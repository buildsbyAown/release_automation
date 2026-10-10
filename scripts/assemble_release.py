#!/usr/bin/env python3
"""Build a release branch from manually supplied commit SHAs.

Commit SHAs from all three developers are combined and sorted by author time
(oldest first). A deterministic SHA tie-breaker is used for equal timestamps.
Author time is used because it survives cherry-picks and rebases, so a commit
that was re-created to resolve a conflict keeps its original position.
Each SHA is cherry-picked individually. On conflict, the script reports the
original commit author, title, SHA, conflicting files and stops without pushing
or opening a PR.

Run with --local on a developer machine to reproduce the release and leave a
conflicting cherry-pick in progress so it can be resolved by hand.

Important: timestamp order is only a heuristic. It is not a proof of dependency
order. If commits are interdependent, the team should provide an explicit order
or preserve a dependency-aware manifest.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")


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


def branches_containing(sha):
    result = git("branch", "-r", "--contains", sha, check=False, capture=True)
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and "->" not in line
    ]


def is_empty_pick():
    in_progress = git("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False, capture=True)
    if in_progress.returncode != 0:
        return False
    unmerged = git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
    staged = git("diff", "--cached", "--quiet", check=False).returncode
    return not unmerged and staged == 0


def report_failure(item, applied, release_name):
    conflicted = git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.split()
    branches = branches_containing(item["sha"])
    short = item["sha"][:7]

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
    ]
    if conflicted:
        lines.append(f"  Conflicting files: {', '.join(conflicted)}")
    else:
        lines.append("  No conflicting files reported; see the git error above.")
    lines.append("  Commits applied before it:")
    lines.extend(f"    - {a['sha'][:7]} {a['subject']} ({a['author']})" for a in applied)
    if not applied:
        lines.append("    (none)")
    print("\n" + "\n".join(lines), file=sys.stderr)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## Release {release_name}: cherry-pick conflict\n\n")
            f.write(f"**Commit:** `{short}` {item['subject']}\n\n")
            f.write(f"**Author(s) to resolve:** {', '.join(item['responsible'])} ({item['submitted_by']})\n\n")
            if item["is_merge"]:
                f.write(f"**Merged by:** {item['author']} <{item['email']}>\n\n")
            f.write(f"**Found on:** {', '.join(branches) or 'unknown branch'}\n\n")
            f.write(f"**Conflicting files:** {', '.join(conflicted) or 'none reported; see the step log'}\n\n")
            f.write("To resolve, run the same commit list locally with `--local`; see README.\n")

    return conflicted


def print_local_instructions(item, conflicted):
    files = " ".join(conflicted) or "<files>"
    print(
        "\nThe cherry-pick is left in progress so you can resolve it here:\n"
        f"  1. Fix the conflict markers in: {files}\n"
        f"  2. git add {files}\n"
        "  3. git cherry-pick --continue\n"
        f"  4. git push origin HEAD:refs/heads/resolved/{item['sha'][:7]}\n"
        "  5. git rev-parse --short HEAD   # the new SHA\n"
        f"  6. Replace {item['sha'][:7]} with the new SHA in the commit list, then re-run this\n"
        "     command to check the remaining commits. When it succeeds, use that list in the workflow.\n"
        "To give up instead: git cherry-pick --abort && git switch main",
        file=sys.stderr,
    )


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
        help="Run on a developer machine: start from origin/main on a detached HEAD and leave a "
             "conflicting cherry-pick in progress for manual resolution.",
    )
    args = parser.parse_args()

    if not NAME_RE.fullmatch(args.release_name):
        raise ValueError("Release name may contain only letters, digits, dots, underscores, and hyphens.")

    if args.local:
        git("fetch", "origin")

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

    # Reject duplicates, which can otherwise cause empty cherry-picks.
    seen = {}
    for sha, source in submitted:
        if sha in seen:
            raise ValueError(f"Commit {sha} was entered more than once ({seen[sha]} and {source}).")
        seen[sha] = source

    # Validate commits and gather author + timestamp metadata.
    commits = []
    for sha, source in submitted:
        check = git("cat-file", "-e", f"{sha}^{{commit}}", check=False)
        if check.returncode != 0:
            raise ValueError(
                f"Commit {sha} from {source} is not available in this checkout. "
                "The commit must be pushed to a branch/tag reachable by the workflow checkout."
            )
        info = commit_info(sha)
        info["submitted_by"] = source
        commits.append(info)

    # Oldest author timestamp first; SHA gives stable order for equal timestamps.
    commits.sort(key=lambda item: (item["timestamp"], item["sha"]))

    ensure_clean = git("status", "--porcelain", "--untracked-files=no", capture=True)
    if ensure_clean.stdout.strip():
        raise RuntimeError("Working tree has uncommitted changes. Commit or stash them first.")

    branch = f"release/{args.release_name}"
    if not args.local:
        remote = git("ls-remote", "--heads", "origin", branch, capture=True)
        if remote.stdout.strip():
            raise RuntimeError(
                f"origin/{branch} already exists. Choose a new release name or review/remove the existing branch."
            )

    base_ref = "origin/main" if args.local else "HEAD"
    base = git("rev-parse", base_ref, capture=True).stdout.strip()
    print(f"Base main commit: {base}")
    print("Commit application order (oldest author timestamp first):")
    for item in commits:
        when = datetime.fromtimestamp(item["timestamp"], timezone.utc).isoformat()
        kind = "PR merge" if item["is_merge"] else "commit"
        print(f"  {when} | {', '.join(item['responsible'])} | {item['sha'][:7]} ({kind}) | {item['subject']}")

    if args.local:
        git("switch", "--detach", base)
    else:
        git("switch", "-c", branch)

    applied = []
    skipped = []
    for item in commits:
        sha = item["sha"]
        authors = ", ".join(item["responsible"])
        print(f"Cherry-picking {sha[:7]} \"{item['subject']}\" by {authors}")
        # -m 1 applies a PR merge as the diff against the branch it was merged into.
        pick = ["cherry-pick", "-m", "1", sha] if item["is_merge"] else ["cherry-pick", sha]
        result = git(*pick, check=False)
        if result.returncode != 0 and is_empty_pick():
            print(f"::warning::Skipped {sha[:7]} \"{item['subject']}\": its changes are already included.")
            git("cherry-pick", "--skip", capture=True)
            skipped.append(item)
            continue
        if result.returncode != 0:
            conflicted = report_failure(item, applied, args.release_name)
            if args.local:
                print_local_instructions(item, conflicted)
                sys.exit(1)
            git("cherry-pick", "--abort", check=False, capture=True)
            files = ", ".join(conflicted) or "none reported; see the step log"
            raise RuntimeError(
                f"Conflict applying {sha[:7]} \"{item['subject']}\" by {authors} "
                f"({item['submitted_by']}). Conflicting files: {files}"
            )
        applied.append(item)

    if args.local:
        print(f"\n{len(applied)} commits apply cleanly on origin/main ({len(skipped)} skipped as already included). "
              "Use this commit list in the workflow.")
        print("You are on a detached HEAD; run `git switch main` to go back.")
        return

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/release-builder-summary.md")
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(f"## Release candidate: {args.release_name}\n\n")
        f.write(f"- Base: `{base}`\n")
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
