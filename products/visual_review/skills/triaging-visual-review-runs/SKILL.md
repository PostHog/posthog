---
name: triaging-visual-review-runs
description: >
  Inspects and resolves PostHog Visual Review (VR) runs that gate PR merges with screenshot regression checks.
  Use when the user mentions "visual review", "VR", "snapshot diff", "screenshot test", "storybook regression",
  "playwright snapshot", "quarantine", or "tolerate", asks why a PR is blocked or what changed visually,
  wants to triage the VR backlog, decide whether a snapshot diff is real or flaky, quarantine or lift a flaky story,
  or check whether a story has been changing across runs.
  Also invoke when a PR has a failing `visual-review` status, `Visual regression tests pass`, or `Playwright tests pass` check,
  or when a PR comment mentions "Visual review".
---

# Triaging visual review runs

Visual Review is PostHog's screenshot-regression product.
CI captures Storybook and Playwright screenshots, diffs them against committed baseline hashes, and fails the PR until every changed snapshot is resolved.
You may resolve flakes on your own.
You may not ship a visual change on your own.
Tool names below are PostHog MCP tools; prefix them with `posthog:` where your client needs it.

## Decide first

Gather the evidence in [Gather the evidence](#gather-the-evidence), then take the first row that matches each changed snapshot.

| Evidence                                                                                                        | Action                                                                                                | Human yes needed                   |
| --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------- |
| PR comes from a fork (`isCrossRepository: true`)                                                                | Report only. See [Fork PRs](#fork-prs)                                                                | No VR writes possible              |
| The diff comes from your change and is intended                                                                 | `approve-create`, then ask for finalize                                                               | Yes, for each run, before finalize |
| The diff comes from your change and is not intended                                                             | Fix the code and push. No VR write                                                                    | No                                 |
| Story outside your change, flakiness entry `unstable`, `window_runs` ≥ 5, `hard_count` ≥ 2                      | `quarantine-create`, then `recompute-create`. Report it                                               | No                                 |
| Story outside your change, flakiness entry `broken`                                                             | Do not quarantine. Its baseline on the default branch is wrong. Report it and recommend a re-baseline | Yes                                |
| Story outside your change, quiet history, one rendering with the same size and content and a named noise source | `tolerate-create`, then `recompute-create`                                                            | No                                 |
| Anything else (a real-looking change you did not make, too little history, unsure)                              | Stop and report what you saw                                                                          | Yes                                |

Never do these:

- Tolerate to get past a gate. A toleration accepts one exact hash forever and cannot be undone through the API. A story that renders differently from run to run gets a quarantine, which also protects every other developer.
- Quarantine a diff your own change caused, or a `broken` entry.
- Call `recompute-create` on a run with approved snapshots. Recompute counts an approval as resolved but commits no baseline, so the PR merges with a stale baseline and the merge queue fails on the drift.
- Finalize without an explicit human yes for that run. "Get the gate green" or "fix the PR" is not that yes.

## What each write does

| Tool                                           | Effect                                                                                                                     | Gate                                                      |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `visual-review-runs-approve-create`            | Records approval in the database only                                                                                      | No change                                                 |
| `visual-review-runs-tolerate-create`           | Accepts the current hash as an alternative baseline, in every future run                                                   | Needs recompute                                           |
| `visual-review-repos-quarantine-create`        | Removes one identifier of one run type from pass or fail on every PR, until it expires (30 days if you omit `expires_at`)  | Needs recompute                                           |
| `visual-review-repos-quarantine-expire-create` | Lifts the quarantine; the story gates again                                                                                | Next run                                                  |
| `visual-review-runs-recompute-create`          | Recounts, posts the `visual-review` status, and re-runs the CI job that completed the run (about a minute, no new capture) | Turns the required check green when nothing is unresolved |
| `visual-review-runs-finalize-create`           | Commits approved snapshots to the PR's baseline file. With nothing to commit, it re-runs the completing job                | Ships the change                                          |

Branch protection requires the `Visual regression tests pass` and `Playwright tests pass` job checks, not the `visual-review` status.
So a quarantine or toleration only unblocks the PR after `recompute-create` re-runs the completing job.
Recompute refuses a run that is not completed or already finalized.

## Gather the evidence

1. **Fork check.** `gh pr view <n> --json isCrossRepository`. If `true`, go to [Fork PRs](#fork-prs).
2. **Find the run.** `visual-review-runs-list { pr_number: <n>, limit: 5 }`. Take the newest run that is not `stale`. Its `repo_id` feeds the repo tools.
3. **List what changed.** `visual-review-runs-snapshots-list { id: <run_id>, limit: 50 }`. Work on `changed` and `new` rows with an empty `classification_reason` and `review_state: pending`.
4. **Scope.** `git diff <base>...HEAD --stat`. Story identifiers look like `<area>-<scene>--<story>--<theme>`, for example `scenes-app-settings-user--settings-user-profile--dark` maps to `frontend/src/scenes/settings/user/`. Decide whether your change can reach the story, including shared components and styles.
5. **Look at the images.** Download `baseline_artifact.download_url` and `current_artifact.download_url` with `curl -s -o`, then read both files. Name the visible difference in one line. Different `width` or `height` usually means a rendering race, not a UI change.
6. **Flake history.** `visual-review-repos-flakiness-retrieve { id: <repo_id> }` and find the entry with the same `identifier` and `run_type`. No entry means the story is quiet on the default branch.
   - `flakiness_state`: `broken` (fails nearly every run), `unstable` (fails some runs), `at_risk`, `noisy`, `clean`.
   - `hard_rate` and `hard_count`: recent default-branch runs that failed the gate. `window_runs`: how many runs back the rate.
   - `unstable` needs only one failure, so check `hard_count` and `window_runs` before you trust it.
7. **Earlier variants.** `visual-review-runs-tolerated-hashes-list { id: <run_id>, identifier }`. Several tolerated hashes mean the story is not stable, so quarantine rather than tolerate.

`visual-review-runs-snapshot-history-list` shows when the baseline moved on the default branch. It does not count flakes.

## Quarantine well

- `reason`: the flake and the evidence, for example "unstable on master: 3 of 40 runs failed in 7 days, chart animation timing; unrelated to PR 1234".
- `source_run_id`: the run that failed.
- `expires_at`: omit it for 30 days, or set an earlier date. Do not set a later one.
- After the quarantine, call `visual-review-runs-recompute-create` on the PR's newest run and check `ci_rerun_triggered`.
- Tell the user which identifiers you quarantined and why. A quarantine helps every PR, so the story owner must still fix the story.

## Lift quarantines

Use this after you fix a flaky story, or when asked to clean up.

1. `visual-review-repos-flakiness-retrieve` lists quarantined entries. `needs_decision: true` marks one that stopped failing or expires soon.
2. Lift with `visual-review-repos-quarantine-expire-create { id, run_type, identifier }` only when the story has had no hard failure in the window, or your merged fix removed the cause.
3. For stories that keep needing tolerations, `visual-review-repos-toleration-pileups-retrieve` finds them. The fix belongs in the story: a pinned date, a disabled animation, a wait for a loader.

## Fork PRs

A fork PR has no VR run, because CI gives no secret to a fork.
Each Storybook shard instead compares exact hashes with `frontend/snapshots.yml` offline, and a mismatch fails `Visual regression tests pass`.
That fallback knows no tolerations and no quarantines, so a flaky story can fail a fork PR that changes nothing visible.

1. Read the failing job: `gh run view <run_id> --log-failed`. The `Baseline mismatch` error names each snapshot.
2. Run the scope check against those identifiers.
3. Judge flakiness with `visual-review-repos-flakiness-retrieve`, which needs no run.
4. Report and stop. A snapshot that must change needs a maintainer to update `frontend/snapshots.yml` on the PR branch.

Never push a fork's head to an in-repo branch to get it a VR run.
See [Pull requests from forks](../../../../docs/published/handbook/engineering/fork-pull-requests.md).

## Vocabulary

- Run `review_state`: `needs_review`, `clean`, `processing`, `stale` (superseded by a newer run on the same PR).
- Run `run_type`: `storybook` or `playwright`.
- Snapshot `result`: `unchanged`, `changed`, `new` (no baseline yet), `removed`.
- Snapshot `classification_reason`: `tolerated_hash`, `below_threshold`, `exact`, or empty for a real diff.
- Run `summary.unresolved`: what still blocks the PR.

## Triage the queue

1. `visual-review-runs-counts-retrieve` for the size.
2. `visual-review-repos-runs-list { repo_id, review_state: needs_review }`.
3. Group by `run_type` and changed identifiers. Many PRs blocked on the same identifier means one flake or one master drift, which one quarantine or one re-baseline fixes.

## Report

Lead with the verdict in one line, then one line for each snapshot: what you saw in the images, the evidence, and the action you took or recommend.
Include the run's `_posthogUrl`.
