#!/usr/bin/env python3
"""Build a resumable release branch from tickets and their commit SHAs.

Each ticket is given as "<ticket>: <sha> <sha> ...". All commits are combined
and sorted by author time (oldest first), with a SHA tie-breaker. Plain commits
and PR merge commits are accepted; a merge commit is applied as the PR's
changes (`cherry-pick -m 1`).

Every commit is cherry-picked with -x, which records
"(cherry picked from commit <sha>)" in the new commit. That line is how the
script knows what is already on release/<name>, so a run can resume.

On a conflict:
  * With --ai and GROQ_API_KEY set, each conflicted file is resolved by an LLM
    that is told which tickets wrote each side and must keep both behaviours.
    The result must have no markers, compile, and pass scripts/release_check.sh.
    Accepted resolutions are recorded in the commit message and the release PR.
  * Otherwise, or if the AI resolution is rejected, the commits applied so far
    are pushed to release/<name> and the run stops naming the author(s); the
    author resolves that one commit and re-runs with the same inputs.

Run with --local on a developer machine to do the same on a local
release/<name> branch, leaving a conflicting cherry-pick in progress so it can
be resolved by hand.

Important: timestamp order is only a heuristic. It is not a proof of dependency
order, and AI resolutions must be reviewed.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_resolver  # noqa: E402


SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
TICKET_RE = re.compile(r"^\s*#?([A-Za-z0-9][A-Za-z0-9._-]{0,40})\s*:\s*(.*)$", re.S)
PICKED_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{40})\)")
CHECK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release_check.sh")


def run(args, check=True, capture=False):
    return subprocess.run(
        args,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def git(*args, check=True, capture=False):
    return run(["git", *args], check=check, capture=capture)


def ref_exists(ref):
    return git("rev-parse", "-q", "--verify", ref, check=False, capture=True).returncode == 0


def parse_shas(value, source):
    values = [x for x in re.split(r"[\s,;]+", value.strip()) if x]
    for sha in values:
        if not SHA_RE.fullmatch(sha):
            raise ValueError(f"{source}: invalid commit SHA {sha!r}. Supply commit hashes, not branch names.")
    return values


def parse_ticket(value):
    match = TICKET_RE.match(value)
    if not match:
        raise ValueError(f"Invalid ticket entry {value!r}. Use the format '20: 6569375 b44a336'.")
    ticket, shas = match.group(1), parse_shas(match.group(2), f"Ticket {match.group(1)}")
    if not shas:
        raise ValueError(f"Ticket {ticket} has no commits.")
    return ticket, shas


def commit_info(sha):
    result = git(
        "show", "-s", "--format=%H%x1f%at%x1f%an%x1f%ae%x1f%s%x1f%P", sha,
        capture=True,
    )
    fields = result.stdout.strip().split("\x1f")
    if len(fields) != 6:
        raise RuntimeError(f"Could not read metadata for commit {sha}")
    full_sha, timestamp, author, email, subject, parents = fields
    parents = parents.split()
    if len(parents) > 2:
        raise ValueError(f"Commit {full_sha[:7]} \"{subject}\" is an octopus merge and cannot be cherry-picked.")
    is_merge = len(parents) == 2
    if is_merge:
        # The PR's own commits: reachable from the merged branch but not from the target branch.
        log = git("log", "--no-merges", "--format=%an <%ae>", f"{parents[0]}..{parents[1]}", capture=True)
        responsible = list(dict.fromkeys(log.stdout.splitlines())) or [f"{author} <{email}>"]
    else:
        responsible = [f"{author} <{email}>"]
    return {
        "sha": full_sha,
        "timestamp": int(timestamp),
        "author": author,
        "email": email,
        "subject": subject,
        "is_merge": is_merge,
        "responsible": responsible,
    }


def pick_command(item):
    return ["cherry-pick", "-x", "-m", "1", item["sha"]] if item["is_merge"] else ["cherry-pick", "-x", item["sha"]]


def release_log(*paths):
    """(release sha, original sha or None, body) for each commit on the branch since it left main."""
    out = git("log", "--format=%H%x1f%B%x1e", "origin/main..HEAD", "--", *paths, capture=True).stdout
    entries = []
    for entry in out.split("\x1e"):
        if not entry.strip():
            continue
        sha, body = entry.strip().split("\x1f", 1)
        found = PICKED_RE.findall(body)
        entries.append((sha, found[-1] if found else None, body))
    return entries


def already_picked():
    picked, unmarked = set(), []
    for sha, original, body in release_log():
        if original:
            picked.add(original)
        else:
            unmarked.append(f"{sha[:7]} {body.splitlines()[0] if body else ''}")
    return picked, unmarked


def branches_containing(sha):
    result = git("branch", "-r", "--contains", sha, check=False, capture=True)
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and "->" not in line
    ]


def unmerged_files():
    return git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.split()


def is_empty_pick():
    if not ref_exists("CHERRY_PICK_HEAD"):
        return False
    staged = git("diff", "--cached", "--quiet", check=False).returncode
    return not unmerged_files() and staged == 0


def stage_content(stage, path):
    result = subprocess.run(["git", "show", f":{stage}:{path}"], capture_output=True)
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ai_resolver.ResolutionError(f"{path} is not a text file.") from exc


def ai_resolve(item, by_sha, by_ticket):
    """Resolve the in-progress conflict with the AI and commit it. Returns the resolved paths."""
    paths = unmerged_files()
    if not paths:
        raise ai_resolver.ResolutionError("git reported a failure without conflicting files.")

    ticket_commits = [f"{c['sha'][:7]} {c['subject']}" for c in by_ticket[item["ticket"]]]

    other_tickets = set()
    notes = []
    for path in paths:
        ours, theirs = stage_content(2, path), stage_content(3, path)
        if ours is None or theirs is None:
            raise ai_resolver.ResolutionError(f"{path} was deleted on one side; a person must decide.")
        incoming_diff = git("diff", f"{item['sha']}^1", item["sha"], "--", path, capture=True).stdout

        release_tickets = []
        for _, original, _ in release_log(path):
            known = by_sha.get(original)
            if known:
                other_tickets.add(known["ticket"])
                release_tickets.append(f"Ticket {known['ticket']}: {known['subject']} ({', '.join(known['responsible'])})")

        print(f"Asking {ai_resolver.model_name()} to resolve {path} ...")
        content, explanation = ai_resolver.resolve_file(path, ours, theirs, {
            "incoming_ticket": item["ticket"],
            "incoming_subject": item["subject"],
            "incoming_authors": ", ".join(item["responsible"]),
            "incoming_diff": incoming_diff,
            "ticket_commits": ticket_commits,
            "release_tickets": release_tickets,
        })
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        git("add", "--", path)
        notes.append(f"{path}: {' '.join(explanation.split())[:500]}")
        print(f"  Resolved {path}: {explanation}")

    check = run(["bash", CHECK_SCRIPT], check=False, capture=True)
    if check.returncode != 0:
        output = (check.stdout + check.stderr).strip().splitlines()[-5:]
        raise ai_resolver.ResolutionError("release check failed after AI resolution: " + " | ".join(output))

    git("-c", "core.editor=true", "cherry-pick", "--continue", capture=True)
    message = git("log", "-1", "--format=%B", capture=True).stdout.rstrip()
    tickets = ", ".join([f"{item['ticket']} (incoming)"] + sorted(other_tickets - {item["ticket"]}))
    trailers = [
        f"AI-resolved-conflict: {', '.join(paths)}",
        f"AI-resolved-tickets: {tickets}",
        f"AI-resolver-model: {ai_resolver.model_name()}",
    ] + [f"AI-resolution-note: {note}" for note in notes]
    git("commit", "--amend", "--quiet", "-m", message + "\n\n" + "\n".join(trailers))
    return paths


def local_command(args):
    parts = ["python3", "scripts/assemble_release.py", "--local", "--release-name", args.release_name]
    for ticket, shas in args.tickets:
        parts += ["--ticket", f"{ticket}: {' '.join(shas)}"]
    return " ".join(shlex.quote(p) for p in parts)


def report_failure(item, conflicted, done_count, total, args, ai_problem=None):
    branches = branches_containing(item["sha"])
    short = item["sha"][:7]
    branch = f"release/{args.release_name}"
    pick = "git " + " ".join(pick_command(item))

    lines = [
        f"Cherry-pick failed on commit {short}: \"{item['subject']}\"",
        f"  Ticket:          {item['ticket']}",
        f"  Commit:          {item['sha']}",
        f"  Title:           {item['subject']}",
        f"  Author(s) to resolve: {', '.join(item['responsible'])}",
    ]
    if item["is_merge"]:
        lines.append(f"  Merged by:       {item['author']} <{item['email']}>")
    lines += [
        f"  Found on:        {', '.join(branches) or 'unknown branch'}",
        f"  Conflicting files: {', '.join(conflicted) or 'none reported; see the git error above'}",
        f"  Progress:        {done_count} of {total} commits are on {branch}",
    ]
    if ai_problem:
        lines.append(f"  AI resolution:   not applied ({ai_problem})")
    print("\n" + "\n".join(lines), file=sys.stderr)

    steps = (
        f"git fetch origin\n"
        f"git switch {branch} && git pull --ff-only\n"
        f"{pick}\n"
        f"# fix the conflict markers in: {' '.join(conflicted) or '<files>'}\n"
        f"git add <files> && git cherry-pick --continue\n"
        f"git push origin {branch}"
    )
    if not args.local:
        print(
            f"\nProgress was pushed to {branch}. To resolve only this commit:\n{steps}\n"
            "Then re-run the workflow with the same inputs; it continues from the next commit.\n"
            f"Or resolve this and any later conflicts locally in one go:\n  {local_command(args)}",
            file=sys.stderr,
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## Release {args.release_name}: paused on a cherry-pick conflict\n\n")
            f.write(f"**Ticket:** {item['ticket']}\n\n")
            f.write(f"**Commit:** `{short}` {item['subject']}\n\n")
            f.write(f"**Author(s) to resolve:** {', '.join(item['responsible'])}\n\n")
            if item["is_merge"]:
                f.write(f"**Merged by:** {item['author']} <{item['email']}>\n\n")
            f.write(f"**Found on:** {', '.join(branches) or 'unknown branch'}\n\n")
            f.write(f"**Conflicting files:** {', '.join(conflicted) or 'none reported; see the step log'}\n\n")
            if ai_problem:
                f.write(f"**AI resolution not applied:** {ai_problem}\n\n")
            f.write(f"**Progress saved:** {done_count} of {total} commits are on `{branch}`.\n\n")
            f.write(f"### Resolve only this commit\n\n```bash\n{steps}\n```\n\n")
            f.write("Then re-run the workflow with the same inputs; it continues from the next commit.\n\n")
            f.write(f"Or resolve this and any later conflicts locally in one go:\n\n```bash\n{local_command(args)}\n```\n")


def print_local_instructions(conflicted, args):
    files = " ".join(conflicted) or "<files>"
    print(
        "\nThe cherry-pick is left in progress so you can resolve it here:\n"
        f"  1. Fix the conflict markers in: {files}\n"
        f"  2. git add {files} && git cherry-pick --continue\n"
        f"  3. Run the same command again to continue with the next commits:\n"
        f"     {local_command(args)}\n"
        f"  4. When it reports that all commits are applied: git push origin release/{args.release_name}\n"
        "     and re-run the workflow with the same inputs to test and open the PR.\n"
        "To give up instead: git cherry-pick --abort && git switch main",
        file=sys.stderr,
    )


def switch_to_release_branch(branch, local):
    remote_ref = f"refs/remotes/origin/{branch}"
    if local and ref_exists(f"refs/heads/{branch}"):
        git("switch", branch)
        if ref_exists(remote_ref):
            behind = git("rev-list", "--count", f"HEAD..origin/{branch}", capture=True).stdout.strip()
            if behind != "0":
                git("merge", "--ff-only", f"origin/{branch}")
        return "resumed local"
    if ref_exists(remote_ref):
        git("switch", "-C", branch, f"origin/{branch}")
        return "resumed"
    git("switch", "--no-track", "-c", branch, "origin/main")
    return "new"


def write_pr_body(path, args, commits, by_sha, skipped):
    """Describe tickets and every AI resolution on the branch, including ones from earlier runs."""
    lines = [
        f"## Release candidate: {args.release_name}",
        "",
        "Assembled by Collaborative Release Builder from the latest `main` "
        "(commits oldest author date first). This workflow does not merge or deploy the release.",
        "",
        "### Tickets",
        "",
        "| Ticket | Commit | Author(s) | Status |",
        "|---|---|---|---|",
    ]
    for ticket, _ in args.tickets:
        for item in (c for c in commits if c["ticket"] == ticket):
            status = "skipped (already included)" if item in skipped else "applied"
            subject = item["subject"].replace("|", "\\|")
            lines.append(f"| {ticket} | `{item['sha'][:7]}` {subject} | {', '.join(item['responsible'])} | {status} |")

    ai_commits = [(sha, original, body) for sha, original, body in release_log() if "AI-resolved-conflict:" in body]
    review_items = []
    if ai_commits:
        lines += ["", "### AI-resolved conflicts (review required)", ""]
        for sha, original, body in reversed(ai_commits):
            trailers = dict(
                re.match(r"(AI-[\w-]+):\s*(.*)", line).groups()
                for line in body.splitlines() if re.match(r"AI-[\w-]+:", line) and not line.startswith("AI-resolution-note")
            )
            known = by_sha.get(original, {})
            files = trailers.get("AI-resolved-conflict", "")
            notes = [line.split(":", 1)[1].strip() for line in body.splitlines() if line.startswith("AI-resolution-note:")]
            lines.append(
                f"**`{sha[:7]}`** (from `{(original or '')[:7]}` \"{known.get('subject', '')}\"), "
                f"tickets {trailers.get('AI-resolved-tickets', '?')}, files `{files}`, "
                f"model `{trailers.get('AI-resolver-model', '?')}`"
            )
            lines += [f"- {note}" for note in notes]
            diff = git("show", "--format=", sha, "--", *files.split(", "), capture=True).stdout
            lines += ["", "<details><summary>Diff</summary>", "", "```diff", diff.rstrip(), "```", "", "</details>", ""]
            review_items.append(
                f"- [ ] Owners of tickets {trailers.get('AI-resolved-tickets', '?')} reviewed the AI resolution "
                f"of `{files}` in `{sha[:7]}`"
            )

    lines += [
        "",
        "### Required validation",
        *review_items,
        "- [ ] Developer 1 tested and approved this exact release candidate",
        "- [ ] Developer 2 tested and approved this exact release candidate",
        "- [ ] Developer 3 tested and approved this exact release candidate",
        "- [ ] Required CI checks passed",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-name")
    parser.add_argument("--ticket", action="append", default=[], help="'<ticket>: <sha> <sha> ...' (repeatable)")
    parser.add_argument("--hotfixes", default="")
    parser.add_argument(
        "--from-workflow-inputs",
        action="store_true",
        help="Read release_name, ticket_* and approved_hotfix_commits from the WORKFLOW_INPUTS JSON env var.",
    )
    parser.add_argument("--ai", action="store_true", help="Try to resolve conflicts with the AI (needs GROQ_API_KEY).")
    parser.add_argument("--pr-body", help="Write the release PR description to this file on success.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run on a developer machine on a local release/<name> branch and leave a conflicting "
             "cherry-pick in progress for manual resolution. Never pushes.",
    )
    args = parser.parse_args()

    if args.from_workflow_inputs:
        inputs = json.loads(os.environ.get("WORKFLOW_INPUTS", "{}"))
        args.release_name = args.release_name or inputs.get("release_name")
        slots = sorted((k for k in inputs if k.startswith("ticket_")), key=lambda k: int(k.split("_")[1]))
        args.ticket += [inputs[k] for k in slots if str(inputs[k]).strip()]
        args.hotfixes = args.hotfixes or inputs.get("approved_hotfix_commits") or ""

    if not args.release_name or not NAME_RE.fullmatch(args.release_name):
        raise ValueError("Release name may contain only letters, digits, dots, underscores, and hyphens.")

    args.tickets = [parse_ticket(value) for value in args.ticket]
    if args.hotfixes.strip():
        args.tickets.append(("hotfix", parse_shas(args.hotfixes, "Approved hotfix")))
    ticket_ids = [t for t, _ in args.tickets]
    duplicates = {t for t in ticket_ids if ticket_ids.count(t) > 1}
    if duplicates:
        raise ValueError(f"Ticket(s) entered more than once: {', '.join(sorted(duplicates))}. Put all of a ticket's commits in one slot.")
    if not args.tickets:
        raise ValueError("No tickets or commits were supplied.")

    git("fetch", "--quiet", "origin")

    # Validate commits and gather author + timestamp metadata.
    commits = []
    by_sha = {}
    for ticket, shas in args.tickets:
        for sha in shas:
            if not ref_exists(f"{sha}^{{commit}}"):
                raise ValueError(
                    f"Commit {sha} from ticket {ticket} is not available in this checkout. "
                    "The commit must be pushed to a branch/tag reachable by the workflow checkout."
                )
            info = commit_info(sha)
            if info["sha"] in by_sha:
                raise ValueError(f"Commit {sha} was entered more than once (tickets {by_sha[info['sha']]['ticket']} and {ticket}).")
            info["ticket"] = ticket
            by_sha[info["sha"]] = info
            commits.append(info)
    by_ticket = {ticket: [c for c in commits if c["ticket"] == ticket] for ticket in ticket_ids}

    # Oldest author timestamp first; SHA gives stable order for equal timestamps.
    commits.sort(key=lambda item: (item["timestamp"], item["sha"]))

    ensure_clean = git("status", "--porcelain", "--untracked-files=no", capture=True)
    if ensure_clean.stdout.strip() or ref_exists("CHERRY_PICK_HEAD"):
        raise RuntimeError(
            "Working tree has uncommitted changes or a cherry-pick in progress. "
            "Finish it (git cherry-pick --continue) or abort it first."
        )

    use_ai = args.ai and ai_resolver.enabled()
    if args.ai and not use_ai:
        print("::notice::GROQ_API_KEY is not set; conflicts will not be resolved automatically.")

    branch = f"release/{args.release_name}"
    mode = switch_to_release_branch(branch, args.local)

    picked, unmarked = already_picked()
    unknown = picked - set(by_sha)
    if unknown:
        raise RuntimeError(
            f"{branch} contains commits that are not in the submitted list: "
            f"{', '.join(s[:7] for s in sorted(unknown))}. Submit the same list as before, "
            f"or delete {branch} to start over."
        )
    for line in unmarked:
        print(f"::warning::{branch} has a commit without a 'cherry picked from' line, kept as-is: {line}")

    print(f"Release branch: {branch} ({mode})")
    print("Commit application order (oldest author timestamp first):")
    for item in commits:
        when = datetime.fromtimestamp(item["timestamp"], timezone.utc).isoformat()
        kind = "PR merge" if item["is_merge"] else "commit"
        status = "done" if item["sha"] in picked else "todo"
        print(f"  [{status}] {when} | ticket {item['ticket']} | {', '.join(item['responsible'])} | "
              f"{item['sha'][:7]} ({kind}) | {item['subject']}")

    applied = [item for item in commits if item["sha"] in picked]
    skipped = []
    for item in commits:
        if item["sha"] in picked:
            continue
        sha = item["sha"]
        authors = ", ".join(item["responsible"])
        print(f"Cherry-picking {sha[:7]} (ticket {item['ticket']}) \"{item['subject']}\" by {authors}")
        result = git(*pick_command(item), check=False)
        if result.returncode != 0 and is_empty_pick():
            print(f"::warning::Skipped {sha[:7]} \"{item['subject']}\": its changes are already included.")
            git("cherry-pick", "--skip", capture=True)
            skipped.append(item)
            continue
        if result.returncode != 0:
            conflicted = unmerged_files()
            ai_problem = None
            if use_ai:
                try:
                    paths = ai_resolve(item, by_sha, by_ticket)
                    print(f"::warning::AI resolved a conflict in {', '.join(paths)} for ticket {item['ticket']} "
                          f"({sha[:7]}). It is listed in the release PR for review.")
                    applied.append(item)
                    continue
                except ai_resolver.ResolutionError as exc:
                    ai_problem = str(exc)
                    print(f"::warning::{ai_problem}")
                    git("cherry-pick", "--abort", check=False, capture=True)
                    git(*pick_command(item), check=False, capture=True)
            report_failure(item, conflicted, len(applied), len(commits), args, ai_problem)
            if args.local:
                print_local_instructions(conflicted, args)
                sys.exit(1)
            git("cherry-pick", "--abort", check=False, capture=True)
            git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
            files = ", ".join(conflicted) or "none reported; see the step log"
            raise RuntimeError(
                f"Conflict applying {sha[:7]} (ticket {item['ticket']}) \"{item['subject']}\" by {authors}. "
                f"Conflicting files: {files}. "
                f"Progress saved on {branch}: {len(applied)} of {len(commits)} commits applied."
            )
        applied.append(item)

    if args.pr_body:
        write_pr_body(args.pr_body, args, commits, by_sha, skipped)

    if args.local:
        print(f"\nAll commits are on {branch} ({len(skipped)} skipped as already included).")
        print(f"Next: git push origin {branch}, then re-run the workflow with the same inputs.")
        return

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/release-builder-summary.md")
    with open(summary_path, "a", encoding="utf-8") as f:
        if args.pr_body:
            with open(args.pr_body, encoding="utf-8") as body:
                f.write(body.read())
        else:
            f.write(f"## Release candidate: {args.release_name}\n\nAll {len(commits)} commits processed.\n")
    print(f"Successfully assembled {branch}")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    try:
        main()
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
