#!/usr/bin/env python3
"""Build a release branch from manually supplied commit SHAs.

Commit SHAs from all three developers are combined and sorted by committer time
(oldest first). A deterministic SHA tie-breaker is used for equal timestamps.
Each SHA is cherry-picked individually. On conflict, the script reports the
original commit author, subject, SHA and stops without pushing or opening a PR.

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
        "show", "-s", "--format=%H%x1f%ct%x1f%an%x1f%ae%x1f%s", sha,
        capture=True,
    )
    fields = result.stdout.strip().split("\x1f")
    if len(fields) != 5:
        raise RuntimeError(f"Could not read metadata for commit {sha}")
    full_sha, timestamp, author, email, subject = fields
    return {
        "sha": full_sha,
        "timestamp": int(timestamp),
        "author": author,
        "email": email,
        "subject": subject,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-name", required=True)
    parser.add_argument("--dev1", default="")
    parser.add_argument("--dev2", default="")
    parser.add_argument("--dev3", default="")
    parser.add_argument("--hotfixes", default="")
    args = parser.parse_args()

    if not NAME_RE.fullmatch(args.release_name):
        raise ValueError("Release name may contain only letters, digits, dots, underscores, and hyphens.")

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

    # Oldest committer timestamp first; SHA gives stable order for equal timestamps.
    commits.sort(key=lambda item: (item["timestamp"], item["sha"]))

    ensure_clean = git("status", "--porcelain", capture=True)
    if ensure_clean.stdout.strip():
        raise RuntimeError("Working tree is not clean.")

    branch = f"release/{args.release_name}"
    remote = git("ls-remote", "--heads", "origin", branch, capture=True)
    if remote.stdout.strip():
        raise RuntimeError(
            f"origin/{branch} already exists. Choose a new release name or review/remove the existing branch."
        )

    base = git("rev-parse", "HEAD", capture=True).stdout.strip()
    print(f"Base main commit: {base}")
    print("Commit application order (oldest committer timestamp first):")
    for item in commits:
        when = datetime.fromtimestamp(item["timestamp"], timezone.utc).isoformat()
        print(f"  {when} | {item['author']} | {item['sha']} | {item['subject']}")

    git("switch", "-c", branch)

    for item in commits:
        sha = item["sha"]
        print(f"Cherry-picking {sha} — {item['author']} — {item['subject']}")
        result = git("cherry-pick", sha, check=False)
        if result.returncode != 0:
            print("\n::error::Cherry-pick failed. Resolve the issue before creating a release PR.", file=sys.stderr)
            print(f"Commit: {sha}", file=sys.stderr)
            print(f"Original author: {item['author']} <{item['email']}>", file=sys.stderr)
            print(f"Submitted by: {item['submitted_by']}", file=sys.stderr)
            print(f"Subject: {item['subject']}", file=sys.stderr)
            print(
                "The workflow has stopped. It will not push the branch or open a PR. "
                "The failed cherry-pick may be in progress; on a local reproduction, run "
                "`git cherry-pick --abort` before retrying.",
                file=sys.stderr,
            )
            # Abort so the runner is left in a clean state.
            git("cherry-pick", "--abort", check=False)
            raise RuntimeError(f"Conflict/failure applying {sha} authored by {item['author']}.")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/release-builder-summary.md")
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(f"## Release candidate: {args.release_name}\n\n")
        f.write(f"- Base: `{base}`\n")
        f.write(f"- Selected commits: {len(commits)}\n")
        f.write("- Ordering: committer timestamp, oldest first (heuristic)\n\n")
        f.write("| Order | Author | SHA | Commit |\n|---:|---|---|---|\n")
        for index, item in enumerate(commits, 1):
            f.write(f"| {index} | {item['author']} | `{item['sha']}` | {item['subject'].replace('|', '\\|')} |\n")
    print(f"Successfully assembled {branch}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
