# Collaborative One-Click Release Builder

This workflow takes the tickets going into a release and the commit SHAs of each ticket. It combines them, sorts commits by author timestamp oldest-first, cherry-picks each onto a fresh branch from `main`, resolves conflicts with an AI that is told which tickets are involved (falling back to pausing and naming the author), runs the release check, pushes the release branch, and opens a PR into `main` that lists every AI resolution for review. It never merges or deploys.

## Important behavior and limitation

**Oldest timestamp first is a heuristic, not a guarantee of dependency order.** Git author/committer timestamps do not reliably prove which change depends on another. A commit authored later may be a prerequisite for another commit with skewed clocks or rebased history. This template follows your requested timestamp rule but stops at the first cherry-pick failure.

A commit can also apply cleanly and still depend on omitted code. Tests and review remain necessary.

## Install

Files:
- `.github/workflows/collaborative-release-builder.yml`
- `scripts/assemble_release.py`: assembles, resumes, and reports.
- `scripts/ai_resolver.py`: resolves conflicted files through Groq.
- `scripts/release_check.sh`: the release check (compile + import every module). Add real tests here; it runs in the workflow and after every AI resolution.

For AI conflict resolution, add a repository secret **`GROQ_API_KEY`** (Settings → Secrets and variables → Actions → New repository secret). Optionally add a repository variable **`GROQ_MODEL`** to change the model (default `openai/gpt-oss-120b`). Without the secret, conflicts pause for a person as before.

## Run it

Open **Actions → Collaborative Release Builder → Run workflow**.

Provide:
- Release name: `sprint-10`
- Ticket slots 1–10, one ticket per slot: `20: 6569375 b44a336` (ticket, colon, the ticket's commit SHAs). Leave unused slots empty. GitHub's form cannot add fields dynamically, so ten slots are provided.
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

## AI conflict resolution

When a cherry-pick conflicts and `GROQ_API_KEY` is set, for each conflicted file the AI receives the common base, the release-branch version, the incoming version, the incoming commit's diff, the incoming ticket's commits, and which tickets already on the release branch touched the file. It is instructed to keep the behaviour of both sides.

A resolution is accepted only if it has no conflict markers, is valid Python (for `.py` files), and `scripts/release_check.sh` passes. Otherwise it retries once, then falls back to the manual flow below.

Accepted resolutions are committed with `AI-resolved-conflict`, `AI-resolved-tickets`, `AI-resolver-model` and `AI-resolution-note` lines in the commit message. The release PR lists each one with its explanation and diff, and adds a checkbox for the owners of the tickets involved to review it.

The AI can only be checked as well as `release_check.sh` checks the code. A resolution can run and still drop part of a feature; review every AI resolution, and add tests per ticket to catch this automatically.

## Resolving a cherry-pick conflict by hand

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
  --ticket "20: <shas>" --ticket "30: <shas>"
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
