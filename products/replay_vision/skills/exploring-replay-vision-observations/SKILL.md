---
name: exploring-replay-vision-observations
description: "Guides agents through pulling a Replay Vision scanner's observations, reading the findings, and acting on them — summarizing patterns across sessions, drilling into individual recordings, and turning real, corroborated issues into PostHog tasks, insights, or an investigating-replay hand-off.\nTRIGGER when: user wants to pull/read/triage Replay Vision observations, asks \"what has my scanner found\", wants to act on or summarize scanner findings, turn observations into tasks/work, or points at a /replay-vision/<scanner-id> URL.\nDO NOT TRIGGER when: creating or sizing a scanner (use creating-replay-vision-scanners), running a one-off scan you don't then analyse, or authoring a signals scout."
---

# Exploring Replay Vision observations

A scanner is a standing LLM probe over session recordings; each time it runs against a session it records
one **observation**. This skill is about the other half of the loop — reading what the scanners have found
and doing something useful with it. For creating or sizing scanners, use [[creating-replay-vision-scanners]].

## Mental model

- **Scanner → observations.** One observation = one scan of one session. There is at most one observation
  per `(scanner, session)`.
- **The finding lives in `scanner_result`.** Its shape depends on the scanner's `scanner_type`, but it always
  carries a `confidence`:
  - `monitor` → a `verdict` (`yes` / `no` / `inconclusive`) plus an open-ended observation.
  - `classifier` → one or more `tags` from the scanner's label set.
  - `scorer` → a numeric score on the scanner's `scale`.
  - `summarizer` → a free-text summary (optionally with facet embeddings).
- **Only `succeeded` observations carry a finding.** Triage the rest by `status`/`error_reason` (see below).
- **Observations are LLM judgments, not ground truth.** One observation is one model's read of one session —
  corroborate before you act on it.

If a scanner has `emits_signals: true`, its observations also feed the Signals pipeline and may surface as
Inbox **signal reports** (clusters of related findings). When the user's intent is "work the reports", that's
the inbox path — see _Acting on findings_ below.

## Step 1 — Anchor on the scanner

If the user gave a `/project/<id>/replay-vision/<scanner-id>` URL, that path segment is the scanner ID.
Otherwise list them with `vision-scanners-list` and pick the relevant one.

Then call `vision-scanners-get` to read its configuration **before** reading results — the `scanner_type` and
`scanner_config.prompt` tell you how to interpret `scanner_result` (a `verdict` field only makes sense once you
know it's a monitor; a score only means something against the scorer's `scale`).

## Step 2 — Pull the observations

Pick the axis that matches the question:

- **What has this scanner found, over time?** → `vision-scanners-observations-list` (the workhorse). Filter to
  `status=succeeded` to get only sessions with a finding, then narrow by `verdict` (monitors) or `tags`
  (classifiers). Scorers aren't filtered by score — rank them with `order_by=-result_score` instead. Use
  `order_by` (e.g. `-result_score`, `-completed_at`) to surface the strongest hits first.
- **What did every scanner find about one session?** → `vision-observations-list` (the `session_id` query
  parameter is REQUIRED). Use this while investigating a single recording.
- **The full detail of one finding** → `vision-scanners-observations-get` or `vision-observations-retrieve` —
  returns the frozen `scanner_snapshot` (config at run time) and the complete `scanner_result`, including any
  event citations that link the finding back to specific events in the recording.

Triage `status` so you don't mistake a non-result for "nothing wrong":

| status                | meaning                                                       | typical `error_reason`                                                                                   |
| --------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `succeeded`           | has a `scanner_result`                                        | —                                                                                                        |
| `ineligible`          | session couldn't be analysed — a normal outcome, not an error | `too_short`, `no_recording`, `too_inactive`, `too_long`, `no_events`                                     |
| `failed`              | the scan errored                                              | `provider_rejected`, `validation_failed`, `rasterization_failed`, `provider_transient`, `internal_error` |
| `pending` / `running` | still in flight                                               | —                                                                                                        |

A scanner that looks like it "found nothing" is often producing mostly `ineligible` observations — check the
mix before concluding.

## Step 3 — Read the findings

- **Monitors:** focus on `verdict: yes`; treat `inconclusive` as a weak signal. The observation text is the
  substance.
- **Classifiers:** group by `tags` to see the distribution of what's happening across sessions.
- **Scorers:** look at the tails (highest/lowest scores), not just the average.
- **Summarizers:** read for recurring themes across summaries.

Weight by `confidence`, and don't over-index on a single observation. To understand a specific hit, take its
`session_id` and either cross-reference other scanners (`vision-observations-list`) or drill into the actual
recording with the [[investigating-replay]] skill and the session-recording MCP tools.

To test a scanner's lens against a specific session that doesn't have an observation yet, trigger one on demand
with `vision-scanners-scan-session` — it's async (minutes; rasterising the recording + the LLM call are slow)
and, like all observations, runs at most once per `(scanner, session)`.

## Step 4 — Act on the findings

Match the action to the user's intent, and **corroborate before you create work**:

- **Summarize a pattern.** Report the finding back with the numbers and a few representative `session_id`s
  (e.g. "12 of 40 succeeded observations flagged checkout confusion; sessions A, B, C"). Cite, don't assert.
- **Make it trackable.** When a finding is corroborated across several sessions (not one low-confidence
  hit), capture it durably with the tools that exist: create an `insight` or `notebook` to track its
  frequency, bundle the supporting recordings into a session-recording playlist so a human can watch the
  evidence, and add an `annotation` if it marks a regression. There is **no MCP tool to open a PostHog
  task directly** — to route a finding into tracked work, use the Inbox path below (for signal-emitting
  scanners) or hand the summary to a human or coding agent to act on. Group by distinct issue, not per
  observation.
- **Work the Inbox.** If the scanner emits signals, its findings may already be clustered into signal reports —
  read and act on those with `inbox-reports-list` + `inbox-report-artefacts-list` (the report's work log is the
  evidence). See the [[inbox-exploration]] skill; that path also records your work against the report.

The discipline that matters: a single observation is one model's judgment on one recording. Confirm a finding
reproduces across observations (or against the raw recording) before turning it into a task, an alert, or a
claim — the same rigor the signals pipeline applies before it promotes observations to a report.

## Gotchas

- **Only `succeeded` observations have a `scanner_result`** — everything else is triage metadata.
- **`ineligible` ≠ `failed`.** Ineligible is a normal terminal outcome (e.g. the recording was too short), not
  a bug to chase.
- **One observation per `(scanner, session)`** — re-scanning a session that already has any observation
  (even ineligible/failed) is a no-op.
- **Findings are snapshotted.** Each observation keeps the `scanner_snapshot` it ran under, so older
  observations may reflect a previous prompt/config (`scanner_version`).
- **Quota is shared.** On-demand scans count against the org's monthly budget — check `vision-quota-retrieve`
  before triggering a batch of them.
