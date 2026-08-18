# Agent notes: inbox_ranking dags

Read `README.md` first for what the dataset is and how partitions behave. This file is the guardrails for changing code here.

## Extending

- A new ranking dag (training, eval, ...) is a **sibling subpackage** (`inbox_ranking/<name>/dag.py`) importing shared plumbing from `common.py` — don't grow `dataset/` sideways and don't duplicate the S3/partition helpers.
- Register new jobs/schedules in `posthog/dags/locations/signals.py`, keep the EU gate (`is_inbox_ranking_registered()`), and remember the ci-dagster paths filter must cover every module a dag file imports (`uv run .github/scripts/check-dagster-paths.py`).

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
