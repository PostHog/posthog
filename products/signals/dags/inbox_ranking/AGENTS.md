# Agent notes: inbox_ranking dags

Read `README.md` first for what the dataset is and how partitions behave. This file is the guardrails for changing code here.

## Extending

- A new ranking dag (training, eval, ...) is a **sibling subpackage** (`inbox_ranking/<name>/dag.py`) importing shared plumbing from `common.py` — don't grow `dataset/` sideways and don't duplicate the S3/partition helpers.
- Register new jobs/schedules in `posthog/dags/locations/signals.py`, keep the EU gate (`is_inbox_ranking_registered()`), and remember the ci-dagster paths filter must cover every module a dag file imports (`uv run .github/scripts/check-dagster-paths.py`).

## Training dag specifics

- `products/signals/backend/ranking/features.py` holds a `FeatureSet` per feature universe (it lives in the backend so the scoring sweep owns it and the dag imports it). The tabular set is also the serving contract the sweep reads as `FEATURE_NAMES` / `feature_vector`, and the sweep refuses a booster whose `feature_names` or `feature_schema_version` disagree. Adding a tabular feature means bumping `FEATURE_SCHEMA_VERSION`, and the sweep must be able to compute it from the `SignalReport` row at scoring time — nothing impression-derived, nothing that needs the label streams.
- A model declares its feature set in `metadata.json` and is checked against that set, not against one global contract. Adding a set means an entry in `FEATURE_SETS`; the examples asset then writes its Parquet under `inbox_ranking_training_examples/v1/<feature_set>/dt=D/`, and the unseen scorer builds one matrix per set and shares it across the families that read it. Do not reintroduce a module-global feature list into the training path: two sets live side by side. A partition whose examples were written before the per-set layout has nothing under `<feature_set>/`, so re-run the examples asset for that day before re-running the candidate or the unseen scores on it.
- A set that reads a side input declares it in `extras_keys`, and reports per-row availability through `buildable`. The example builder drops the rows `buildable` returns False for. The scorer deliberately does not drop rows: every family scores the whole newborn pool, or the AUCs stop being paired and the uplift read the families exist for is unmeasurable. Watch `<set>_pool_coverage` on the scores asset instead.
- Both `buildable` and `build_matrix` take the moment being built as `as_of`, and a side input that changes over a report's life must honor it. The report vector does: reports are re-embedded when their text changes, so the snapshot's latest vector often postdates the moment, and taking it would train on text that did not exist yet. Never widen a set's side input to the latest value for convenience.
- `example_grain` and `max_examples_per_head` are per set, because the examples object is. Keep the tabular set at the scoring-moment grain with no budget: `report_embeddings` is the reason both knobs exist (1536 columns per row), and a budget on the tabular set would thin the family the other lines are measured against. A budget keeps every positive, so it moves the base rate its scores calibrate to and not the ranking.
- `feature_vector` (one row, serving) and `feature_frame` (vectorized, training) must agree row for row; a test pins it. Change both together.
- Examples are scoring moments (every report × every snapshot) unless the set asks for the report grain, labeled from the snapshot `horizon_days` later. Keep the holdout cut by report; a row-level split leaks near-duplicate snapshots of the same report. The moments are chosen before the features are built, so a set under a row budget never builds columns for rows it then drops; keep that order.
- `inbox_ranking_models/v1/<model_name>/dt=D/` is history like the dataset partitions: the only mutation is a re-run of the same partition, which replaces the prefix in full (stale head files are deleted). `<model_name>/champion.json` is the only object written outside its partition, and only the champion asset (or a human, deliberately) writes it; it carries the candidate's `run_id`, so a loader can detect a re-run behind a pinned version.
- A re-run of `inbox_ranking_unseen_scores` that scores nothing is refused when the partition already holds rows, because the newborn state snapshot behind those rows ages out and the dt=D+horizon grade reads them. A partition trained before the per-family models layout has no candidate to load, so it hits this; delete the object by hand to replace it deliberately.
- `model_name` is the model family, and every model object, scored row, grade and event carries it. A family is an entry in `MODEL_FAMILIES` (`training/unseen.py`) naming the feature set it is fit on; the candidate and champion assets walk that registry, and the loader, the grader and the events need no change to gain a family. Promotion stays inside a family, so a family never takes another family's `champion.json`. Do not fold the family into `model_version`, which the dashboard filters as a date.
- A family whose `metadata.json`, examples object or side input is missing for a partition is logged and skipped, so one family does not cost every family's series. The champion asset raises only when no family has a candidate at all.
- Skipping is not the same as rebuilding from nothing, and the difference is destructive. An empty examples object produces an empty candidate, and the candidate's prefix cleanup then deletes the boosters that partition already holds, which a `champion.json` can be pointing at. So when a side input is unavailable, leave the partition's objects alone rather than writing empty ones over them.
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
