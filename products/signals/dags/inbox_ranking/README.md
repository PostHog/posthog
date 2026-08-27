# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model: the **dataset** dag (daily snapshots) and the **training** dag (daily per-head XGBoost candidates + champion pointer), sibling subpackages sharing `common.py`.

```text
inbox_ranking/
├── common.py       # shared: S3 destination config, daily partition def, gating, Parquet IO
├── dataset/
│   ├── dag.py      # the five dataset assets + job + schedule
│   └── queries.py  # HogQL label SQL, embeddings SQL, stream merging
├── training/
│   ├── dag.py        # examples → candidate → champion assets + job + schedule
│   ├── examples.py   # scoring-moment training examples over the snapshots
│   ├── heads.py      # the v0 outcome heads
│   ├── train.py      # per-head XGBoost fit + holdout/null metrics
│   └── promotion.py  # the champion promotion rule
└── tests/
```

Registered via `posthog/dags/locations/signals.py` (US only) and loaded locally through `.dagster_home/workspace.yaml`.

## The dataset dag

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on prod US, stopped everywhere else — including hosted DEV and E2E, which have no dogfood project to read labels from) and builds five assets on one daily partition, each a Parquet object in S3:

```text
s3://<bucket>/<prefix>/
├── inbox_report_state/v1/dt=YYYY-MM-DD/       # Postgres spine + report state + tabular features
├── inbox_report_embeddings/v1/dt=YYYY-MM-DD/  # report_id -> small-1536 vector as of snapshot end
├── inbox_report_labels/v1/dt=YYYY-MM-DD/      # cumulative label columns from dogfood telemetry
├── inbox_report_model_data/v1/
│   ├── dt=YYYY-MM-DD/                         # materialized join of the three (the training table)
│   └── latest/                                # rewritten by the newest partition; warehouse tables point here
└── inbox_signal_embeddings/v1/dt=YYYY-MM-DD/  # one row per signal emitted during the day (signal grain)
```

The first four are report grain and land in one table. `inbox_signal_embeddings` is signal grain, feeds the group-level model, and is read on its own — training joins it to `inbox_report_model_data` by `report_id`.

### Partition semantics

- Partition `dt=D` snapshots the eligible report inventory (promoted before `D+1 00:00 UTC`, or referenced by any label event before it). Every label aggregate is bounded `event_time < D+1 00:00 UTC`.
- Label columns are **cumulative**: later partitions strictly dominate earlier ones, so training reads features from `dt=D` and labels from any later partition, choosing the label-maturity window at read time. Late labels are never backfilled into old partitions.
- `latest/` advances **monotonically**: each write stamps a `snapshot-date` in S3 object metadata, and a partition rewrites `latest/` only when it is at or ahead of what `latest/` holds. Delayed retries of the newest day repair it; backfills of older days never clobber it.
- Rows for reports **outside this dag's region** are label-only: no Postgres state, no embedding, and `report_team_id` null (a US team id and an EU team id of the same number are different teams, so the label stream's id can't be merged in). `status_event_team_id` carries the team the transition itself reported, which is the tenant attribution those rows do have.
- **Backfills are not fully point-in-time**: labels are exact for any past day, embeddings are exact within the source table's 3-month TTL, but report state is read from Postgres as of the run (`features_observed_at` flags this per row).
- Report-state mutability reaches **inclusion**, not just feature values: `promoted_at` is cleared on suppression and snooze, so a report promoted before the cutoff and suppressed after it leaves the spine unless a label event referenced it before the cutoff. Forward runs see this only for the 2.5 hours between the cutoff and the schedule; backfills see the full accumulated effect. Deriving the spine from immutable promotion history (`signal_report_status_changed` carries `promoted_at`) is the v2 fix.

### Signal-grain partitions

`inbox_signal_embeddings` is the one asset here whose partitions are **not** full snapshots. `dt=D` holds only the signal documents inserted during D — an emission log — because a cumulative copy at signal grain means a 1536-float vector per signal, fleet-wide, rewritten every day.

- Read the **union** of partitions and take the latest row per `(team_id, signal_id)` at or before the cutoff. `signal_id` (the ClickHouse `document_id`) is caller-supplied and only unique within a team, so the tenant key is part of the identity. That is the same `(team_id, document_id)` latest-wins the report assets do in SQL, moved to read time.
- **The log is best-effort, not complete.** The source is a ReplacingMergeTree versioned by `inserted_at`, and a retraction re-emits the signal under the same sort key, so a merge between the two writes keeps only the retraction. A signal whose report is deleted in the same window it was inserted reaches no partition in its live form, and no query shape recovers it: the merge has already dropped the row.
- The reverse gap is the TTL. A retraction inherits the original event timestamp, so retracting a signal more than three months old writes a row that is already expired and may never be scanned. **Absence of an `is_deleted` row is not proof that a signal is live**, and this archive is not authoritative for deletion — see the retention section below.
- The vectors' source TTL runs from **signal event time**, so this asset is also where signal vectors become durable. Whatever a partition does not capture before its signals age out is gone.
- Consequently **a re-run is additive**: it unions the fresh scan into the rows the partition already holds, keyed by `(team_id, signal_id, embedding_inserted_at)`, so a row the source can no longer supply survives. Overwriting with the scan alone would delete it permanently, and a row count cannot police that — a scan can lose one emission and gain another and land on the same total.
- The count check remains as a backstop: a union can only grow, so a smaller result means the merge itself is broken and the write is refused. Row counts are stamped in S3 object metadata at write time to make that check a `head_object`. A deliberate shrink still means deleting the object by hand.
- Signal text never leaves ClickHouse: the query selects the vector and the structured metadata (weight, source, match graph), not `content` or the free-text metadata fields.

## The training dag

`inbox_ranking_training_job` runs daily at 06:00 UTC on the same partition definition (gated like the dataset job) and writes:

```text
s3://<bucket>/<prefix>/
├── inbox_ranking_training_examples/v1/dt=YYYY-MM-DD/   # scoring-moment examples, all heads, one parquet
└── inbox_ranking_models/v1/
    ├── dt=YYYY-MM-DD/<head>.ubj + <head>.holdout.ubj    # the day's candidate: serving fit + train-only fit
    │                  + metadata.json                     # (a re-run replaces this prefix in full)
    └── champion.json                                     # pointer the scoring sweep loads (the only object written across partitions)
```

- **Examples are scoring moments, not reports.** For partition `dt=D` the examples asset reads the report-state and labels snapshots `dt=D-lookback..D` and emits one row per (report, snapshot) whose head label is still 0 on that snapshot, labeled from the snapshot `horizon_days` later (3 for open, 7 for action / dismiss_wrong / pr_created). Features are that snapshot's state columns plus `age_hours`, the report's age at the snapshot. Labels are aligned to the state spine, so a report with no label event is a negative (all-zero labels), not absent. Label-only rows (no Postgres state) are skipped, as are state rows read long after their snapshot day (backfills carry current Postgres state; see `features_observed_at`) and, for the `dismiss_wrong` head, rows whose status telemetry fails the dataset's `label_provenance_ok` check. This is the serving situation replayed over history; it measured better than one row per report on the engagement heads.
- **Serving population caveat.** Training keeps only moments where the head's outcome has not happened yet, but the scoring sweep cannot see outcome state, so it also scores reports that were already opened or acted on. `p_open` on an already-opened report is undefined; the shadow eval joins scores as of impression time, which keeps the read honest. Stopping a head once its outcome is observed is a sweep-side change.
- **Features are tabular only in v0** (`products/signals/backend/ranking/features.py`: the state counters, title/summary length, age, one-hot priority/actionability). No embedding, no impression-derived columns, so the scoring sweep needs only the `SignalReport` row and its judgment artefacts. The sweep must build features through the same module; the booster's `feature_names` are checked against it at load.
- **Candidate**: per-head XGBoost with fixed params, holdout = the last `holdout_days` of reports (cut by report, never by row), AUC + a label-permutation null. A head is _readable_ when it has enough holdout positives and clears its null by 0.05. The shipped booster (`<head>.ubj`) is refit on everything; the train-only fit is kept as `<head>.holdout.ubj` so a later candidate can grade this model on its own holdout.
- **Champion**: `promotion.decide_promotion` — promote when the candidate has a readable head, is within 0.02 AUC of the champion on every head the champion could read, and the champion is at least `INBOX_RANKING_PROMOTION_MIN_DAYS` old. The champion's AUCs come from its `<head>.holdout.ubj` scored on the candidate's holdout (`paired_champion_aucs`), so both models are compared on one set of reports; a champion without that file falls back to its stored AUC. The pointer is rewritten only when `INBOX_RANKING_AUTO_PROMOTE` is on; otherwise the decision is logged and surfaced as asset metadata, so the daily candidate series is monitoring while the first shadow read runs on a frozen champion. To promote by hand, copy a candidate's `metadata.json` to `champion.json` with a `promoted_at`.

### Configuration

| Setting                                | Default         | Meaning                                                                                                                                                                                                             |
| -------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET`      | unset           | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (SeaweedFS in dev and CI). |
| `INBOX_RANKING_DATASET_S3_PREFIX`      | `inbox_ranking` | Key prefix under the bucket.                                                                                                                                                                                        |
| `INBOX_RANKING_TRAINING_LOOKBACK_DAYS` | `60`            | How many daily snapshots back the training examples reach.                                                                                                                                                          |
| `INBOX_RANKING_TRAINING_HOLDOUT_DAYS`  | `7`             | Trailing days of reports that grade a candidate.                                                                                                                                                                    |
| `INBOX_RANKING_AUTO_PROMOTE`           | `false`         | Whether a winning candidate rewrites `champion.json`; off, the decision is only logged.                                                                                                                             |
| `INBOX_RANKING_PROMOTION_MIN_DAYS`     | `3`             | Minimum age of the champion before another promotion.                                                                                                                                                               |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

### ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan has no `team_id` sort-key prefix and why that is acceptable).

### Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch). Every asset sits in the `inbox_ranking_etl` pool so concurrent partitions don't each start their own fleet-wide embeddings scan — the pool's limit is a Dagster deployment setting, provisioned with the bucket.
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_`, `inbox_signal_`, and `inbox_ranking_` asset-name prefixes.
- The job is capped at 3h via `dagster/max_runtime` — the seven label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them.

### Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
The same holds for signal rows, with one addition: a retraction can expire out of the source before any run scans it, so a scrub cannot be driven off `is_deleted` in this archive and has to work from the deleted report's id.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
