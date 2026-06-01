---
name: triaging-visual-review-runs
description: >
  Inspects PostHog Visual Review (VR) runs that gate PR merges with screenshot regression checks.
  Use when the user mentions "visual review", "VR", "snapshot diff", "screenshot test", "storybook regression",
  "playwright snapshot", asks why a PR is blocked or what changed visually, wants to triage the VR backlog,
  decide whether a snapshot diff is real vs flaky, or check whether a story has been changing across runs.
  Also invoke when a PR has a failing `visual-review` status check, when a PR comment mentions "Visual review",
  or when the user is on a branch with an open VR run.
---

# Triaging visual review runs

Visual Review is PostHog's screenshot-regression product: CI captures storybook + playwright screenshots,
diffs them against committed baseline hashes, and gates the PR until a human approves the visible changes.
A PR with visual changes carries a `visual-review` GitHub status check that stays red until each diffed
snapshot is approved or tolerated in the [VR UI](https://us.posthog.com/project/2/visual_review).

This skill teaches an agent how to answer the questions a human reviewer would actually ask, by chaining
the VR MCP tools — instead of reaching for `gh pr view` and tab-hopping to the VR web UI. The read tools
cover status / scope / history / triage; two write tools (`approve-create`, `tolerate-create`) let the
agent act once the user confirms.

## When this skill applies

Trigger this skill on any of:

- A PR number, branch name, or commit SHA paired with words like _visual review_, _VR_, _snapshot_, _screenshot_,
  _storybook diff_, _playwright snapshot_, _baseline_, _approve_, _tolerated_, _quarantine_.
- Questions about why a PR is blocked, what visually changed, or whether a diff is real.
- "Is my run done?" / "What's left to review?" / "Has this story flaked recently?"
- A failing `visual-review` GitHub check or a PR comment from the `posthog-bot` mentioning visual review.

When the user asks for the rendered diff image itself, the [VR web UI](https://us.posthog.com/project/2/visual_review)
is faster — direct them there. This skill is for everything around the diff: status, scope, history, triage.

## Tools

Read tools (safe to call freely):

| Tool                                               | Purpose                                                                                                            |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `posthog:visual-review-runs-list`                  | List runs, filter by `pr_number` / `commit_sha` / `branch` / `review_state`. Start here.                           |
| `posthog:visual-review-runs-retrieve`              | Full detail for a single run (status, summary counts, supersession).                                               |
| `posthog:visual-review-runs-snapshots-list`        | Per-snapshot results inside a run: identifier, `result`, diff %, classification, baseline + current artifact URLs. |
| `posthog:visual-review-runs-snapshot-history-list` | A single story's last N runs across master/PRs — the flake check.                                                  |
| `posthog:visual-review-runs-counts-retrieve`       | Aggregate counts for queue triage (how many runs in `needs_review`, etc.).                                         |
| `posthog:visual-review-runs-tolerated-hashes-list` | Hashes the team has explicitly accepted as "known flake / acceptable variation".                                   |
| `posthog:visual-review-repos-list`                 | Repos (one per GitHub repo) — usually only one matters; useful for filtering.                                      |
| `posthog:visual-review-repos-retrieve`             | Repo metadata: baseline file paths, PR-comment configuration.                                                      |

Write tools (NEVER call without explicit per-run human confirmation — see the gate below; these ship the visual change):

| Tool                                         | Purpose                                                                                                                |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `posthog:visual-review-runs-approve-create`  | Approve `changed` / `new` snapshots in a run. Commits the updated baseline YAML to the PR (greens the gate).           |
| `posthog:visual-review-runs-tolerate-create` | Mark a single changed snapshot as a known tolerated alternate. Does NOT change the baseline — use for benign variants. |

> [!CAUTION]
> **Approval requires explicit human interaction every time.** This is a hard rule, not a preference.
> Approving rewrites the committed baseline and ships the visual change. NEVER approve on your own
> initiative, on a standing instruction ("approve anything that looks fine"), or by inferring intent from
> the task. You may _verify_ and _recommend_ freely; the decision to approve is the human's alone, made
> fresh for each run. See [The approval gate](#the-approval-gate) before calling `approve-create`.

Approval call shape:

- `id` (required) — the run UUID. It's the route parameter, so the call fails without it.
- `approve_all: true` — approves every `changed` and `new` snapshot in the run. Convenient when you've verified every diff is intended.
- `snapshots: [{identifier, new_hash}]` — explicit list. `new_hash` is the `content_hash` of each snapshot's `current_artifact`. Prefer this when only some diffs are intended.
- `commit_to_github: true` (default) — commits the baseline-YAML update straight to the PR branch. This is what greens the GitHub `visual-review` check, and it works for **`new` snapshots, not just `changed` ones**. The pushed commit SHA comes back on the run's `metadata.baseline_commit_sha`; if that field is absent after a `commit_to_github: true` call, no commit landed (e.g. the run has no PR, or the PR has newer commits — a `409 sha_mismatch`) and the gate is still red. Set `false` only to record the approval in the DB without committing.
- The run is finalized (gate goes green) only once **every** `changed`/`new` snapshot is approved. A partial `snapshots` list commits those baselines but leaves the gate red — so approve the full set when you intend to unblock the merge.

Toleration call shape — both fields are required:

- `id` (required) — the run UUID. It's the route parameter, so the call fails without it.
- `snapshot_id` (required) — the UUID of the individual snapshot to tolerate (from `visual-review-runs-snapshots-list`). This identifies _which_ snapshot inside the run; it does not replace the run `id`.

If approval fails with `409 stale_run`, the run has been superseded — `visual-review-runs-list { pr_number }` and approve the newest one. A successful approval often kicks off a fresh CI run, which is normal.

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

1. `posthog:visual-review-runs-list { pr_number: <n>, limit: 5 }` — sort by `created_at` desc, take the latest non-stale one.
2. If the run has `summary.changed > 0` or `summary.unresolved > 0`, drill in:
   `posthog:visual-review-runs-snapshots-list { id: <run_id> }` and report the `changed` snapshots.

Report back: PR number, run UUID, `review_state`, summary counts, and the `_posthogUrl` deep link so the
user can click straight to the diff viewer.

### "Is the diff real or unrelated?"

The most useful judgment a code-aware agent can add. Combine three signals: **scope match**, **flake history**,
and **the actual rendered images**. The agent should look at the screenshots — not just describe metadata.

1. **Scope check** — `git diff master...HEAD --stat` (or against the PR's base branch) → list of touched paths.
   Cross-reference with `posthog:visual-review-runs-snapshots-list { id }` filtered to `result: changed` → story identifiers.
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
     screenshot — a flake signal, not a regression.

3. **Flake history** — run the flake check below for any story that looks suspect.

4. **Verdict** — combine all three:
   - Scope plausible + visible regression matches the code change → real diff, recommend approval.
   - Scope mismatch + dimensions mismatch + frequent prior changes → flake, recommend tolerating the hash.
   - Scope plausible + visible regression looks unintended → push a fix; do not approve.

Always include a one-line description of what you saw in the images — the user uses this to decide whether to
trust your verdict without opening the VR UI themselves.

### The approval gate

Approval is the one irreversible, outward-facing action in this skill: it rewrites the baseline committed to
the PR and greens the merge gate. Treat it like pushing to someone's branch — never automatic.

Before _any_ `approve-create` call, all of these must hold:

1. **You verified the diffs.** You pulled the current (and, for `changed`, baseline) PNGs and looked at them,
   ran the flake check on anything suspect, and reached a per-snapshot verdict. Metadata alone is never enough.
2. **You presented the verdict and waited.** Show the user, per snapshot, what changed and your recommendation,
   then stop. Do not pre-stage the tool call.
3. **The user explicitly approved _this_ run.** They named the snapshots or said "approve all of those" in
   response to your verdict. A general "get the gate green", "fix the PR", or "approve anything that looks
   right" is NOT confirmation to approve — it is permission to _investigate and recommend_. When the task
   implies approval but the human hasn't said it for this specific run, ask; do not infer.

Only then call `approve-create`. After it returns, confirm what actually happened: report
`metadata.baseline_commit_sha` (the pushed commit) or, if absent, that no commit landed and why — never claim
the gate is green without that SHA. A successful approval usually kicks off a fresh CI run; that's expected.

If you find yourself about to approve and can't point to a specific human "yes" for this run, stop and ask.

### Flake check: "Has this story been changing?"

Once you have a suspect snapshot identifier:

`posthog:visual-review-runs-snapshot-history-list { id: <snapshot_id> }` → returns prior outcomes for the same story.

Verdicts:

- Mostly `unchanged` and this run's diff is the outlier → likely a real regression caused by this PR.
- Frequent `changed` across unrelated branches/master → flaky story; recommend tolerating the hash via the UI.
- Recent `removed` or large-jump dimension change → baseline likely stale; recommend re-baselining on master.

### Triaging the queue

When the user is doing housekeeping rather than asking about a specific PR:

1. `posthog:visual-review-runs-counts-retrieve` → total queue size.
2. `posthog:visual-review-runs-list { review_state: needs_review, limit: 50 }` (paginate if needed).
3. Group by `branch` author or `run_type` to surface clusters (e.g., "12 PRs blocked on the same shared
   component change" usually means a single underlying root cause to address).
4. Prefer surfacing runs whose `summary.changed > 0` over runs that are only `new` — `new` means no baseline
   yet, which is usually trivial to approve; `changed` is the real review work.

## Output expectations

For PR-status questions, lead with the verdict in one line, then 2-4 bullets of supporting context. Always
include the `_posthogUrl` deep link to the run — humans need to see the rendered images to make the call,
the agent can only describe the metadata.

For triage / aggregate questions, a short table beats prose. Group by what the user is going to act on.

## What NOT to do

- Do not approve or tolerate without explicit, per-run human confirmation — see [The approval gate](#the-approval-gate).
  The verdict is yours to recommend; the decision to ship belongs to the user. A broad instruction like "get the
  gate green" or "approve anything that looks fine" authorizes investigation and a recommendation, NOT the approval
  itself — wait for a "yes" naming this run. Once they say "approve those" / "tolerate that", call the tool.
- Do not assume the failing GitHub check on a PR is unrelated to VR — if a `visual-review` check is red on
  a PR you're working on, that's the trigger to run this skill.
- Do not declare a verdict from metadata alone when `result: changed`. Pull the baseline and current PNGs
  and look at them; metadata can only say "something changed", not whether the change is intended.
