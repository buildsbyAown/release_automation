# Collaborative One-Click Release Builder

This workflow lets three developers paste the commit SHAs they want included. It combines the lists, sorts commits by author timestamp oldest-first, cherry-picks each onto a fresh branch from `main`, pauses on a conflict (saving progress and naming the author who must resolve it), runs your tests, pushes the release branch, and opens a PR into `main`. It never merges or deploys.

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
4. Cherry-picks each commit one by one with `-x`.
5. If a commit's changes are already included (empty cherry-pick), skips it with a warning. If a cherry-pick fails, prints the commit title, SHA, the authors to resolve it (for a PR merge, the authors of the PR's commits), who merged it, branches containing it, and conflicting files, and stops. The commits applied so far are pushed to `release/<release_name>` so the run can be resumed (see below); no PR is opened.
6. If `release/<release_name>` already exists, continues it instead of starting over, skipping commits that are already on it.
7. If all commits apply, runs your configured tests, pushes `release/<release_name>`, and opens a PR into `main`.

## Resolving a cherry-pick conflict

Releases are resumable, so a conflict on commit 50 never throws away commits 1–49.

Every commit is cherry-picked with `git cherry-pick -x`, which adds `(cherry picked from commit <sha>)` to the new commit. That line is how the builder knows which submitted commits are already on `release/<release_name>`.

When a cherry-pick conflicts, the workflow:
1. Pushes the commits applied so far to `release/<release_name>`. It does not run tests or open a PR.
2. Names the commit, its title, and the author(s) who must resolve it. The step log and run summary show the exact commands to run.

**Resolve only the conflicting commit** (the commands are printed with the real SHA):

```bash
git fetch origin
git switch release/sprint-10 && git pull --ff-only
git cherry-pick -x <sha>          # add -m 1 for a PR merge commit
# fix the conflict markers
git add <files> && git cherry-pick --continue
git push origin release/sprint-10
```

Then re-run the workflow with **the same inputs and release name**. It skips everything already on the branch and continues from the next commit. If another conflict appears, its author repeats the same steps.

**Or resolve every remaining conflict locally in one go:**

```bash
python3 scripts/assemble_release.py --local --release-name sprint-10 \
  --dev1 "<shas>" --dev2 "<shas>" --dev3 "<shas>"
```

This continues `release/sprint-10` on your machine and stops at each conflict with the cherry-pick left in progress. Fix it, run `git add <files> && git cherry-pick --continue`, and run the same command again. When it reports that all commits are on the branch, `git push origin release/sprint-10` and re-run the workflow to test and open the PR. `--local` never pushes.

Rules:
- Always use `-x` when resolving by hand. A commit without the `(cherry picked from commit ...)` line is kept, but the builder will try to apply the original again.
- Keep the same commit list when resuming. If `release/<release_name>` contains commits that are no longer in the list, the run stops; delete the branch to start over with a new list.

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
