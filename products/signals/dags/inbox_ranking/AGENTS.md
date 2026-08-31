# Agent notes: inbox_ranking dags

Read `README.md` first for what the dataset is and how partitions behave. This file is the guardrails for changing code here.

## Extending

- A new ranking dag (training, eval, ...) is a **sibling subpackage** (`inbox_ranking/<name>/dag.py`) importing shared plumbing from `common.py` — don't grow `dataset/` sideways and don't duplicate the S3/partition helpers.
- Register new jobs/schedules in `posthog/dags/locations/signals.py`, keep the EU gate (`is_inbox_ranking_registered()`), and remember the ci-dagster paths filter must cover every module a dag file imports (`uv run .github/scripts/check-dagster-paths.py`).

## Training dag specifics

- `products/signals/backend/ranking/features.py` is the serving contract (it lives in the backend so the scoring sweep owns it and the dag imports it): the training code and the sweep both import `FEATURE_NAMES` / `feature_vector`, and the sweep refuses a booster whose `feature_names` or `feature_schema_version` disagree. Adding a feature means bumping `FEATURE_SCHEMA_VERSION`, and the sweep must be able to compute it from the `SignalReport` row at scoring time — nothing impression-derived, nothing that needs the label streams.
- `feature_vector` (one row, serving) and `feature_frame` (vectorized, training) must agree row for row; a test pins it. Change both together.
- Examples are scoring moments (every report × every snapshot), labeled from the snapshot `horizon_days` later. Keep the holdout cut by report; a row-level split leaks near-duplicate snapshots of the same report.
- `inbox_ranking_models/v1/dt=D/` is history like the dataset partitions: the only mutation is a re-run of the same partition, which replaces the prefix in full (stale head files are deleted). `champion.json` is the only object written outside its partition, and only the champion asset (or a human, deliberately) writes it; it carries the candidate's `run_id`, so a loader can detect a re-run behind a pinned version.
- The champion is compared to a candidate on the candidate's holdout, through the champion's `<head>.holdout.ubj` (the train-only fit). Keep writing that file: without it the gate falls back to the champion's stored AUC, which was measured on a different set of reports.
- The example builder reads labels aligned to the state spine (`assemble_snapshot`): no label row means all-zero labels, not "absent". It drops rows whose `features_observed_at` is a backfill (`STATE_LAG_LIMIT`) and, for status-derived heads, rows that fail `label_provenance_ok`.

## Invariants — do not break

- `dt=` partitions are **immutable snapshots** with deterministic object keys; the only mutation ever applied is an idempotent re-run of the same partition. The exception is `inbox_signal_embeddings`, an emission log whose partition holds only that day's inserts — see the README's signal-grain section before touching it. Its re-run must stay **additive** (union with the existing object): the source drops rows it already archived, so a plain overwrite destroys history that exists nowhere else.
- Label columns are **cumulative from `LABELS_EPOCH`**; never bake a maturity window or a rolling time bound into the SQL (the saved `inbox_ranking_*` views roll 90 days — that is exactly why their SQL is inlined here with explicit bounds instead of reused).
- `latest/` must stay **monotonic** (snapshot-date metadata stamp); backfills must never overwrite it.
- Schema changes: additive nullable columns bump `FEATURE_SCHEMA_VERSION`; breaking changes bump the `v1` path segment. The parquet schemas and the row assemblers must stay in exact key agreement — `pa.Table.from_pylist` silently drops unknown keys, and a test guards this.
- Cross-team ClickHouse reads stay on the offline workload with explicit guards; team-2 label queries keep their event + timestamp bounds aligned with the events sort key.

## Context that lives outside the repo

The cross-session design record (decision history, label catalog, schema mock, backlog) is the `inbox-ranking` skill in the PostHog skills store — load it with `/phs inbox-ranking` before making design-level changes here.

## Verify loop

`pytest products/signals/dags/inbox_ranking/tests/`, then confirm the location resolves (import `posthog.dags.locations.signals` under Django) and run repo-wide mypy.
