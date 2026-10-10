#!/usr/bin/env python3
"""Build a resumable release branch from manually supplied commit SHAs.

Commit SHAs from all three developers are combined and sorted by author time
(oldest first). A deterministic SHA tie-breaker is used for equal timestamps.
Plain commits and PR merge commits are accepted; a merge commit is applied as
the PR's changes (`cherry-pick -m 1`).

Every commit is cherry-picked with -x, which records
"(cherry picked from commit <sha>)" in the new commit. That line is how the
script knows what is already on release/<name>, so a run can resume:

  * On conflict, the commits applied so far are pushed to release/<name> and
    the run stops without opening a PR. The author resolves only the
    conflicting commit on that branch and pushes.
  * Re-running with the same inputs continues from the next commit.

Run with --local on a developer machine to do the same on a local
release/<name> branch, leaving a conflicting cherry-pick in progress so it can
be resolved by hand.

Important: timestamp order is only a heuristic. It is not a proof of dependency
order. If commits are interdependent, the team should provide an explicit order
or preserve a dependency-aware manifest.
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone


SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
PICKED_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{40})\)")


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


def already_picked():
    """SHAs recorded by `cherry-pick -x` on the current branch since it left main, plus commits without that line."""
    log = git("log", "--format=%H%x1f%s%x1f%B%x1e", "origin/main..HEAD", capture=True).stdout
    picked, unmarked = set(), []
    for entry in log.split("\x1e"):
        if not entry.strip():
            continue
        sha, subject, body = entry.strip().split("\x1f", 2)
        found = PICKED_RE.findall(body)
        if found:
            picked.update(found)
        else:
            unmarked.append(f"{sha[:7]} {subject}")
    return picked, unmarked


def branches_containing(sha):
    result = git("branch", "-r", "--contains", sha, check=False, capture=True)
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and "->" not in line
    ]


def is_empty_pick():
    if not ref_exists("CHERRY_PICK_HEAD"):
        return False
    unmerged = git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
    staged = git("diff", "--cached", "--quiet", check=False).returncode
    return not unmerged and staged == 0


def local_command(args):
    parts = ["python3", "scripts/assemble_release.py", "--local", "--release-name", args.release_name]
    for flag, value in (("--dev1", args.dev1), ("--dev2", args.dev2), ("--dev3", args.dev3), ("--hotfixes", args.hotfixes)):
        if value.strip():
            parts += [flag, " ".join(re.split(r"[\s,;]+", value.strip()))]
    return " ".join(shlex.quote(p) for p in parts)


def report_failure(item, done_count, total, args):
    conflicted = git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.split()
    branches = branches_containing(item["sha"])
    short = item["sha"][:7]
    branch = f"release/{args.release_name}"
    pick = "git " + " ".join(pick_command(item))

    lines = [
        f"Cherry-pick failed on commit {short}: \"{item['subject']}\"",
        f"  Commit:          {item['sha']}",
        f"  Title:           {item['subject']}",
        f"  Author(s) to resolve: {', '.join(item['responsible'])}",
    ]
    if item["is_merge"]:
        lines.append(f"  Merged by:       {item['author']} <{item['email']}>")
    lines += [
        f"  Submitted by:    {item['submitted_by']}",
        f"  Found on:        {', '.join(branches) or 'unknown branch'}",
        f"  Conflicting files: {', '.join(conflicted) or 'none reported; see the git error above'}",
        f"  Progress:        {done_count} of {total} commits are on {branch}",
    ]
    print("\n" + "\n".join(lines), file=sys.stderr)

    if not args.local:
        steps = (
            f"git fetch origin\n"
            f"git switch {branch} && git pull --ff-only\n"
            f"{pick}\n"
            f"# fix the conflict markers in: {' '.join(conflicted) or '<files>'}\n"
            f"git add <files> && git cherry-pick --continue\n"
            f"git push origin {branch}"
        )
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
            f.write(f"**Commit:** `{short}` {item['subject']}\n\n")
            f.write(f"**Author(s) to resolve:** {', '.join(item['responsible'])} ({item['submitted_by']})\n\n")
            if item["is_merge"]:
                f.write(f"**Merged by:** {item['author']} <{item['email']}>\n\n")
            f.write(f"**Found on:** {', '.join(branches) or 'unknown branch'}\n\n")
            f.write(f"**Conflicting files:** {', '.join(conflicted) or 'none reported; see the step log'}\n\n")
            f.write(f"**Progress saved:** {done_count} of {total} commits are on `{branch}`.\n\n")
            f.write(f"### Resolve only this commit\n\n```bash\n{steps}\n```\n\n")
            f.write("Then re-run the workflow with the same inputs; it continues from the next commit.\n\n")
            f.write(f"Or resolve this and any later conflicts locally in one go:\n\n```bash\n{local_command(args)}\n```\n")

    return conflicted


def print_local_instructions(item, conflicted, args):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-name", required=True)
    parser.add_argument("--dev1", default="")
    parser.add_argument("--dev2", default="")
    parser.add_argument("--dev3", default="")
    parser.add_argument("--hotfixes", default="")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run on a developer machine on a local release/<name> branch and leave a conflicting "
             "cherry-pick in progress for manual resolution. Never pushes.",
    )
    args = parser.parse_args()

    if not NAME_RE.fullmatch(args.release_name):
        raise ValueError("Release name may contain only letters, digits, dots, underscores, and hyphens.")

    git("fetch", "--quiet", "origin")

    submitted = []
    for developer, value in (
        ("Developer 1", args.dev1),
        ("Developer 2", args.dev2),
        ("Developer 3", args.dev3),
        ("Approved hotfix", args.hotfixes),
    ):
        for sha in parse_shas(value, developer):
            submitted.append((sha.lower(), developer))

    if not submitted:
        raise ValueError("No commits were supplied.")

    # Validate commits and gather author + timestamp metadata.
    commits = []
    seen = {}
    for sha, source in submitted:
        if not ref_exists(f"{sha}^{{commit}}"):
            raise ValueError(
                f"Commit {sha} from {source} is not available in this checkout. "
                "The commit must be pushed to a branch/tag reachable by the workflow checkout."
            )
        info = commit_info(sha)
        if info["sha"] in seen:
            raise ValueError(f"Commit {sha} was entered more than once ({seen[info['sha']]} and {source}).")
        seen[info["sha"]] = source
        info["submitted_by"] = source
        commits.append(info)

    # Oldest author timestamp first; SHA gives stable order for equal timestamps.
    commits.sort(key=lambda item: (item["timestamp"], item["sha"]))

    ensure_clean = git("status", "--porcelain", "--untracked-files=no", capture=True)
    if ensure_clean.stdout.strip() or ref_exists("CHERRY_PICK_HEAD"):
        raise RuntimeError(
            "Working tree has uncommitted changes or a cherry-pick in progress. "
            "Finish it (git cherry-pick --continue) or abort it first."
        )

    branch = f"release/{args.release_name}"
    mode = switch_to_release_branch(branch, args.local)

    picked, unmarked = already_picked()
    unknown = picked - set(seen)
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
        print(f"  [{status}] {when} | {', '.join(item['responsible'])} | {item['sha'][:7]} ({kind}) | {item['subject']}")

    applied = [item for item in commits if item["sha"] in picked]
    skipped = []
    for item in commits:
        if item["sha"] in picked:
            continue
        sha = item["sha"]
        authors = ", ".join(item["responsible"])
        print(f"Cherry-picking {sha[:7]} \"{item['subject']}\" by {authors}")
        result = git(*pick_command(item), check=False)
        if result.returncode != 0 and is_empty_pick():
            print(f"::warning::Skipped {sha[:7]} \"{item['subject']}\": its changes are already included.")
            git("cherry-pick", "--skip", capture=True)
            skipped.append(item)
            continue
        if result.returncode != 0:
            if args.local:
                conflicted = report_failure(item, len(applied), len(commits), args)
                print_local_instructions(item, conflicted, args)
                sys.exit(1)
            conflicted = report_failure(item, len(applied), len(commits), args)
            git("cherry-pick", "--abort", check=False, capture=True)
            git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
            files = ", ".join(conflicted) or "none reported; see the step log"
            raise RuntimeError(
                f"Conflict applying {sha[:7]} \"{item['subject']}\" by {authors} "
                f"({item['submitted_by']}). Conflicting files: {files}. "
                f"Progress saved on {branch}: {len(applied)} of {len(commits)} commits applied."
            )
        applied.append(item)

    if args.local:
        print(f"\nAll commits are on {branch} ({len(skipped)} skipped as already included).")
        print(f"Next: git push origin {branch}, then re-run the workflow with the same inputs.")
        return

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/release-builder-summary.md")
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(f"## Release candidate: {args.release_name}\n\n")
        f.write(f"- Base: `{git('merge-base', 'HEAD', 'origin/main', capture=True).stdout.strip()}`\n")
        f.write(f"- Selected commits: {len(commits)}\n")
        f.write("- Ordering: author timestamp, oldest first (heuristic)\n\n")
        f.write("| Order | Author | SHA | Commit |\n|---:|---|---|---|\n")
        for index, item in enumerate(applied, 1):
            subject = item["subject"].replace("|", "\\|")
            f.write(f"| {index} | {', '.join(item['responsible'])} | `{item['sha']}` | {subject} |\n")
        if skipped:
            f.write("\n**Skipped (changes already included):**\n\n")
            for item in skipped:
                f.write(f"- `{item['sha'][:7]}` {item['subject']}\n")
    print(f"Successfully assembled {branch}")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    try:
        main()
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
