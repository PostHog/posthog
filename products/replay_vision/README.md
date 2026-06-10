# Replay Vision

A sub-product of Session Replay. Users configure named **scanners** that PostHog applies to completed session recordings; results land as queryable `$recording_observed` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Scanner** — a configured probe scoped to a team. Carries a prompt, a scanner type (`monitor` / `classifier` / `scorer` / `summarizer`), a `RecordingsQuery` that selects matching sessions, and a sampling rate. Each enabled scanner has a Temporal schedule that fires every 5 minutes. Summarizers always emit per-facet embeddings for downstream free-text search.

**Observation** — one application of a scanner to a session. Created in `pending` when triggered (by the scanner's schedule or the `/observe/` action), transitions to `running` while `ApplyScannerWorkflow` executes, and lands in `succeeded` (with content emitted as a `$recording_observed` event) or `failed`. Each observation snapshots the full scanner state (`scanner_snapshot`) that produced it, so subsequent edits to the scanner don't retro-mutate history.

## Layout

- `backend/models/` — `ReplayScanner`, `ReplayObservation`, and their enums.
- `backend/api/` — DRF viewsets, serializers, URL routing.
- `backend/feature_flag.py` — `replay-vision` flag check + permission.
- `backend/admin.py` — Django admin registrations for both models.
- `frontend/` — kea-first scenes and logics for the scanner management UI.
