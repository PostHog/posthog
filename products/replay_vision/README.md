# Replay Vision

A sub-product of Session Replay. Users configure named **lenses** that PostHog applies to completed session recordings; results land as queryable `$recording_observed` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Lens** — a configured probe scoped to a team. Carries a prompt, a lens type (`monitor` / `classifier` / `scorer` / `summarizer` / `indexer`), a `RecordingsQuery` that selects matching sessions, and a sampling rate. Each enabled lens has a Temporal schedule that fires every 5 minutes.

**Observation** — one application of a lens to a session. Created in `pending` when triggered (by the lens's schedule or the `/observe/` action), transitions to `running` while `ApplyLensWorkflow` executes, and lands in `succeeded` (with content emitted as a `$recording_observed` event) or `failed`. Each observation snapshots the full lens state (`lens_snapshot`) that produced it, so subsequent edits to the lens don't retro-mutate history.

## Layout

- `backend/models/` — `ReplayLens`, `ReplayObservation`, and their enums.
- `backend/api/` — DRF viewsets, serializers, URL routing.
- `backend/feature_flag.py` — `replay-vision` flag check + permission.
- `backend/admin.py` — Django admin registrations for both models.
- `frontend/` — kea-first scenes and logics for the lens management UI.
