# Replay Vision

A sub-product of Session Replay. Users configure named **scanners** that PostHog applies to completed session recordings; results land as queryable `$recording_observed` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Scanner** — a configured probe scoped to a team. Carries a prompt, a scanner type (`monitor` / `classifier` / `scorer` / `summarizer`), a `RecordingsQuery` that selects matching sessions, and a sampling rate. Each enabled scanner has a Temporal schedule that fires every 5 minutes and sweeps for newly settled recordings past the scanner's watermark (`last_swept_at`); disabling a scanner removes its schedule, and re-enabling restarts the sweep from now rather than backfilling the gap (see **Backfill** for the explicit way to cover history). Summarizers always emit per-facet embeddings for downstream free-text search.

**Inline scan** — a prompt pointed at named sessions with nothing saved, for a one-off question (`POST /vision/scanners/inline_scan/`, and the path agents take instead of creating a throwaway scanner). An observation belongs to a scanner, so a scan mints one keyed by a fingerprint of its config: the same question reuses the observations it already has, a different question gets its own. Those rows carry `origin=inline`, are never listed or swept, and are reaped once they have nothing to show. See `backend/inline_scan.py` for why they exist and `backend/scanner_access.py` for how results are read back.

**Observation** — one application of a scanner to a session, unique per (scanner, session). Created in `pending` when triggered (by the scanner's schedule or the `/observe/` action), transitions to `running` while `ApplyScannerWorkflow` executes (rasterize the recording to video → upload to Gemini → multi-turn scan), and lands in `succeeded` (result persisted, then a `$recording_observed` event plus embeddings/tags emitted fail-soft), `failed` (with a `kind:message` `error_reason`), or `ineligible` (the session doesn't qualify — too short, too idle, no recording). Each observation snapshots the full scanner state (`scanner_snapshot`) that produced it, so subsequent edits to the scanner don't retro-mutate history. Rows stranded in `pending`/`running` by a dead workflow are failed as `orphaned` by a reaper on the reconciler tick.

**Backfill** — one historical scan of a scanner over a closed, past time window, walked newest-first. The window is closed, so the candidate query enumerates the exact eligible set at creation: the quoted cost (`total_count` x the model's credit price) is a ceiling, and actual spend only falls below it as already-observed sessions dedup, expired recordings land `ineligible`, and failures write no receipt. The scanner's full config is frozen into `scanner_snapshot` at creation, so later edits change neither the enumerated set nor the price nor what the observations record. A per-backfill Temporal schedule ticks every minute, dispatching the same `ApplyScannerWorkflow` children within the shared in-flight caps plus a per-backfill sub-cap; its `window_end` is clamped to the scanner's sweep watermark so live and backfill never contest a session. Backfill and live observations have equal quota priority: an active backfill's remaining commitment counts toward the projected monthly spend, the per-observation creation check enforces the org limit for both, and exhausting the monthly quota moves the backfill to `paused_quota` until an explicit resume.

**Quota** — succeeded observations write an immutable usage receipt; usage (receipts + in-flight rows) is counted against a monthly per-organization quota, with per-scanner volume estimates summed into a projected-usage prognosis shown at configuration time.

## Experiment-created scanners

The experiment creation wizard offers an opt-in Replay Vision scanner when the `replay-vision` feature flag is enabled. The scanner is a **disabled** classifier — enabling it, and the credit spend that follows, stays a human decision on the scanner itself. Its `RecordingsQuery` uses the experiment's exposure event, enrolled variant filters, custom exposure properties, and test-account setting, with the session-linkability check the experiment recordings surfaces use, applied as advice rather than a veto: an exposure event never seen with a `$session_id` falls back to the `$feature/<key>` property where one applies, and otherwise keeps the exposure filter. The check can't distinguish "captured server-side" from "not emitted yet", which at creation time is the common case, so it must never refuse and never widen the query. Scanner creation runs after the experiment has been persisted and cannot roll back a successfully created experiment.

The template lives in `frontend/src/scenes/experiments/replayVisionScanner.ts` and mirrors the one in the `scanning-experiments-with-replay-vision` skill: a fixed tag set (so variants stay comparable), an escape tag for sessions that never reached the changed surface, and no variant names in the prompt.

## Layout

- `backend/models/` — `ReplayScanner`, `ReplayObservation`, `ReplayScannerBackfill`, usage receipts, quota grants.
- `backend/api/` — DRF viewsets and serializers (scanners, observations, backfills, stats, live progress over SSE).
- `backend/queries/` — ClickHouse candidate selection (watermark + settle window + eligibility + sampling), the backfill's bounded descending walk and its exact count, and volume estimates.
- `backend/temporal/` — the apply workflow and its activities, per-scanner sweep, per-backfill tick, schedule reconciler (+ observation and backfill-schedule reapers), estimate refresher, and the Gemini file cleanup sweep.
- `backend/quota.py` — monthly quota accounting.
- `backend/embeddings.py` — the embedding identity shared by the write and search sides.
- `backend/max_tools.py` — Max AI tools (draft a scanner prompt, digest summaries, semantic search over observations).
- `backend/feature_flag.py` — `replay-vision` flag check + permission.
- `backend/admin.py` — Django admin registrations.
- `backend/temporal/vision_actions/` + `backend/api/vision_actions.py` — scheduled follow-up actions over observations (under active development).
- `frontend/` — kea-first scenes and logics for the scanner management UI.
