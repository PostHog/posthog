# Replay Vision

A sub-product of Session Replay. Users configure named **scanners** that PostHog applies to completed session recordings; results land as queryable `$recording_observed` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Scanner** — a configured probe scoped to a team. Carries a prompt, a scanner type (`monitor` / `classifier` / `scorer` / `summarizer`), a `RecordingsQuery` that selects matching sessions, and a sampling rate. Each enabled scanner has a Temporal schedule that fires every 5 minutes and sweeps for newly settled recordings past the scanner's watermark (`last_swept_at`); disabling a scanner removes its schedule, and re-enabling restarts the sweep from now rather than backfilling the gap. Summarizers always emit per-facet embeddings for downstream free-text search.

**Observation** — one application of a scanner to a session, unique per (scanner, session). Created in `pending` when triggered (by the scanner's schedule or the `/observe/` action), transitions to `running` while `ApplyScannerWorkflow` executes (rasterize the recording to video → upload to Gemini → multi-turn scan), and lands in `succeeded` (result persisted, then a `$recording_observed` event plus embeddings/tags emitted fail-soft), `failed` (with a `kind:message` `error_reason`), or `ineligible` (the session doesn't qualify — too short, too idle, no recording). Each observation snapshots the full scanner state (`scanner_snapshot`) that produced it, so subsequent edits to the scanner don't retro-mutate history. Rows stranded in `pending`/`running` by a dead workflow are failed as `orphaned` by a reaper on the reconciler tick.

**Scan scope** — what part of each matching recording a scanner watches. `recording` (the default) scans the whole recording. `moments` scans short clips around each occurrence of the scanner's configured focus events (`moments_config`: 1–10 events with optional property filters, plus before/after clip bounds): the sweep additionally requires ≥1 occurrence, fetches occurrences per session, merges overlapping windows into distinct moments (capped per session), and dispatches one observation per moment, discriminated by `moment_key` (the anchor occurrence's uuid; empty for whole-recording rows). Moments lift the active-seconds eligibility cap — hour-plus sessions become scannable because only the clip is rendered — and each moment counts as one observation against quota. Creation of moments-scoped scanners is gated by the `replay-vision-moments` flag.

**Quota** — succeeded observations write an immutable usage receipt; usage (receipts + in-flight rows) is counted against a monthly per-organization quota, with per-scanner volume estimates summed into a projected-usage prognosis shown at configuration time.

## Layout

- `backend/models/` — `ReplayScanner`, `ReplayObservation`, usage receipts, quota grants.
- `backend/api/` — DRF viewsets and serializers (scanners, observations, stats, live progress over SSE).
- `backend/queries/` — ClickHouse candidate selection (watermark + settle window + eligibility + sampling) and volume estimates.
- `backend/temporal/` — the apply workflow and its activities, per-scanner sweep, schedule reconciler (+ observation reaper), estimate refresher, and the Gemini file cleanup sweep.
- `backend/quota.py` — monthly quota accounting.
- `backend/embeddings.py` — the embedding identity shared by the write and search sides.
- `backend/max_tools.py` — Max AI tools (draft a scanner prompt, digest summaries, semantic search over observations).
- `backend/feature_flag.py` — `replay-vision` flag check + permission.
- `backend/admin.py` — Django admin registrations.
- `backend/temporal/vision_actions/` + `backend/api/vision_actions.py` — scheduled follow-up actions over observations (under active development).
- `frontend/` — kea-first scenes and logics for the scanner management UI.
