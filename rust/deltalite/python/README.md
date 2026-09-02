# deltalite

Streaming, partition-level **upsert for [Delta Lake](https://delta.io/) tables**
that replaces delta-rs's SQL `MERGE` with a bounded-memory merge engine. Memory
is bounded by the size of the incoming batch and a few concurrency knobs —
**never by the size of the target table**.

delta-rs stays the storage and protocol layer (transaction log, checkpoints,
Parquet writing, Add-action statistics, S3 conditional-put commits, conflict
resolution). deltalite replaces only the *merge execution*.

```python
import deltalite

table = deltalite.DeltaLiteTable.open("s3://bucket/my_table")
stats = table.upsert(record_batch, primary_keys=["id"], partition_key="day")
print(f"v{stats.version}: +{stats.rows_inserted} / ~{stats.rows_updated}")
```

## Why

delta-rs `MERGE` executes a DataFusion hash join whose memory scales with the
*scanned target*, and it can **deadlock under a bounded memory pool**
([delta-io/delta-rs#4614](https://github.com/delta-io/delta-rs/issues/4614)).
For a large, slowly-changing table merged against a comparatively small batch —
the typical incremental-sync shape — that means either OOM risk or a hang.

deltalite takes a different route:

1. Build a primary-key hash set over the (small) **source** batch.
2. Stream the (large) **target** one Parquet row group at a time, dropping rows
   whose key is in the source set.
3. Write survivors plus the source rows into new files.
4. Commit every touched partition in **one atomic Delta commit**.

Peak memory is bounded by the source batch and the concurrency knobs, not by
the table. In validation, resident memory stayed flat from 62k- to 1M-row
partitions (~4× below `MERGE`) at matching write volume, via exact
content-based file selection.

## Installation

```bash
pip install deltalite
# or
uv add deltalite
```

Prebuilt `cp312-abi3` wheels are published for manylinux (2_28) and musllinux
on x86_64/aarch64, and macOS on arm64/x86_64. A single wheel works on **any
CPython 3.12 or newer**. No Rust toolchain is needed to install.

## Usage

`upsert` accepts anything with the pyarrow C-stream interface — a
`pyarrow.Table`, a `RecordBatch`, or a `RecordBatchReader`:

```python
import pyarrow as pa
import deltalite

table = deltalite.DeltaLiteTable.open(
    "s3://bucket/events",
    storage_options={
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "...",
        "AWS_SECRET_ACCESS_KEY": "...",
    },
)

batch = pa.table({
    "id":  [1, 2, 3],
    "day": ["2026-01-01", "2026-01-01", "2026-01-02"],
    "val": ["a", "b", "c"],
})

stats = table.upsert(
    batch,
    primary_keys=["id"],
    partition_key="day",          # omit for an unpartitioned table
    commit_metadata={"source": "my-sync"},
)

print(stats)
# UpsertStats(version=42, partitions_touched=2, files_added=2, files_removed=1, ...)
```

Rows in the batch whose primary key already exists are **replaced**; new keys
are **inserted**. Deletes are not expressed through `upsert` — it is an
insert-or-replace by key. Duplicate primary keys *within a single batch* are
rejected (raising `DeltaLiteError`) rather than silently double-inserted.

## API

### `DeltaLiteTable`

| Method | Description |
|---|---|
| `DeltaLiteTable.open(uri, storage_options=None)` | Open an existing Delta table. `storage_options` is the usual object-store dict (S3/GCS/Azure/local). |
| `DeltaLiteTable.is_deltatable(uri, storage_options=None)` | `True` if a Delta table exists at `uri`. |
| `.upsert(data, primary_keys, partition_key=None, **opts)` | Insert-or-replace `data` by key. Returns `UpsertStats`. See knobs below. |
| `.version()` | Current table version (`int`). |
| `.reload()` | Reload the table state from the log. |
| `.schema_arrow()` | Table schema as a pyarrow `Schema`. |
| `.partition_columns()` | Partition column names (`list[str]`). |
| `.file_uris()` | URIs of the table's active data files. |
| `.history(limit)` | Recent commit history entries. |

### `UpsertStats`

Returned by `upsert`. Counts: `version`, `partitions_touched`, `files_added`,
`files_removed`, `files_carried_over`, `files_probed`, `rows_updated`,
`rows_inserted`, `rows_copied`, `source_rows`, `null_pk_rows`. Per-phase
wall-clock timings (milliseconds): `plan_ms` (listing + pruning files),
`rewrite_ms` (reading + rewriting the touched partitions), `commit_ms`
(committing to the Delta log).

### Exceptions

All inherit from `DeltaLiteError`, so you can catch the base or branch on kind:

| Exception | Raised when |
|---|---|
| `DeltaLiteError` | Base class / generic failure. |
| `DeltaLiteCommitConflictError` | Concurrent commit won the conditional-put race (retry-exhausted). |
| `DeltaLiteSchemaMismatchError` | Batch schema is incompatible with the table. |
| `DeltaLiteTableNotFoundError` | No Delta table at the URI. |
| `DeltaLiteUnsupportedTableError` | Table uses a feature deltalite can't handle (e.g. deletion vectors, column mapping). |
| `DeltaLiteSourceTooLargeError` | Batch exceeds `max_source_bytes` (see below). |

## Operational knobs

**Per-call** — keyword arguments to `upsert` (defaults in parentheses):

| Argument | Default | Purpose |
|---|---|---|
| `max_parallel_partitions` | `2` | Partitions merged concurrently. |
| `max_parallel_files` | `4` | Files read concurrently within a partition. |
| `max_buffered_bytes` | `64 MiB` | Output buffered in memory before flushing. |
| `prune_strategy` | `"probe"` | `"probe"` skips files that can't contain a source key; `"none"` scans all. |
| `skip_unmatched_files` | `True` | Convenience toggle: `False` ≡ `prune_strategy="none"`. |
| `probe_concurrency` | `8` | Concurrent statistics/probe reads. |
| `read_batch_size` | `8192` | Row-group read batch size. |
| `target_file_size` | table setting, else 100 MiB | Output file size target. |
| `max_source_bytes` | `2 GiB` | Oversized-batch guard (`0` disables). |
| `multipart_threshold` / `multipart_part_size` | `64 MiB` / `16 MiB` | Multipart upload thresholds (`0` threshold disables). |
| `commit_max_retries` | `15` | Conditional-put commit retry budget. |
| `commit_metadata` | `None` | Extra key/values recorded in the Delta commit. |

**Process-global** — environment variables, enforced *on top of* the per-call
knobs so that many concurrent upsert threads in one process cannot multiply the
budgets:

`DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS` (8),
`DELTALITE_PROCESS_MAX_PARALLEL_FILES` (16),
`DELTALITE_PROCESS_MAX_BUFFERED_BYTES` (256 MiB),
`DELTALITE_MAX_SOURCE_BYTES`, `DELTALITE_MULTIPART_THRESHOLD_BYTES`,
`DELTALITE_MULTIPART_PART_SIZE_BYTES`.

## Metrics

deltalite emits via the Rust [`metrics`](https://docs.rs/metrics) facade (static
labels only): `deltalite_upserts_total` (`outcome`, `prune_strategy`,
`error_kind`), `deltalite_upsert_duration_seconds`,
`deltalite_files_{added,removed,carried_over,probed}_total`, and
`deltalite_rows_{updated,inserted,copied}_total`.

## Compatibility & status

- Built against `deltalake` (delta-rs) `0.32.x` as the storage/protocol layer.
  Correctness is guaranteed by a **differential parity suite** that runs the
  same batch sequences through real delta-rs `MERGE` and through
  `deltalite.upsert` and asserts identical logical content — not by version
  equality.
- **Not supported:** tables with deletion vectors or column mapping (detected
  and raised as `DeltaLiteUnsupportedTableError`), and SCD2 merges.
- deltalite rejects duplicate source primary keys that `MERGE` silently
  double-inserts — check pre-existing data if you migrate an existing pipeline.

This package is developed in the [PostHog monorepo](https://github.com/PostHog/posthog)
under `rust/deltalite/`. Issues and source live there.
