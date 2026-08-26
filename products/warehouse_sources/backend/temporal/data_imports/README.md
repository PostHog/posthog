# Data Stack - Import Pipeline

## How to detect a OOM:

In the logs, you'll often see the last operation of the job being a delta merge - such as `Merging partition=...`. Followed by heartbeat logs. There will then be a 2-min gap between the last heartbeat and the start of the next retry, or if its the last attempt, then you'll see a 2-min gap before a `activity Heartbeat timeout` error log. The 2-mins (as of Oct 2025) comes from the current `heartbeat_timeout` set on the `import_data_activity` in the workflow.

Typically only incremental syncs can cause an OOM on a pod, this affects all jobs running on the pod at the time, causing them all to retry if they have retry attempts available.

Some jobs may look like they cause OOMs due to how they're always running when an OOM occurs. This is usually the case for long-running jobs, such as big Stripe tables or any other full-refresh/append-only jobs. These jobs are almost always not the cause, and so it's best to just focus on the incremental jobs when this happens.

To help with exactly that attribution problem, every import activity self-reports its workload — current phase (extract/merge), its own in-memory buffer size (the same slice-accurate accounting dynamic chunking uses), process RSS, and the peaks of both — to the warehouse Redis every `DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS` (default 30s; zero disables). See `workload_report.py`. When a worker dies silently, the retry reads the dead attempt's last report plus its pod co-tenants' and attaches them to the `dwh_pod_heartbeat_timeout` event — `self_phase`, `self_peak_buffer_bytes`, and co-tenant **aggregates only** (`co_tenant_max_peak_buffer_bytes`, counts by phase; never their schema or run ids, since a pod is multi-tenant and co-tenant identifiers belong to other teams) — so a death can be read as "was anything on this pod holding more memory, doing what" instead of guessing from at-rest table sizes. The v3 load consumer reports too, under a `{job_id}:load` span key of its own, since for v3 schemas the memory-heavy merge phase runs there rather than in the import activity. Runs whose peak buffer crosses `DATA_WAREHOUSE_WORKLOAD_HIGH_WATERMARK_BYTES` (default 500 MB) additionally emit one `dwh_workload_high_watermark` event on completion, capturing the tail of surviving runs. Observe-only for now: nothing acts on any of it.

## Why does this happen?

This happens during a deltalake merge because we have to read the whole partition from S3 (or the whole table if partitioning isn't enabled for the table) to merge data into it. If the partition has great ordering, then a lot of data can be skipped via parquet row group min/max's, but this often isn't the case, and so we often have to load the whole partition into memory. The library we use for this attempts to be clever with how it reads the data in, but it doesn't always work out in our favour.

I've found that at worst case, we require roughly 20x the memory of what the compressed partition size is at rest on S3. So, if the partition is 5 GB in S3, then I'd expect to need (at worst case) roughly 100 GB memory on the pod to merge the data without fail. Our pods currently run with memory limits of 29 GB - so any partition over 1.5 GB will likely result in a OOM at some point.

Some tables may not be partitioned. This usually comes down to one of two reasons. (1) the table existed pre-partitioning logic, or (2) the table can't be partitioned due to a lack of stable `datetime`, a numerical `id`, or a stable primary key. If the reason is (1), then resyncing the table from scratch usually solves the issue. If the reason is (2), then we usually need to dive into the table data and figure out if there is a new method we can add to partition the table.

In other cases, the table is already partitioned, but the partitions have gotten too big - usually because the table has outgrown the original partitioning method. When this happens, we need to resync the table and allow the system to implement a new partitioning method.

On rare occasions, OOMs can be caused by tables that have too wide data - that is, a column (or columns) with a lot of data. Such as LLM traces, or full email bodies. This causes us to load too much data on the pod before we get to merging - we have practices in place to handle this, but it's not 100% effective. Majority of the time we have dynamic chunking that will only ingest data up to 150 MB in CPython/Arrow before flushing it out to S3. We don't have a guideline for how to deal with these syncs, they're very rare and we handle them on a case-by-case basis.

## Repartitioning

The `ExternalDataSchema` model stores partitioning settings in the `sync_type_config` json column. We have all the possible settings listed at `posthog/warehouse/models/external_data_schema.py#L57`.

More info on what partitioning options and the different modes can be found here: [https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/README.md#partitioning](https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/README.md#partitioning)

If a table has the `partition_mode` set to `datetime`, then you'll likely see that `partition_format` is set to either `month` or `None` (which means `month`). To repartition by `day`, you'll want to update this value to `day` and then perform a resync below.

If the `partition_mode` is either `md5` or `numerical`, then you'll want to do a standard resync by following the below instructions.

If the table has no partitions, but it could be partitioned, then again just resync the table following below.

### Automated in-place repartitioning

The manual flow above re-pulls every row from the source. We also have an automated path that repartitions the data **already in S3**, so it never re-extracts from the source and never materialises an oversized partition. It lives in `pipelines/core/repartition.py` (the streaming rewrite + crash-safe swap), `pipelines/core/repartition_controller.py` (size-aware detection + gating), and `workflow_activities/repartition_table.py` (the pre-extraction activity that runs it).

How it works:

- **Detection.** After each sync, the controller measures per-partition bytes from the Delta log (`get_add_actions` — no S3 LIST, no scan) and always records `max_partition_bytes` on the schema for observability. It records a `repartition_pending` target (the next finer tier — md5 count grows, numerical size shrinks, datetime `month` → `week` → `day` → `hour`) when **either** the largest partition is over the budget (`trigger_reason=proactive_threshold`) **or** the schema has repeatedly OOM'd recently (`trigger_reason=oom_history`). The OOM path catches tables whose compressed at-rest size looks safe but whose real merge working set is much larger (e.g. wide nested-JSON columns) — see `ExternalDataSchemaOOMEvent`, recorded per occurrence at the heartbeat-timeout detection point. _Suspected_, because the raw signal ("the previous attempt stopped heartbeating") is equally a deploy, an eviction or a lost heartbeat. Each row snapshots the workload self-report evidence available at recording time (own phase, own peak buffer, co-tenant aggregates — see the self-reporting section above), and `recent_count` only counts occurrences the evidence cannot explain away: deaths self-reported outside the merge phase are excluded (their remedy is chunking or routing, not partitioning), deaths where a pod co-tenant reported a strictly larger peak buffer are excluded as collateral, and occurrences inside a fleet-wide burst of many distinct schemas are attributed to infrastructure. Exonerating evidence must also be fresh relative to the death — self-reports are periodic, so a stale snapshot describes an earlier phase of the run. Every rule fails open — missing or stale evidence never exonerates.
- **What the OOM trigger requires.** The signal behind `ExternalDataSchemaOOMEvent` is "the previous attempt stopped heartbeating", which a deploy, an eviction, a node drain and a lost heartbeat all produce as readily as a real OOM, and repartitioning finer fixes none of those. The prerequisite that keeps it from acting where partition size cannot be the cause is `min_splittable_partition_bytes()`: a split has to land above the size the coarsening path treats as over-fragmented, because below it we would be splitting a table into a layout we immediately want to merge back. Since an OOM-triggered split targets half the current largest partition, the table's largest partition must be at least a quarter of the budget for the trigger to act at all. Note that every retry attempt counts, including repeats within one job: each is a separate attempt at the same merge on whichever worker picks it up, so a job that OOMs attempt after attempt is a table failing deterministically, which is the clearest evidence the log carries.
- **Coarsening.** The same detection pass also runs the reverse direction (`trigger_reason=coarsening`, `select_coarsen_target`): a table split far below what memory safety needs pays for every partition on each merge, and most tables in that state were put there by the finer path reacting to failures that were never about size. A table is coarsened only when it has at least 16 partitions, its largest is under an eighth of the budget, at least a 4x reduction is available, no occurrence in the last 14 days still looks like its own merge OOM once the classification rules have run (infrastructure bursts and non-merge deaths do not block it, an unexplained death does, and a merge-phase death whose own peak buffer crossed `DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES` blocks whatever the rules concluded), and its current layout is at least 7 days old. Candidate layouts are computed from the measured partitions (re-formatting datetime keys, merging md5 buckets into a divisor of the current count, multiplying numerical bucket size) rather than estimated, and the coarsest one landing under **half** the budget wins. The gap between the two triggers is what stops the controller oscillating: a coarsened table must double before the finer path can claim it, and a split one must shrink eightfold before this path can.

Week into month is the one transition that cannot be computed exactly, because ISO weeks straddle month boundaries and the key does not say how a week's bytes divide between two months. It is sized by upper bound instead, charging each straddling week's full size to both months, so a layout that fits under the bound fits in reality. The transition is worth supporting rather than skipping: the finer path's first step is month into week, so without it a table this controller wrongly split could never be merged back. Note the bound also makes it the narrowest transition on offer, since a month holds only about 4.3 weeks against a 4x minimum reduction, so in practice it needs roughly a year of weekly partitions to qualify.

- **Rewrite.** On the next run, a pre-extraction activity streams the live Delta table one record-batch at a time, recomputes `_ph_partition_key` under the finer scheme, and writes a sibling temp table. It then does a crash-safe swap: delete live → server-side copy temp → verify row count → delete temp. Memory is bounded by batch size, independent of partition size. Temp stays the source of truth until the swap is verified, so a worker death at any point loses wasted compute, never data. An interruption (OOM, worker restart) can leave the `__repartitioned` temp partial, so every step that could destroy live re-validates temp first: the swap opens temp and checks it holds the full row count before deleting live, and a resume re-validates the temp the `ready` marker points at — discarding it and rebuilding fresh from the intact live rather than copying a broken temp over live. A live table whose own log is unreadable is skipped (the import activity's revival handles it), not counted as a repartition failure.
- **Safety.** Concurrent _syncs_ are excluded (the schedule's `OnlyOne` overlap policy plus the v3 pipeline lock), but concurrent _repartition attempts_ are not: an attempt Temporal heartbeat-times-out keeps running as a zombie (heartbeat failures are swallowed) while its retry starts, and S3 has no locking. The schema row's `repartition_claim` is the fence — each attempt mints a claim token, temp tables are scoped to it (`__repartitioned_<token>`), and the claim is re-checked before every batch write and every destructive step (temp sweep, swap marker, live delete). A superseded attempt raises `RepartitionSupersededError` and stands down silently; orphaned temp variants from superseded or crashed attempts are swept by name prefix before each fresh rebuild. A repartition failure never fails the sync — it's swallowed, retried on a later run, and capped at `MAX_REPARTITION_ATTEMPTS` (3) consecutive failures before it gives up and alerts. Cancellations, superseded attempts, transient infra errors (DB pooler drops, S3 rate limits), and budget-exceeded attempts that advanced the rewrite checkpoint don't count against that cap — a table too large to rewrite in one activity budget converges across runs via the checkpoint, and only an attempt that made no forward progress is charged.

Tuning and gating:

- Gated by the `data-warehouse-auto-repartition` feature flag plus a 24h per-table cooldown. The flag can be released to a single schema (`schema_id = <id>`) before rolling out by team/org/project. Coarsening has its own flag, `data-warehouse-auto-coarsen`, released the same way.
- **Repairing the existing backlog.** The automatic coarsening path will not reach a table that keeps recording OOM occurrences, and the tables most in need of coarsening are exactly the ones the unreliable OOM signal keeps firing on. `./manage.py stage_warehouse_coarsening` is the way in: it nominates tables by setting a `coarsen_requested` marker, and the next sync evaluates them. A nomination skips the policy gates (rollout flag, OOM history, layout age, minimum partition count) because an operator has made that call, but never the safety check: the controller still measures the live layout and refuses any target that would not fit the budget, so a nomination can only ever be a no-op. Nominated rewrites report `trigger_reason=coarsening_requested`. Dry run by default, `--limit` defaults low, and it is worth keeping low: a rewrite blocks that table's sync for as long as it runs, which is seconds for small tables and hours for the largest.
- The budget is tunable via the `DATA_WAREHOUSE_TARGET_PARTITION_BYTES` setting (default ~0.5 GB at-rest → ~10 GB worst-case merge). Worker pods are multi-tenant, so the budget leaves headroom for concurrent merges under the 29 GB pod limit rather than sizing to a single merge.
- The OOM-history override is tunable via `DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD` (default 3) and `DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS` (default 7). An OOM-triggered rewrite of an under-budget table steps one tier finer per cooldown cycle, converging as the (still-recorded) OOMs continue.
- The split floor and the coarsening trigger are both derived from the budget rather than tuned separately (`COARSEN_TRIGGER_DIVISOR`), so the two directions stay consistent by construction.
- The coarsening gate's own tunables are `COARSEN_OOM_FREE_DAYS` (default 14, deliberately longer than the split window) and `DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES` (default 1 MB), the peak above which a merge-phase death blocks regardless of how the classification rules explained it. `DELTA_COARSEN_DECLINE_TOTAL` records which gate declined, labelled by reason.
- CDC tables are excluded for now.

Observability: `warehouse_repartition_flagged` / `started` / `completed` / `failed` / `skipped` PostHog events (with full team/schema/source/table context, before→after scheme, sizes, durations, and trigger reason) plus `DELTA_REPARTITION_*` Prometheus metrics.

The existing admin repartition action now stages a `repartition_pending` target and triggers this cheap in-place path (no reset, no source re-pull) instead of a reset + resync.

## Admin panel actions

Most day-to-day interventions no longer need a k8s pod — they're buttons on the `ExternalDataSchema` change page in the Django admin (`/admin/warehouse_sources/externaldataschema/<schema_id>/change/`).
All admin-triggered runs are non-billable, and admin-triggered runs auto-pause the per-schema schedule for the duration and auto-unpause it on success.

- **Trigger sync / resync.** Runs an ad-hoc `external-data-job` workflow, with checkboxes for `reset_pipeline` (wipe existing files and re-pull from scratch) and `billable`. This replaces the pod snippets under [How to resync](#how-to-resync) for most cases.
- **Repartition / change partition mode.** Stages a `repartition_pending` target and triggers the cheap [in-place repartition](#automated-in-place-repartitioning) — rewrites the data already in S3, no source re-pull, no pod, no oversized partition materialised. You can switch `partition_mode` (`datetime` / `numerical` / `md5`), set the partitioning keys, and set the mode's knob (`partition_format`, `partition_size`, or `partition_count`).
- **Pause / unpause schedule.** Pause the per-schema Temporal schedule manually while doing admin work.

### Overriding the read chunk size (`chunk_size_override`)

For SQL sources (Postgres, Redshift, ClickHouse) the pipeline auto-sizes how many rows it reads per fetch by sampling the p95 row size and targeting ~150 MB per chunk.
That estimate ignores the top 5% of rows and undercounts the Python/Arrow heap the rows expand into, so a wide table with large outlier cells (long text, big arrays) can compute a huge chunk size and OOM the pod on _read_ — before any merge.

To cap it, add `chunk_size_override` (an integer row count) to the schema's `sync_type_config` JSON via the admin change form, then Save:

```json
{ "...": "...", "chunk_size_override": 15000 }
```

It bypasses the auto-sizing, is read at the start of the next run (no reset needed — a full-refresh re-reads everything anyway), and survives resets.
Start conservative (e.g. 10k–25k) and tune up: smaller chunks lower peak read memory at the cost of more fetches and more Delta files, which end-of-run compaction cleans up.

## How to resync

Prefer the admin **Trigger sync** action above; use the pod method below only when the admin isn't suitable (e.g. bulk-resyncing many schemas at once).

When we resync a table, we do so from a k8s pod. We have the ability to disable billing for a sync via this method meaning that a user won't be charged for us repartitioning their data.

To connect to a pod, follow this runbook: [https://runbooks.posthog.com/EKS/access](https://runbooks.posthog.com/EKS/access)

The following code snippet will both disable billing and reset the table - which means deleting all existing table files (other than query files). Make sure to run this on a `temporal-worker-data-warehouse` pod - they have all the correct env vars set up for this:

```python
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem()

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention.normalize_identifier(schema.name)
    s3_folder = f"{os.environ['BUCKET_URL']}/{schema.folder_path()}/{schema_name}"
    print(f"Deleting {s3_folder}")
    try:
        s3.delete(s3_folder, recursive=True)
    except:
        pass
    print("Starting temporal worker...")
    try:
        os.system('python manage.py start_temporal_workflow external-data-job "{\\"team_id\\": ' + str(team_id) + ',\\"external_data_source_id\\":\\"' + str(source_id) + '\\",\\"external_data_schema_id\\":\\"' + str(schema_id) + '\\",\\"billable\\":false,\\"reset_pipeline\\":true}" --workflow-id ' + str(schema_id) + '-resync-' + str(time.time()) + ' --task-queue data-warehouse-task-queue')
    except Exception as e:
        print(e)
    print(f"{index + 1}/{len(schema_ids)}")
```

If you want to sync a table without resetting it - then the below snippet is for you instead:

```python
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem()

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention.normalize_identifier(schema.name)
    print("Starting temporal worker...")
    try:
        os.system('python manage.py start_temporal_workflow external-data-job "{\\"team_id\\": ' + str(team_id) + ',\\"external_data_source_id\\":\\"' + str(source_id) + '\\",\\"external_data_schema_id\\":\\"' + str(schema_id) + '\\",\\"billable\\":false,\\"reset_pipeline\\":false}" --workflow-id ' + str(schema_id) + '-resync-' + str(time.time()) + ' --task-queue data-warehouse-task-queue')
    except Exception as e:
        print(e)
    print(f"{index + 1}/{len(schema_ids)}")
```

## Recovering a stuck or failed load in PipelineV3

There is no manual replay step for the load phase.
The extraction-to-load hand-off is a durable Postgres batch queue (`pipeline_v3/postgres_queue/`), not fire-and-forget messages: batch rows survive consumer crashes, transient failures retry automatically with backoff (`waiting_retry`), a crashed consumer's lease expires and its batches are reclaimed, and a reconcile sweep fails the `ExternalDataJob` for runs whose batches ended up terminally `failed`.

If a job still ends up failed, re-run the sync with the snippets above (use `reset_pipeline: false` to keep existing data).
Queue rows and their parquet files are pruned after the queue's retention window (see `postgres_queue/README.md`), so there is nothing to replay from S3 after that point either.

The Kafka-era replay runbook that used to live here reconstructed `ExportSignalMessage`s from S3 and re-produced them to the `data_warehouse_sources_jobs` topic.
That transport was removed; see git history for the old procedure.

## How to clean up orphaned S3 data

When a source or schema is soft-deleted, S3 cleanup can fail silently (it's best-effort). This leaves orphaned data in S3 that customers consider deleted.

Run this on a `temporal-worker-data-warehouse` pod to find and delete S3 folders for orphaned schemas:

```python
import os
import s3fs

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

bucket_url = os.environ['BUCKET_URL']
s3 = s3fs.S3FileSystem()

# Find schemas that are soft-deleted but whose S3 folder may still exist
orphaned_schemas = (
    ExternalDataSchema.objects
    .filter(deleted=True)
    .select_related('source')
    .iterator()
)

deleted = 0
skipped = 0
errors = 0

for schema in orphaned_schemas:
    s3_folder = f"{bucket_url}/{schema.folder_path()}"
    try:
        if s3.exists(s3_folder):
            print(f"Deleting {s3_folder} (schema={schema.id}, team={schema.team_id})")
            s3.delete(s3_folder, recursive=True)
            deleted += 1
        else:
            skipped += 1
    except Exception as e:
        print(f"Error deleting {s3_folder}: {e}")
        errors += 1

print(f"Done. Deleted: {deleted}, Already clean: {skipped}, Errors: {errors}")
```

To do a dry run first (just list what would be deleted without actually deleting):

```python
import os
import s3fs

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

bucket_url = os.environ['BUCKET_URL']
s3 = s3fs.S3FileSystem()

orphaned_schemas = (
    ExternalDataSchema.objects
    .filter(deleted=True)
    .select_related('source')
    .iterator()
)

total_size = 0
count = 0

for schema in orphaned_schemas:
    s3_folder = f"{bucket_url}/{schema.folder_path()}"
    try:
        if s3.exists(s3_folder):
            size = sum(f['size'] for f in s3.ls(s3_folder, detail=True))
            print(f"[WOULD DELETE] {s3_folder} (schema={schema.id}, team={schema.team_id}, size={size / 1024 / 1024:.1f} MB)")
            total_size += size
            count += 1
    except Exception as e:
        print(f"Error checking {s3_folder}: {e}")

print(f"\nTotal: {count} folders, {total_size / 1024 / 1024 / 1024:.2f} GB")
```
