# Collaborative One-Click Release Builder

This workflow lets three developers paste the commit SHAs they want included. It combines the lists, sorts commits by committer timestamp oldest-first, cherry-picks each onto a fresh branch from `main`, stops and reports the original commit author on failure, runs your tests, pushes the release branch, and opens a PR into `main`. It never merges or deploys.

## Important behavior and limitation

**Oldest timestamp first is a heuristic, not a guarantee of dependency order.** Git author/committer timestamps do not reliably prove which change depends on another. A commit authored later may be a prerequisite for another commit with skewed clocks or rebased history. This template follows your requested timestamp rule but stops at the first cherry-pick failure.

A commit can also apply cleanly and still depend on omitted code. Tests and review remain necessary.

## Install

Copy these files into your repository:
- `.github/workflows/collaborative-release-builder.yml`
- `scripts/assemble_release.py`

Install the dependency `PyYAML` is not required for this version.

Replace the `Run release tests` step in the workflow with the real test/build commands for your project. The included step intentionally fails until you configure tests; do not remove the guard without adding actual checks.

## Run it

Open **Actions → Collaborative Release Builder → Run workflow**.

Provide:
- Release name: `sprint-10`
- Developer 1 commit SHAs: comma- or space-separated full/abbreviated SHAs
- Developer 2 commit SHAs
- Developer 3 commit SHAs
- Optional approved hotfix SHAs

Every commit must already exist in the repository and be reachable from a pushed branch/tag fetched by the workflow. Do not paste branch names.

The script:
1. Starts from the latest `main`.
2. Validates SHAs and rejects duplicates.
3. Sorts all submitted commits by committer timestamp, oldest first.
4. Cherry-picks each commit one by one.
5. If a cherry-pick fails, prints the original commit author, email, SHA, subject, and stops. It aborts the in-progress cherry-pick and does not push a release branch or open a PR.
6. If all commits apply, runs your configured tests, pushes `release/<release_name>`, and opens a PR into `main`.

## GitHub permissions and protections

The workflow requests `contents: write` and `pull-requests: write`. In repository Settings → Actions → General, allow the necessary workflow permissions. Organization policies may further restrict the token.

Protect `main` with required reviews and CI checks. Keep auto-merge disabled if you want humans to control the final merge. The workflow itself never merges.

## Three-developer testing requirement

The workflow PR body includes a checklist for each developer. Those checkboxes are not identity-verified and must not be treated as security enforcement. For real enforcement:
- Require approval reviews on the PR.
- Configure CODEOWNERS or an appropriate ruleset so each of the three developers (or their team) must approve.
- Require passing CI checks.
- Have each developer test the exact PR head commit. If the branch changes after testing, retest.

A stronger future design would have each developer submit an actual GitHub PR review approval, rather than entering a boolean in a workflow form. GitHub branch protection/rulesets should enforce this; a workflow input alone cannot prove who tested.

## Hotfix handling

Hotfix commits are included in the same timestamp sort as developer commits. This is safer than always applying hotfixes first if they are interleaved with other changes, but timestamps still do not capture dependencies. If a hotfix is already part of `main`, do not submit it; it may become an empty cherry-pick. If a hotfix is a merge commit, `git cherry-pick` needs a mainline parent and this script will stop. Supply the actual hotfix change commits, not the PR merge commit, unless you intentionally adapt the script.

## Current repository caveat

Your `staging` branch has PR merge commits and developer commits interleaved. A SHA entered by a developer must be the actual ticket change commit, not an unrelated staging merge commit. Commits that exist only on an unpushed local branch cannot be fetched by Actions. Push the source branch first.

## How to mark testing complete

The release PR contains a checklist for all three developers. Use actual PR approvals plus required status checks for enforcement. Do not rely on workflow input checkboxes as proof that the person tested it. The release PR is not merged automatically.
