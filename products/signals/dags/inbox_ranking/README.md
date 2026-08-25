# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model.
The one dag today is the **dataset** dag; future ranking dags (training, eval) live as sibling subpackages sharing `common.py`.

```text
inbox_ranking/
├── common.py       # shared: S3 destination config, daily partition def, gating, Parquet IO
├── dataset/
│   ├── dag.py      # the five dataset assets + job + schedule
│   └── queries.py  # HogQL label SQL, embeddings SQL, stream merging
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

### Configuration

| Setting                           | Default         | Meaning                                                                                                                                                                                                             |
| --------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET` | unset           | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (SeaweedFS in dev and CI). |
| `INBOX_RANKING_DATASET_S3_PREFIX` | `inbox_ranking` | Key prefix under the bucket.                                                                                                                                                                                        |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

### ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan has no `team_id` sort-key prefix and why that is acceptable).

### Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch). Every asset sits in the `inbox_ranking_etl` pool so concurrent partitions don't each start their own fleet-wide embeddings scan — the pool's limit is a Dagster deployment setting, provisioned with the bucket.
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_` and `inbox_signal_` asset-name prefixes.
- The job is capped at 3h via `dagster/max_runtime` — the seven label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them.

### Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
The same holds for signal rows, with one addition: a retraction can expire out of the source before any run scans it, so a scrub cannot be driven off `is_deleted` in this archive and has to work from the deleted report's id.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
