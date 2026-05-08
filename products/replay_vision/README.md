# Replay Vision

A sub-product of Session Replay. Users configure named **lenses** that PostHog applies to completed session recordings; results land as queryable `$replay_lens` events that feed insights, dashboards, and PostHog Signals.

## Concepts

**Lens** — a configured probe scoped to a team. Carries a prompt, a lens type (`monitor` / `classifier` / `scorer` / `summarizer` / `indexer`), a `RecordingsQuery` that selects matching sessions, and a sampling rate. Each enabled lens has a Temporal schedule that fires every 5 minutes.

**Observation** — one application of a lens to a session. Created in `pending` when triggered (by the lens's schedule or the `/observe/` action), transitions to `running` while `ApplyLensWorkflow` executes, and lands in `succeeded` (with content emitted as a `$replay_lens` event) or `failed`. Each observation snapshots the `lens_config` and `lens_version` that produced it, so subsequent edits to the lens don't retro-mutate history.

## Layout

- `backend/models/` — `ReplayLens`, `ReplayLensObservation`, and their enums.
- `backend/temporal/` — Vision-owned Temporal workflows (e.g. `ApplyLensWorkflow`, the per-lens schedule, the reconciler, the reaper).
- `backend/presentation/` — DRF viewsets, serializers, URL routing.
- `backend/facade/` — thin contract layer for cross-product access; this product is `backend:contract-check`-isolated, so external imports must enter through `facade/api.py`.
- `backend/logic/` — business logic; keeps the facade and viewsets thin.
- `backend/admin.py` — Django admin registrations for both models.
- `frontend/` — kea-first scenes and logics for the lens management UI.
