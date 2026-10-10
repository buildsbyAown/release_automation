"""Resolve cherry-pick conflicts with an LLM through Groq's OpenAI-compatible API.

The model gets, per conflicted file: the common base, the release-branch
version, the incoming version, the conflicted text, the incoming commit's diff,
and which tickets wrote each side. It must return the whole resolved file.
A resolution is only accepted if it has no conflict markers and is
syntactically valid (Python compiles, JavaScript parses, HTML tags balance). The caller still runs the release check before committing.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

import check_html

API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_FILE_CHARS = 60_000
MAX_DIFF_CHARS = 20_000
MARKER_RE = re.compile(r"^(<{7}|={7}|>{7}|\|{7})(\s|$)", re.M)
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)

SYSTEM_PROMPT = """You resolve git cherry-pick conflicts while assembling a release branch.
The release branch already contains earlier tickets. An incoming commit from another ticket conflicts with it.
Write the final content of the file so that BOTH the behaviour already on the release branch AND the behaviour the incoming commit introduces keep working.

Rules:
- Keep every function, constant, parameter and behaviour from both sides, unless the incoming commit's own diff clearly removes or replaces it.
- When both sides change the same logic, combine them so each ticket's intent still works.
- Keep existing function signatures compatible; prefer adding optional parameters over changing required ones.
- Do not refactor, rename, reformat, or add anything unrelated to the conflict.
- Reply with the complete resolved file in exactly one fenced code block and no conflict markers, followed by one line starting with "Explanation:" that says how each ticket's behaviour was preserved."""


class ResolutionError(Exception):
    pass


def enabled():
    return bool(os.environ.get("GROQ_API_KEY"))


def model_name():
    return os.environ.get("GROQ_MODEL") or DEFAULT_MODEL


def _chat(messages):
    body = json.dumps({"model": model_name(), "messages": messages, "temperature": 0}).encode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": "collaborative-release-builder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ResolutionError(f"Groq API error {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(f"Could not reach Groq API: {exc.reason}") from exc
    return data["choices"][0]["message"]["content"] or ""


def _section(title, text, limit=MAX_FILE_CHARS):
    if text is None:
        return f"### {title}\n(file does not exist on this side)\n"
    if len(text) > limit:
        text = text[:limit] + "\n... [truncated]"
    return f"### {title}\n```\n{text}\n```\n"


def _validate(path, content):
    if not content.strip():
        return "the resolved file is empty"
    if MARKER_RE.search(content):
        return "the resolved file still contains conflict markers"
    if path.endswith(".py"):
        try:
            compile(content, path, "exec")
        except SyntaxError as exc:
            return f"the resolved file is not valid Python: {exc.msg} on line {exc.lineno}"
    if path.endswith(".js") and shutil.which("node"):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
        try:
            result = subprocess.run(["node", "--check", tmp.name], capture_output=True, text=True)
        finally:
            os.unlink(tmp.name)
        if result.returncode != 0:
            lines = result.stderr.splitlines()
            detail = next((line for line in lines if "Error" in line), "syntax error").strip()[:300]
            return f"the resolved file is not valid JavaScript: {detail}"
    if path.endswith((".html", ".htm")):
        issue = check_html.problem(content)
        if issue:
            return f"the resolved HTML is malformed: {issue}"
    return None


def resolve_file(path, base, ours, theirs, conflicted, context):
    """Return (resolved_content, explanation) or raise ResolutionError.

    context keys: incoming_ticket, incoming_subject, incoming_authors,
    incoming_diff, ticket_commits (list of subjects), release_tickets
    (list of "ticket: subject" for commits already on the branch touching path).
    """
    for name, text in (("base", base), ("release", ours), ("incoming", theirs)):
        if text is not None and len(text) > MAX_FILE_CHARS:
            raise ResolutionError(f"{path} is too large for automatic resolution ({name} side).")

    diff = context["incoming_diff"]
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n... [truncated]"
    release_tickets = "\n".join(f"- {line}" for line in context["release_tickets"]) or "- (only code already on main)"
    ticket_commits = "\n".join(f"- {s}" for s in context["ticket_commits"])

    prompt = (
        f"File: `{path}`\n\n"
        f"## Incoming change\n"
        f"Ticket {context['incoming_ticket']}, commit \"{context['incoming_subject']}\" "
        f"by {context['incoming_authors']}.\n"
        f"All commits of ticket {context['incoming_ticket']} in this release:\n{ticket_commits}\n\n"
        f"Diff of the incoming commit:\n```diff\n{diff}\n```\n\n"
        f"## Already on the release branch\n"
        f"Commits in this release that touched `{path}`:\n{release_tickets}\n\n"
        + _section("BASE (common ancestor)", base)
        + _section("RELEASE (current release branch, keep its behaviour)", ours)
        + _section("INCOMING (version from the incoming commit, keep its behaviour)", theirs)
        + _section("CONFLICTED (git's attempt with markers)", conflicted)
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    last_problem = None
    for _ in range(2):
        reply = _chat(messages)
        blocks = FENCE_RE.findall(reply)
        if not blocks:
            last_problem = "the reply did not contain a fenced code block"
        else:
            content = blocks[0]
            if not content.endswith("\n"):
                content += "\n"
            last_problem = _validate(path, content)
            if last_problem is None:
                match = re.search(r"Explanation:\s*(.+)", reply, re.S)
                explanation = match.group(1).strip() if match else "(no explanation given)"
                return content, explanation
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That is not usable: {last_problem}. Reply again following the rules exactly."},
        ]
    raise ResolutionError(f"AI could not resolve {path}: {last_problem}.")
