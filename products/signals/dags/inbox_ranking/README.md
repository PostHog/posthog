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

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on prod US, stopped everywhere else — including hosted DEV and E2E, which have no dogfood project to read labels from) and builds four assets on one daily partition, each a Parquet object in S3:

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
- Rows for reports **outside this dag's region** are label-only: no Postgres state, no embedding, and `report_team_id` null (a US team id and an EU team id of the same number are different teams, so the label stream's id can't be merged in). `status_event_team_id` carries the team the transition itself reported, which is the tenant attribution those rows do have.
- **Backfills are not fully point-in-time**: labels are exact for any past day, embeddings are exact within the source table's 3-month TTL, but report state is read from Postgres as of the run (`features_observed_at` flags this per row).
- Report-state mutability reaches **inclusion**, not just feature values: `promoted_at` is cleared on suppression and snooze, so a report promoted before the cutoff and suppressed after it leaves the spine unless a label event referenced it before the cutoff. Forward runs see this only for the 2.5 hours between the cutoff and the schedule; backfills see the full accumulated effect. Deriving the spine from immutable promotion history (`signal_report_status_changed` carries `promoted_at`) is the v2 fix.

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
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_` asset-name prefix.
- The job is capped at 3h via `dagster/max_runtime` — the six label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them.

### Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
