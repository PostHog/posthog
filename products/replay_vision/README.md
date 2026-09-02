# Replay Vision

A sub-product of Session Replay. Users configure named **scanners** that PostHog applies to completed session recordings; results land as queryable `$recording_observed` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Scanner** — a configured probe scoped to a team.
Carries a prompt, a scanner type (`monitor` / `classifier` / `scorer` / `summarizer`), a `RecordingsQuery` that selects matching sessions, a Gemini model (which sets the per-observation credit price), and two volume levers: `sampling_mode` (a quality pre-filter over the matched sessions) and `sampling_rate` (a random downsample applied after it).
Each enabled scanner has a Temporal schedule that fires every 5 minutes and sweeps for newly settled recordings past the scanner's watermark (`last_swept_at`); disabling a scanner removes its schedule, and re-enabling restarts the sweep from now rather than backfilling the gap (see **Backfill** for the explicit way to cover history).
Summarizers always emit per-facet embeddings for downstream free-text search.
A scanner with `emits_signals` also pushes one signal per finding into the Signals inbox (`replay_vision` / `scanner_finding`), which is what the editor's Self-driving step turns on.

**Inline scan** — a prompt pointed at named sessions with nothing saved, for a one-off question (`POST /vision/scanners/inline_scan/`, and the path agents take instead of creating a throwaway scanner). An observation belongs to a scanner, so a scan mints one keyed by a fingerprint of its config: the same question reuses the observations it already has, a different question gets its own. Those rows carry `origin=inline`, are never listed or swept, and are reaped once they have nothing to show. See `backend/inline_scan.py` for why they exist and `backend/scanner_access.py` for how results are read back.

**Observation** — one application of a scanner to a session, unique per (scanner, session).
Created in `pending` when triggered (by the scanner's schedule, the `/observe/` and `/bulk_observe/` actions, or a retry of a failed observation), transitions to `running` while `ApplyScannerWorkflow` executes (rasterize the recording to video → upload to Gemini → multi-turn scan), and lands in `succeeded` (result persisted under `scanner_result.model_output`, then a `$recording_observed` event plus embeddings/tags emitted fail-soft), `failed` (with a `kind:message` `error_reason`), or `ineligible` (the session doesn't qualify — too short, too idle, no recording).
Each observation snapshots the full scanner state (`scanner_snapshot`) that produced it, so subsequent edits to the scanner don't retro-mutate history.
Rows stranded in `pending`/`running` by a dead workflow are failed as `orphaned` by a reaper on the reconciler tick.
Teams rate observations thumbs up/down, and those ratings drive the scanner's quality view and its AI prompt suggestions.
A finding can also be turned into a PostHog Task once (the observation remembers the task it minted).

**Backfill** — one historical scan of a scanner over a closed, past time window, walked newest-first. The window is closed, so the candidate query enumerates the exact eligible set at creation: the quoted cost (`total_count` x the model's credit price) is a ceiling, and actual spend only falls below it as already-observed sessions dedup, expired recordings land `ineligible`, and failures write no receipt. The scanner's full config is frozen into `scanner_snapshot` at creation, so later edits change neither the enumerated set nor the price nor what the observations record. A per-backfill Temporal schedule ticks every minute, dispatching the same `ApplyScannerWorkflow` children within the shared in-flight caps plus a per-backfill sub-cap; its `window_end` is clamped to the scanner's sweep watermark so live and backfill never contest a session. Backfill and live observations have equal quota priority: an active backfill's remaining commitment counts toward the projected monthly spend, the per-observation creation check enforces the org limit for both, and exhausting the monthly quota moves the backfill to `paused_quota` until an explicit resume.

**Quota** — succeeded observations write an immutable usage receipt priced in credits (1 credit = $0.01, set by the observation's model).
Usage (receipts + in-flight rows + in-flight prompt tests) counts against the organization's credit limit for the current billing period, falling back to the calendar month when billing hasn't synced the product.
Per-scanner volume estimates are credit-weighted and summed into a projected-spend prognosis shown at configuration time.
Scheduled observations over budget are skipped; on-demand ones are rejected.
A scanner can also carry its own optional `credit_limit` for the same period, so one broad scanner cannot drain the whole organization budget. A scanner that reaches its limit stops scanning until the period resets, stays enabled, and does not go back for the sessions it skipped.

## Scenes and tabs

**Scanner list** (`/replay-vision`), two tabs switched through `?tab=`:

| Tab      | `?tab=` | What it shows                                                             |
| -------- | ------- | ------------------------------------------------------------------------- |
| Scanners | (none)  | The team's scanner roster plus the team-wide vision metrics.              |
| Usage    | `usage` | Credit spend over time for the org, bucketed daily/weekly/monthly/yearly. |

**Scanner** (`/replay-vision/<scanner-id>`), seven tabs switched through `?tab=`. Overview is the default and writes no param.

| Tab                | `?tab=`         | What it shows                                                                                                               |
| ------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Overview           | `overview`      | At-a-glance panels: impact, verdict mix, top fixed and freeform tags, score distribution. Leads with the daily digest card. |
| Observations       | `observations`  | The scanner's observations, filterable by status, verdict, tags, and date.                                                  |
| On-demand          | `on-demand`     | Scan now: by session ID, or by picking from recent recordings.                                                              |
| Backfills          | `backfills`     | The scanner's historical backfills: create one over a past window, watch progress, pause/resume.                            |
| Configuration      | `configuration` | Read-only view of the scanner's current config.                                                                             |
| Calibration        | `calibration`   | Thumbs up/down ratings, accuracy over time, feedback themes, and the AI prompt recommendation with its prompt test.         |
| Digests and alerts | `actions`       | The vision actions bound to this scanner.                                                                                   |

**Scanner editor** (`/replay-vision/<scanner-id>/<step>`) is a stepper rather than tabs: Template, Configure, Scan conditions (`triggers`), Self-driving.
Observations, vision actions, and action runs each have their own scene under `/replay-vision/observations/…` and `/replay-vision/actions/…`.

Outside these scenes, the product also renders inside the session replay player: `ObservationsDock` shows what the team's scanners found about the recording being watched (standard players only — embedded, shared, and chromeless players skip every vision surface).

## Experiment-created scanners

The experiment creation wizard offers an opt-in Replay Vision scanner when the `replay-vision` feature flag is enabled. The scanner is a **disabled** classifier — enabling it, and the credit spend that follows, stays a human decision on the scanner itself. Its `RecordingsQuery` uses the experiment's exposure event, enrolled variant filters, custom exposure properties, and test-account setting, with the session-linkability check the experiment recordings surfaces use, applied as advice rather than a veto: an exposure event never seen with a `$session_id` falls back to the `$feature/<key>` property where one applies, and otherwise keeps the exposure filter. The check can't distinguish "captured server-side" from "not emitted yet", which at creation time is the common case, so it must never refuse and never widen the query. Scanner creation runs after the experiment has been persisted and cannot roll back a successfully created experiment.

The template lives in `frontend/src/scenes/experiments/replayVisionScanner.ts` and mirrors the one in the `scanning-experiments-with-replay-vision` skill: a fixed tag set (so variants stay comparable), an escape tag for sessions that never reached the changed surface, and no variant names in the prompt.

## Layout

- `backend/models/` — `ReplayScanner`, `ReplayObservation`, `ReplayScannerBackfill`, observation labels (ratings), usage receipts, quota grants, prompt suggestions, vision actions.
- `backend/api/` — DRF viewsets and serializers (scanners, observations, backfills, prompt suggestions, quota, vision actions, stats, live progress over SSE).
- `backend/queries/` — ClickHouse candidate selection (watermark + settle window + eligibility + sampling), the backfill's bounded descending walk and its exact count, and volume estimates.
- `backend/temporal/` — the apply workflow and its activities, per-scanner sweep, per-backfill tick, schedule reconciler (+ observation and backfill-schedule reapers), estimate refresher, prompt evaluation, vision actions, and the Gemini file cleanup sweep.
- `backend/quota.py` + `backend/billing.py` — credit accounting: the per-model price table, the receipt ledger, the quota snapshot the meter reads, and the per-org credit-limit override described below.
- `backend/enqueue_claims.py` — atomic slot claims that keep on-demand scans inside the in-flight caps.
- `backend/embeddings.py` — the embedding identity shared by the write and search sides.
- `backend/prompt_suggestions.py` + `backend/proposers/` — rating-driven prompt rewrites, one proposer per scanner type. `backend/prompt_evaluation.py` re-runs a suggestion against rated sessions before it's applied, and `backend/feedback_themes.py` clusters written thumbs-down feedback.
- `backend/impact.py` — affected sessions and users per scanner, exportable as a static cohort.
- `backend/tags.py` + `backend/tag_suggestions.py` — tag slug normalization and data-grounded vocabulary suggestions for classifiers.
- `backend/max_tools.py` — Max AI tools (draft a scanner prompt, digest summaries, semantic search over observations).
- `backend/scanner_access.py` — scanner-level RBAC shared by the API and the vision-action engine.
- `backend/facade/` — the cross-product entry point (session observations, formatted for Max reports).
- `backend/admin.py` — Django admin registrations.
- `backend/temporal/vision_actions/` + `backend/api/vision_actions.py` — scheduled follow-up actions over observations: group summaries and alerts, including the built-in daily digest.
- `frontend/` — kea-first scenes and logics for the scanner management UI; `frontend/generated/` carries the generated API types.

## Per-org credit limit override

`REPLAY_VISION_ORG_CREDIT_LIMIT_OVERRIDES` caps monthly credit spend for named organizations, on top
of whatever billing reports. It exists for organizations on unlimited plans, where billing correctly
syncs no limit but spend still needs a ceiling — our own internal org being the case it was built for.

The value is a JSON object of organization id to monthly credit cap:

```json
{ "01234567-89ab-cdef-0123-456789abcdef": 500000 }
```

- The tighter of billing's limit and the override wins, so it can only ever reduce credits.
- Every gate and spend surface reads it, because they all resolve through `quota_state`. An org at its
  override behaves exactly like an org at a billing limit: observations stop, and the quota UI and the
  cost preview both price against what is left.
- Keys are normalized through `UUID`, so uppercase or unhyphenated ids still match the org they name.
- Values clamp at zero, and booleans are rejected. A malformed entry is dropped on its own and logged;
  the rest of the map still applies. Unparseable JSON yields no overrides rather than failing startup.
- Applied org ids are logged at startup, so a cap that silently failed to match is visible.

Changing it takes a deploy, since it is read once at import.
