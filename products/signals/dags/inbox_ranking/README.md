# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model.
The one dag today is the **dataset** dag; future ranking dags (training, eval) live as sibling subpackages sharing `common.py`.

```text
inbox_ranking/
├── common.py       # shared: S3 destination config, daily partition def, gating, Parquet IO
├── dataset/
│   ├── dag.py      # the four dataset assets + job + schedule
│   └── queries.py  # HogQL label SQL, embeddings SQL, stream merging
└── tests/
```

Registered via `posthog/dags/locations/signals.py` (US only) and loaded locally through `.dagster_home/workspace.yaml`.

## The dataset dag

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on Cloud, stopped elsewhere) and builds four assets on one daily partition, each a Parquet object in S3:

```text
s3://<bucket>/<prefix>/
├── inbox_report_state/v1/dt=YYYY-MM-DD/       # Postgres spine + report state + tabular features
├── inbox_report_embeddings/v1/dt=YYYY-MM-DD/  # report_id -> small-1536 vector as of snapshot end
├── inbox_report_labels/v1/dt=YYYY-MM-DD/      # cumulative label columns from dogfood telemetry
└── inbox_report_model_data/v1/
    ├── dt=YYYY-MM-DD/                         # materialized join of the three (the training table)
    └── latest/                                # rewritten by the newest partition; warehouse tables point here
```

### Partition semantics

- Partition `dt=D` snapshots the eligible report inventory (promoted before `D+1 00:00 UTC`, or referenced by any label event before it). Every label aggregate is bounded `event_time < D+1 00:00 UTC`.
- Label columns are **cumulative**: later partitions strictly dominate earlier ones, so training reads features from `dt=D` and labels from any later partition, choosing the label-maturity window at read time. Late labels are never backfilled into old partitions.
- `latest/` advances **monotonically**: each write stamps a `snapshot-date` in S3 object metadata, and a partition rewrites `latest/` only when it is at or ahead of what `latest/` holds. Delayed retries of the newest day repair it; backfills of older days never clobber it.
- **Backfills are not fully point-in-time**: labels are exact for any past day, embeddings are exact within the source table's 3-month TTL, but report state is read from Postgres as of the run (`features_observed_at` flags this per row).

### Configuration

| Setting                           | Default         | Meaning                                                                                                                                                                                                             |
| --------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET` | unset           | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (MinIO/SeaweedFS locally). |
| `INBOX_RANKING_DATASET_S3_PREFIX` | `inbox_ranking` | Key prefix under the bucket.                                                                                                                                                                                        |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

### ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan has no `team_id` sort-key prefix and why that is acceptable).

### Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch).
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run.
- The job is capped at 1h via `dagster/max_runtime`.

### Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
When history must actually be scrubbed (a team deletion, a takedown), re-run the affected partitions - a re-run is idempotent and regenerates them from current sources, dropping what no longer exists - or delete the `dt=` objects outright.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
