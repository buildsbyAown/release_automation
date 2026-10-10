# Collaborative One-Click Release Builder

This workflow lets three developers paste the commit SHAs they want included. It combines the lists, sorts commits by author timestamp oldest-first, cherry-picks each onto a fresh branch from `main`, stops and reports the original commit author on failure, runs your tests, pushes the release branch, and opens a PR into `main`. It never merges or deploys.

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
3. Sorts all submitted commits by author timestamp, oldest first. You can submit plain commits or PR merge commits (`Merge pull request #N ...`); a merge commit is applied as that PR's changes (`git cherry-pick -m 1`). Do not submit "Merge branch 'staging' into ..." sync merges, as they would bring in the whole target branch.
4. Cherry-picks each commit one by one.
5. If a commit's changes are already included (empty cherry-pick), skips it with a warning. If a cherry-pick fails, prints the commit title, SHA, the authors to resolve it (for a PR merge, the authors of the PR's commits), who merged it, branches containing it, and conflicting files, and stops. It aborts the in-progress cherry-pick and does not push a release branch or open a PR.
6. If all commits apply, runs your configured tests, pushes `release/<release_name>`, and opens a PR into `main`.

## Resolving a cherry-pick conflict

The workflow cannot pause for manual edits, so the author named in the error resolves the conflict locally and resubmits a fixed commit:

1. From a clean checkout, run the same commit list with `--local`:
   ```bash
   python3 scripts/assemble_release.py --release-name sprint-10 --local \
     --dev1 "<shas>" --dev2 "<shas>" --dev3 "<shas>"
   ```
   It starts from `origin/main` on a detached HEAD, applies the commits in the same order as the workflow, and stops on the conflicting commit with the cherry-pick left in progress.
2. Fix the conflict markers, then `git add <files>` and `git cherry-pick --continue`.
3. Publish the fixed commit: `git push origin HEAD:refs/heads/resolved/<old-short-sha>`.
4. Replace the old SHA with the new one (`git rev-parse --short HEAD`) in the commit list and re-run step 1. The fixed commit keeps the original author date, so it stays in the same position.
5. Repeat until the local run reports that all commits apply, then run the workflow with that final list. Run `git switch main` to leave the detached HEAD.

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

Hotfix commits are included in the same timestamp sort as developer commits. This is safer than always applying hotfixes first if they are interleaved with other changes, but timestamps still do not capture dependencies. If a hotfix is already part of `main`, do not submit it; it would be skipped as an empty cherry-pick. A hotfix can be submitted as its PR merge commit or as its individual change commits, but not both.

## Current repository caveat

Your `staging` branch has PR merge commits and developer commits interleaved. A SHA entered by a developer must be the actual ticket change commit, not an unrelated staging merge commit. Commits that exist only on an unpushed local branch cannot be fetched by Actions. Push the source branch first.

## How to mark testing complete

The release PR contains a checklist for all three developers. Use actual PR approvals plus required status checks for enforcement. Do not rely on workflow input checkboxes as proof that the person tested it. The release PR is not merged automatically.
