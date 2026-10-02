---
name: triaging-visual-review-runs
description: >
  Inspects PostHog Visual Review (VR) runs that gate PR merges with screenshot regression checks.
  Use when the user mentions "visual review", "VR", "snapshot diff", "screenshot test", "storybook regression",
  "playwright snapshot", "quarantine", asks why a PR is blocked or what changed visually, wants to triage the VR backlog,
  decide whether a snapshot diff is real vs flaky, quarantine or lift a flaky story, or check whether a story has been changing across runs.
  Also invoke when a PR has a failing `visual-review` status check, when a PR comment mentions "Visual review",
  when a PR from a fork fails `Visual regression tests pass`, or when the user is on a branch with an open VR run.
---

# Triaging visual review runs

Visual Review is PostHog's screenshot-regression product: CI captures storybook + playwright screenshots,
diffs them against committed baseline hashes, and gates the PR until every changed snapshot is resolved.
A PR with visual changes carries a `visual-review` GitHub status check and a required "Visual regression tests pass" job check.
Both stay red until each diffed snapshot is approved and finalized, tolerated, or quarantined, and the job re-runs:
finalize does that for approvals, `recompute-create` for tolerations and quarantines. The [VR UI](https://us.posthog.com/project/2/visual_review) offers the same actions.
A PR from a fork is the exception: it gets no Visual Review run at all.
See [Fork PRs have no Visual Review run](#fork-prs-have-no-visual-review-run).

This skill teaches an agent how to answer the questions a human reviewer would actually ask, by chaining
the VR MCP tools — instead of reaching for `gh pr view` and tab-hopping to the VR web UI. The read tools
cover status / scope / history / triage. An agent may resolve flakes on its own, with a quarantine or, rarely, a toleration.
It may not ship a visual change on its own: `finalize-create` commits the baseline and needs explicit per-run human confirmation.

## Decide first

Gather the evidence with [Is the diff real or unrelated?](#is-the-diff-real-or-unrelated) and the [flake check](#flake-check-has-this-story-been-changing),
then take the first row that matches each changed snapshot.

| Evidence                                                                                                           | Action                                                                                                                                                                                                      | Human yes needed                   |
| ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| PR comes from a fork (`isCrossRepository: true`)                                                                   | Report only. See [Fork PRs](#fork-prs-have-no-visual-review-run)                                                                                                                                            | No VR writes possible              |
| The diff comes from your change and is intended                                                                    | `approve-create`, then ask for finalize                                                                                                                                                                     | Yes, for each run, before finalize |
| The diff comes from your change and is not intended                                                                | Fix the code and push. No VR write                                                                                                                                                                          | No                                 |
| Your change renders a quarantined story `changed` or `new`, and the change is intended                             | `approve-create` for that identifier, then ask for finalize. If the change also fixes the flake, add `lift-on-merge-create` after the approval. See [Quarantined stories](#quarantined-stories-in-your-run) | Yes, for each run, before finalize |
| Your change fixes a quarantined story's flake, and the story renders `unchanged`                                   | `lift-on-merge-create` for that identifier. See [Quarantined stories](#quarantined-stories-in-your-run)                                                                                                     | No                                 |
| Story outside your change, flakiness entry `unstable`, `hard_count` ≥ 5, `last_flaked_at` in the last 7 days       | `quarantine-create`, then `recompute-create`. Report it                                                                                                                                                     | No                                 |
| Story outside your change, flakiness entry `broken`                                                                | Do not quarantine. Its baseline on the default branch is wrong. Report it and recommend a re-baseline                                                                                                       | Yes                                |
| Story outside your change, quiet history, same width and height, `change_kind: pixel`, a noise source you can name | `tolerate-create`, then `recompute-create`                                                                                                                                                                  | No                                 |
| Anything else: `unstable` with fewer failures, a real-looking change you did not make, unsure                      | Stop and report what you saw                                                                                                                                                                                | Yes                                |

Each theme is its own identifier.
Judge the `--light` and `--dark` snapshots of a story separately, and quarantine only the ones that match.

Expect tolerations to be rare.
The diff already absorbs most real render noise below the threshold, and a small diff percentage is often a real structural change.
A toleration accepts one exact hash forever and cannot be undone through the API, so it is never a way past a gate.
A story that renders differently from run to run and meets the quarantine row above gets a quarantine, which also protects every other developer. With less evidence, report it instead.

### Quarantined stories in your run

A quarantine hides a story's diff from the gate and from the PR comment, so a green check does not show that your change left a quarantined story alone.
The story still renders and is diffed on every run that selects it. A PR run renders only the stories its diff affects.
Check every run of a change that touches UI.
List the changed quarantined snapshots with
`posthog:visual-review-runs-snapshots-list { id: <run_id>, include_quarantined: true, exclude_unchanged: true }`.
With `exclude_unchanged`, `quarantined_count` counts only the changed ones.
The list is paginated and does not put quarantined rows first, so follow `next` until every row is read.

- A quarantined story that your change renders differently needs its new picture approved by identifier, then finalized.
  "Approve all" and `approve_all` skip quarantined snapshots.
  Without the approval, the default branch keeps the old entry, and every run fails on the day the quarantine is lifted or expires.
- A quarantined story that your change does not touch can still show `changed`, because it is flaky. Leave it.
- A fix for the flake changes nothing VR can see in one run, so the story renders `unchanged` and the list above leaves it out.
  Record the fix with `posthog:visual-review-runs-lift-on-merge-create { id: <run_id>, identifier: <identifier> }` for each identifier the fix should release, and name the identifiers in the PR description.
  The quarantine lifts only after the PR merges and a default-branch run that contains the merge renders the same picture against a matching entry.
  Until then it stays, unless its expiry date passes first, and `posthog:visual-review-runs-quarantine-lifts-list { id: <run_id> }` shows each request's `state` and `detail`.
- A change that deletes a quarantined story leaves its baseline entry behind.
  Only a full run classifies the story `removed`, and only finalize prunes the entry.
  The `run-ci-frontend` label takes effect on the next push or ready-for-review, not when it is added, so push after labeling and check that the new run is full.
  Finalize that run before the merge, or every full run reports the story `removed` once the quarantine ends.
- Requesting a lift never approves a picture. For a `changed` or `new` quarantined snapshot, approve it by identifier first, or the request returns 400. Finalize the run too, so the baseline entry the lift checks lands with the merge.
- One clean render does not prove a rare flake is gone, and neither does `variant_count: 0`, which counts only absorbed variants.

## When this skill applies

Trigger this skill on any of:

- A PR number, branch name, or commit SHA paired with words like _visual review_, _VR_, _snapshot_, _screenshot_,
  _storybook diff_, _playwright snapshot_, _baseline_, _approve_, _tolerated_, _quarantine_.
- Questions about why a PR is blocked, what visually changed, or whether a diff is real.
- "Is my run done?" / "What's left to review?" / "Has this story flaked recently?"
- A failing `visual-review` GitHub check or a PR comment from the `posthog-bot` mentioning visual review.
- A failing `Visual regression tests pass` check on a PR from a fork, which is the offline fallback and not a VR run.

When the user asks for the rendered diff image itself, the [VR web UI](https://us.posthog.com/project/2/visual_review)
is faster — direct them there. This skill is for everything around the diff: status, scope, history, triage.

**First, check whether the PR comes from a fork.**
A fork PR has no Visual Review run, so every run-scoped VR tool below returns nothing for it.
Only the repo-scoped flakiness tool still answers.
Read the flag before you query the tools:

```bash
gh pr view <n> --json isCrossRepository
```

If `isCrossRepository` is `true`, stop here.
Go to [Fork PRs have no Visual Review run](#fork-prs-have-no-visual-review-run).

## Fork PRs have no Visual Review run

Visual Review needs a secret, and CI does not give a secret to a fork.
The Visual Review upload is therefore skipped.
No run, no snapshot row and no `visual-review` check exists for the PR.
That is the designed behavior, not a fault.

Each Storybook shard instead compares its own screenshots with the committed baseline file `frontend/snapshots.yml`, offline, in the `Verify snapshots against the baseline offline` step.
A mismatch fails the `Visual regression tests pass` check.

The offline fallback is weaker than Visual Review in ways that change the triage:

| Visual Review                             | Offline fallback on a fork                                     |
| ----------------------------------------- | -------------------------------------------------------------- |
| Diffs with a noise threshold              | Exact pixel hash match only                                    |
| Knows tolerated alternate hashes          | Knows none — a tolerated variant still fails                   |
| Applies quarantine                        | Applies none — a quarantined story still fails                 |
| Rendered diff images in the VR UI         | No images; the job log names the snapshots that differ         |
| Triage and finalize through the MCP tools | No tools apply; a maintainer updates the baseline file instead |

So a flaky story can fail a fork PR that changes nothing visible.

How to triage a fork PR failure:

1. Read the failing `Visual regression tests pass` job.
   The step summary and the `Baseline mismatch` error name each snapshot that differs.
   `gh run view <run_id> --log-failed` gets the log.
2. Run the scope check from [Is the diff real or unrelated?](#is-the-diff-real-or-unrelated) against the named identifiers.
   It needs only `git diff`, so it works without a run.
3. Judge flakiness from the default branch, not from the fork PR.
   Use `posthog:visual-review-repos-flakiness-retrieve { id: <repo_id> }`, with the repo id from `posthog:visual-review-repos-list`.
   This is the one VR tool that still helps, because it reports repo-level history and does not need a run.
4. Report the verdict and stop.
   You cannot approve, tolerate or finalize anything, because there is no run to act on.
   A snapshot that must change needs a maintainer to update `frontend/snapshots.yml` on the PR branch, with a Visual Review run on an in-repo branch.

Never push a fork's head to an in-repo branch to get it a Visual Review run.
See [Pull requests from forks](../../../../docs/published/handbook/engineering/fork-pull-requests.md).

## Tools

Read tools (safe to call freely):

| Tool                                                      | Purpose                                                                                                                                                                                                                                                                                                                           |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog:visual-review-runs-list`                         | List runs, filter by `pr_number` / `commit_sha` / `branch` / `review_state`. Start here.                                                                                                                                                                                                                                          |
| `posthog:visual-review-runs-retrieve`                     | Full detail for a single run (status, summary counts, supersession). Carries the `repo_id` the repo tools need.                                                                                                                                                                                                                   |
| `posthog:visual-review-runs-snapshots-list`               | Per-snapshot results inside a run: identifier, `result`, diff %, classification, baseline + current artifact URLs. Quarantined snapshots are excluded by default (see `quarantined_count`); pass `include_quarantined=true` to see them. Pass `exclude_unchanged=true` to skip the thousands of unchanged rows a large run holds. |
| `posthog:visual-review-repos-flakiness-retrieve`          | Repo snapshots whose rendering is untrusted, with a `flakiness_state` and flake rates for each. The flake check starts here.                                                                                                                                                                                                      |
| `posthog:visual-review-runs-snapshot-history-list`        | One story's baseline timeline on the default branch: one row per baseline change. Takes `{ id: <run_id>, identifier: <identifier> }`.                                                                                                                                                                                             |
| `posthog:visual-review-runs-counts-retrieve`              | Aggregate counts for queue triage (how many runs in `needs_review`, etc.).                                                                                                                                                                                                                                                        |
| `posthog:visual-review-runs-tolerated-hashes-list`        | Hashes the team has explicitly accepted as "known flake / acceptable variation". Takes the same two parameters as the history tool.                                                                                                                                                                                               |
| `posthog:visual-review-repos-list`                        | Repos (one per GitHub repo) — usually only one matters; useful for filtering.                                                                                                                                                                                                                                                     |
| `posthog:visual-review-repos-retrieve`                    | Repo metadata: baseline file paths, PR-comment configuration.                                                                                                                                                                                                                                                                     |
| `posthog:visual-review-repos-quarantine-list`             | Active quarantines with reason, author, expiry and source run. Pass `identifier` for its full history.                                                                                                                                                                                                                            |
| `posthog:visual-review-repos-toleration-pileups-retrieve` | Stories that keep getting tolerated: candidates for a fix in the story.                                                                                                                                                                                                                                                           |
| `posthog:visual-review-runs-quarantine-lifts-list`        | Requests to lift a quarantine when the run's PR merges, with `state` and the latest check's `detail`. Takes `{ id: <run_id> }`.                                                                                                                                                                                                   |

Triage tools (they do NOT change the baseline; the gate changes only after `recompute-create`, except a lift on merge, which a default-branch run applies on its own and needs no recompute):

| Tool                                                        | Purpose                                                                                                                                                                                      |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog:visual-review-runs-approve-create`                 | Mark `changed` / `new` snapshots reviewed (approved) in the DB. Does NOT commit or green the gate — ship via finalize.                                                                       |
| `posthog:visual-review-runs-tolerate-create`                | Accept one changed snapshot's current hash as an alternate in every future run. Render noise only, see [Decide first](#decide-first). Cannot be undone through the API.                      |
| `posthog:visual-review-repos-quarantine-create`             | Remove one identifier of one run type from pass or fail on every PR until it expires (30 days if `expires_at` is omitted). Undo with `quarantine-expire-create`.                             |
| `posthog:visual-review-repos-quarantine-expire-create`      | Lift a quarantine, so the story gates runs again.                                                                                                                                            |
| `posthog:visual-review-runs-lift-on-merge-create`           | Lift a quarantine once the run's PR merges and a default-branch run renders the snapshot's picture against a matching entry. Never approves a picture. Takes `{ id: <run_id>, identifier }`. |
| `posthog:visual-review-runs-quarantine-lifts-cancel-create` | Withdraw a pending lift on merge. The quarantine stays. Takes `{ id: <run_id>, request_id }`.                                                                                                |
| `posthog:visual-review-runs-recompute-create`               | Recount a completed, unfinalized run, post the `visual-review` status, and re-run the CI job recorded on the run, so the required check reads the new verdict.                               |

Branch protection requires the `Visual regression tests pass` and `Playwright tests pass` job checks, not the `visual-review` status.
So a quarantine or toleration unblocks the PR only after `recompute-create` re-runs the CI job recorded on the run.
Approved changes keep the gate red until finalize commits them, so recompute never ships an approval.

Ship tool (irreversible, outward-facing — requires explicit per-run human confirmation; see [the gate](#the-finalize-gate)):

| Tool                                         | Purpose                                                                                                          |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `posthog:visual-review-runs-finalize-create` | Commit the approved baseline to the PR branch and green the GitHub `visual-review` check. This ships the change. |

Mark-reviewed call shape (`approve-create`):

- `id` (required) — the run UUID. It's the route parameter, so the call fails without it.
- `snapshots: [{identifier, new_hash}]` — `new_hash` is the `content_hash` of each snapshot's `current_artifact`. This only records the review in the DB; nothing is committed and the gate stays red until you finalize.

Quarantine call shape (`quarantine-create`):

- `id` — the repo UUID (the run's `repo_id`), and `run_type` — the failing run's `run_type`. Both are route parameters.
- `identifier`, and a `reason` with the evidence, for example "unstable on master: 7 failed default-branch runs in 7 days, chart animation timing; unrelated to PR 1234".
- `source_run_id` — the run that failed. `expires_at` — omit it for 30 days, or set an earlier date, never a later one.
- `notify_owners: true` — posts the quarantine to the owning team's Slack channel, so the people who must fix the story hear about it.
- Then call `recompute-create { id: <run_id> }` on the PR's newest non-stale run of the same `run_type`, and check `ci_rerun_triggered`.

Toleration call shape — both fields are required:

- `id` (required) — the run UUID. It's the route parameter, so the call fails without it.
- `snapshot_id` (required) — the UUID of the individual snapshot to tolerate (from `visual-review-runs-snapshots-list`). This identifies _which_ snapshot inside the run; it does not replace the run `id`.

Finalize call shape (`finalize-create`) — the all-or-nothing ship action:

- `id` (required) — the run UUID.
- `approve_all: true` — approve every still-pending `changed`/`new` snapshot before finalizing (tolerated ones are left alone). Use when you've verified every remaining diff is intended.
- Omit `approve_all` (default false) to finalize a run you've already reviewed snapshot-by-snapshot. Finalize is all-or-nothing: it fails with `409 not_fully_resolved` (and lists what's left) unless every changed/new snapshot is approved, tolerated, or quarantined.
- It commits exactly the snapshots approved in the DB — tolerated snapshots keep their baseline and are never overwritten. When a baseline commit is pushed, its SHA comes back on the run's `metadata.baseline_commit_sha`. It's absent when nothing needed committing (everything resolved by toleration/quarantine — finalize posts a green status, and the required check turns green when its job re-runs) or when the commit was skipped: no PR, or a `409 sha_mismatch` because the PR has newer commits (that one leaves the gate red — re-run CI on the latest commit and finalize again).

If finalize fails with `409 stale_run`, the run has been superseded — `visual-review-runs-list { pr_number }` and finalize the newest one. A successful finalize often kicks off a fresh CI run, which is normal.

### The finalize gate

Finalize is the one irreversible, outward-facing action in this skill: it rewrites the baseline committed to the
PR and greens the merge gate. Treat it like pushing to someone's branch — never automatic.

Before _any_ `finalize-create` call, all of these must hold:

1. **You verified the diffs.** You pulled the current (and, for `changed`, baseline) PNGs and looked at them, ran
   the flake check on anything suspect, and reached a per-snapshot verdict. Metadata alone is never enough.
2. **You presented the verdict and waited.** Show the user, per snapshot, what changed and your recommendation, then stop.
3. **The user explicitly approved _this_ run.** A broad "get the gate green" / "fix the PR" is permission to
   investigate and recommend — NOT to finalize. When the task implies finalizing but the human hasn't said it for
   this specific run, ask.

`approve-create`, `tolerate-create`, `quarantine-create` and `recompute-create` don't need this gate when [Decide first](#decide-first) allows them.
The moment you're about to `finalize-create` and can't point to a specific human "yes" for this run, stop and ask.

## Vocabulary cheat sheet

These appear in tool output and matter for interpretation:

- **Run `review_state`**: `needs_review` (open, awaiting human), `clean` (zero diffs), `processing` (CI still uploading),
  `stale` (a newer run on the same PR has superseded this one — check `superseded_by_id`).
- **Run `run_type`**: `storybook` (component snapshots) or `playwright` (full-page e2e snapshots).
- **Snapshot `result`**: `unchanged`, `changed` (real diff), `new` (no baseline yet), `removed`.
- **Snapshot `classification_reason`**: `tolerated_hash` (matches a known-tolerated hash, no action needed),
  `below_threshold` (under the noise floor), `exact` (byte-identical), `""` (real diff requiring review).
- **Snapshot `review_state`**: `pending` or `approved`.
- **Run `summary`**: `total / changed / new / removed / unchanged / unresolved / tolerated_matched` —
  `unresolved` is what's actually blocking review.

## Workflows

### "What's the VR status of this PR?"

The single most common job. Map a PR number to its run state in two calls.
First confirm the PR is not from a fork.
A fork PR has no run, and `visual-review-runs-list` returns an empty list for it.

1. `posthog:visual-review-runs-list { pr_number: <n>, limit: 5 }` — sort by `created_at` desc, take the latest non-stale one.
2. If the run has `summary.changed > 0` or `summary.unresolved > 0`, drill in:
   `posthog:visual-review-runs-snapshots-list { id: <run_id>, exclude_unchanged: true }` and report the `changed` snapshots.

Report back: PR number, run UUID, `review_state`, summary counts, and the `_posthogUrl` deep link so the
user can click straight to the diff viewer.

### "Is the diff real or unrelated?"

The most useful judgment a code-aware agent can add. Combine three signals: **scope match**, **flake history**,
and **the actual rendered images**. The agent should look at the screenshots — not just describe metadata.

1. **Scope check** — `git diff master...HEAD --stat` (or against the PR's base branch) → list of touched paths.
   Cross-reference with `posthog:visual-review-runs-snapshots-list { id, exclude_unchanged: true }` filtered to `result: changed` → story identifiers.
   Stories are namespaced like `<area>-<scene>--<story>--<theme>`; e.g. `scenes-app-settings-user--settings-user-profile--dark`
   maps to `frontend/src/scenes/settings/user/...`. Use this to translate story id → likely source path.

2. **Visual inspection** — for each `changed` snapshot, the tool result contains `current_artifact.download_url`
   and `baseline_artifact.download_url`. These are pre-signed S3 URLs to PNG files; pull them and look:

   ```bash
   curl -s -o /tmp/vr-baseline.png "<baseline_artifact.download_url>"
   curl -s -o /tmp/vr-current.png "<current_artifact.download_url>"
   ```

   Then `Read` both files (the Read tool renders images visually) and compare. Things to call out:
   - The actual visible delta (text changed, button moved, layout shift, color drift, missing element).
   - Whether the change is consistent with the diff_pixel_count and diff_percentage in the metadata
     (e.g. 54% diff but the images look near-identical → screenshot framing changed, not the UI).
   - Whether the baseline and current have different dimensions (`width` / `height` fields). Mismatched
     dimensions usually mean the story rendered to a different viewport or didn't fully render before
     screenshot — a flake signal, not a regression, and never render noise to tolerate.
   - `change_kind`: `pixel` for scattered pixel noise, `structural` for a perceptual change. A small diff percentage
     is often a real structural change.

3. **Flake history** — run the flake check below for any story that looks suspect.

4. **Verdict** — combine all three:
   - Scope plausible + visible regression matches the code change → real diff, recommend approval.
   - Scope mismatch + the story flakes on the default branch → quarantine it, per [Decide first](#decide-first).
   - Scope plausible + visible regression looks unintended → push a fix; do not approve.

Always include a one-line description of what you saw in the images — the user uses this to decide whether to
trust your verdict without opening the VR UI themselves.

### Flake check: "Has this story been changing?"

Once you have a suspect snapshot row from `visual-review-runs-snapshots-list`, ask two separate questions.

**Is the story unstable?** Only the flakiness overview answers this. Read the repo id with
`posthog:visual-review-runs-retrieve { id: <run_id> }`. Then call
`posthog:visual-review-repos-flakiness-retrieve { id: <repo_id> }`, and find the entry whose `identifier` and
`run_type` match your snapshot. That entry carries the flake signal:

- `flakiness_state`: `broken`, `unstable`, `at_risk`, `noisy`, or `clean`.
- `hard_rate` and `hard_count`: the share and number of recent default-branch runs that failed the gate.
  `last_flaked_at`: the latest of them.
- `soft_rate`: the share that a toleration absorbed.
- `window_runs`: the repo's default-branch runs behind those rates. It is the same for every entry of a run type and says nothing about the story.

A story with no entry is quiet only when the response has `truncated: false`.
With `truncated: true`, an absent story can be in any state, so absence proves nothing.
Do not tolerate or quarantine on absence alone: check `visual-review-runs-tolerated-hashes-list` and the snapshot history, or report it.

**Did the baseline move?** Call
`posthog:visual-review-runs-snapshot-history-list { id: <run_id>, identifier: <identifier> }`. It returns one row for
each baseline transition on the default branch, not a run-by-run outcome list. It drops a feature branch, and it
collapses consecutive runs that share a baseline. You therefore cannot count outcomes with it.

Both parameters are required. Copy them from the snapshot row: its `run_id` goes in `id`, and its `identifier` goes in
`identifier`. The snapshot's own `id` is not a run id, and a call that sends it fails.
`visual-review-runs-tolerated-hashes-list` takes the same two parameters.

Verdicts:

- `flakiness_state` is `clean`, or the story has no entry in an untruncated list → likely a real regression caused by this PR.
- `flakiness_state` is `unstable` with `hard_count` ≥ 5 and a recent `last_flaked_at` → flaky story; quarantine it.
  One failure is enough for `unstable`, and a single failure is often a real change that merged, so trust the count.
- `flakiness_state` is `broken` → the baseline is wrong, not the story. Do not quarantine; recommend a re-baseline.
- `at_risk` and `noisy` never fail a run, so they need no action on a PR.
- Recent `removed`, a large-jump dimension change, or a baseline that last moved long ago → baseline likely stale;
  recommend re-baselining on master.

### Triaging the queue

When the user is doing housekeeping rather than asking about a specific PR:

1. `posthog:visual-review-runs-counts-retrieve` → total queue size.
2. `posthog:visual-review-runs-list { review_state: needs_review, limit: 50 }` (paginate if needed).
3. Group by `branch` author or `run_type` to surface clusters (e.g., "12 PRs blocked on the same shared
   component change" usually means a single underlying root cause to address).
4. Prefer surfacing runs whose `summary.changed > 0` over runs that are only `new` — `new` means no baseline
   yet, which is usually trivial to approve; `changed` is the real review work.
5. Lift stale quarantines: entries in `visual-review-repos-flakiness-retrieve` with `needs_decision: true` stopped failing
   or expire soon. Lift one with `posthog:visual-review-repos-quarantine-expire-create { id, run_type, identifier }`
   only when it had no hard failure in the window, or a merged fix removed the cause.
   Before a lift, check that the default branch renders the story as its entry now.
   Use the latest completed default-branch run of the quarantine's run type whose commit contains the fix, and list its
   changed snapshots with `include_quarantined: true, exclude_unchanged: true`, following `next`.
   Lift only when the story is not in that list on several such runs. A rare flake renders clean most of the time,
   so one clean run is not enough, and a pending run or one of another run type proves nothing.
   The `broken` state alone does not decide it. The state covers 7 days, so it stays `broken` for days after a fix lands.
   When the story is still in that list, check that recent default-branch runs render the same changed picture before you re-baseline it.
   One changed render of a flaky story is a flake, and re-baselining it only swaps which variant fails. Keep the quarantine then.
   For the same picture on run after run, re-baseline it first (the README's quarantine section has the procedure), then lift.
   Report a quarantine in that condition before its expiry date, because the expiry fails runs the same way.

## Output expectations

For PR-status questions, lead with the verdict in one line, then 2-4 bullets of supporting context. Always
include the `_posthogUrl` deep link to the run — humans need to see the rendered images to make the call,
the agent can only describe the metadata.

For triage / aggregate questions, a short table beats prose. Group by what the user is going to act on.

## What NOT to do

- Do not tolerate to get past a gate, and do not quarantine a diff your own change caused or a `broken` entry.
- Do not read a green gate as proof that your change left quarantined stories alone. See [Quarantined stories](#quarantined-stories-in-your-run).
- Do not assume the failing GitHub check on a PR is unrelated to VR — if a `visual-review` check is red on
  a PR you're working on, that's the trigger to run this skill.
- Do not read an empty run list on a fork PR as a broken or pending run.
  Check `isCrossRepository` first, then triage the offline check instead.
- Do not declare a verdict from metadata alone when `result: changed`. Pull the baseline and current PNGs
  and look at them; metadata can only say "something changed", not whether the change is intended.
