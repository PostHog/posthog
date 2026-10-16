# deltalite

Streaming, partition-level **upsert for [Delta Lake](https://delta.io/) tables**
that replaces delta-rs's SQL `MERGE` with a bounded-memory merge engine. Memory
is bounded by the size of the incoming batch and a few concurrency knobs —
**never by the size of the target table**.

delta-rs stays the storage and protocol layer (transaction log, checkpoints,
Parquet encoding, S3 conditional-put commits, conflict resolution). deltalite
replaces only the *merge execution*, and writes output files through a streaming
writer that produces the same files and Add-action statistics as delta-rs's
`RecordBatchWriter` without holding a second copy of each file.

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
| `.compact(**opts)` | Small-file compaction, the replacement for `DeltaTable.optimize.compact`. Returns a stats dict. See "Compaction" below. |
| `.version()` | Current table version (`int`). |
| `.reload()` | Bring the table state up to date with the log (incremental; falls back to a full re-open). |
| `.table_id()` | The table id from the metadata action (`str`). |
| `.configuration()` | Table configuration, `delta.*` properties and custom keys (`dict[str, str]`). |
| `.schema_arrow()` | Table schema as a pyarrow `Schema`. |
| `.schema_json()` | Table schema as the Delta JSON document (`str`), as `DeltaTable.schema().to_json()` returns it. |
| `.partition_columns()` | Partition column names (`list[str]`). |
| `.num_files()` | Number of active data files (`int`). |
| `.files()` | Active data files as dicts: `path` (relative to the table root), `size`, `modification_time` (epoch ms), `partition_values` (`dict[str, str \| None]`). |
| `.file_uris()` | URIs of the table's active data files. |
| `.history(limit)` | Recent commit history entries. |

`version`, `table_id`, `configuration`, `schema_*`, `partition_columns`,
`num_files`, `files` and `file_uris` read the loaded snapshot in memory and do
no I/O; call `reload()` first when the table may have moved. `history` reads the
log.

### `UpsertStats`

Returned by `upsert`. Counts: `version`, `partitions_touched`, `files_added`,
`files_removed`, `files_carried_over`, `files_probed`, `rows_updated`,
`rows_inserted`, `rows_copied`, `source_rows`, `null_pk_rows`. Per-phase
wall-clock timings (milliseconds): `ingest_ms` (importing the pyarrow source),
`initial_open_ms` (the full snapshot load in `DeltaLiteTable.open`, reported on
the first upsert through a handle and `0` afterwards, so a sum over a handle's
upserts counts it once), `open_ms` (snapshot refreshes around the upsert),
`relax_ms` (nullability-relax check), `plan_ms` (listing + pruning files),
`rewrite_ms` (reading + rewriting the touched partitions), `commit_ms`
(committing to the Delta log), `maintenance_ms` (checkpoint/log cleanup,
non-zero only on checkpoint-boundary commits). `columns_relaxed` counts
non-nullable columns flipped to nullable before the write.

### Compaction

`compact` plans bins exactly as delta-rs's `optimize.compact` does, from the
loaded log with no storage reads, and commits them the same way (ZSTD level 4,
one `OPTIMIZE` commit, `dataChange=false`). Each bin is streamed one file and
one byte-bounded batch at a time through the upsert's fetch and decode budgets,
so memory follows the knobs, not the bin. Output files and row groups are also
capped by decoded size, so a bin that decodes past a cap writes more than one
file where delta-rs writes one.

| Knob | Default | Meaning |
|---|---|---|
| `target_file_size` | table's `delta.targetFileSize` | Bin size and output file size (compressed bytes). |
| `max_parallel_bins` | 2 | Bins rewritten at once. |
| `slot_budget_bytes` | none | Memory for the whole call: caps the decode and fetch budgets at a quarter each and lowers `max_parallel_bins` so the output files fit the rest. |
| `max_decoded_file_bytes` | 1 GiB | An output file closes when its decoded bytes reach this (keeps files under the 2 GiB Arrow offset limit). |
| `max_row_group_decoded_bytes` | 128 MiB | An output row group closes at this many decoded bytes. |
| `partitions` | all | Only these partition values. |
| `min_partition_removable_files` | 1 | Rewrite a partition only when its bins remove at least this many more files than they write. `1` is delta-rs's behavior. |
| `max_bins_per_commit` | one commit | Commit every N bins instead. |
| `max_replan_rounds` | 1 | Times the partitions of bins dropped on a conflict are planned and rewritten again. |
| `commit_max_retries` | 15 | Commit attempts after another writer committed first. |
| `dry_run` | `False` | Plan only; report what would be rewritten. |

Conflicts: when another writer commits first, compaction keeps each bin whose
input files are all still live and drops the others (deleting their output), so
it never resurrects rows a merge replaced. A concurrent schema, partitioning or
protocol change raises `DeltaLiteCommitConflictError`. Tables the upsert refuses
are refused here too (`DeltaLiteUnsupportedTableError`). The result dict carries
deltalite's counters plus delta-rs's `numFilesAdded`, `numFilesRemoved`,
`partitionsOptimized`, `numBatches`, `totalConsideredFiles` and
`totalFilesSkipped`.

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
| `max_buffered_bytes` | `64 MiB` | Decoded rows in flight between the file readers and the writer. |
| `max_fetch_bytes` | `128 MiB` | Compressed row-group bytes the file readers hold before decoding. A reader reserves its file's largest row group before fetching; a row group larger than the cap still runs, alone. |
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
`DELTALITE_PROCESS_MAX_FETCH_BYTES` (256 MiB),
`DELTALITE_MAX_SOURCE_BYTES`, `DELTALITE_MULTIPART_THRESHOLD_BYTES`,
`DELTALITE_MULTIPART_PART_SIZE_BYTES`.

**Checkpoint prefetch.** Opening or reloading a table reads its latest
checkpoint Parquet file whole in one GET and serves the Parquet reader's many
small range reads from memory, instead of one round trip per footer, metadata
block and column chunk. `DELTALITE_CHECKPOINT_PREFETCH_MAX_BYTES` (128 MiB)
bounds the total checkpoint bytes cached by one table load; larger files or
multipart checkpoints that exhaust the budget fall back to range reads, and `0`
disables the prefetch. Cached bytes also reserve space from
`DELTALITE_PROCESS_MAX_BUFFERED_BYTES`, so concurrent table opens share the
process-wide budget. The bytes are released as soon as the load finishes.

**Commit snapshot adoption.** After a successful upsert the handle keeps the
table state delta-rs derived for the commit it just wrote (the same state every
delta-rs operation returns) instead of listing the log and reading that commit
back. The next upsert still refreshes before it plans, so commits from other
writers are observed exactly as before, and a checkpoint the upsert's own
maintenance wrote is adopted on that refresh.
`DELTALITE_ADOPT_COMMIT_SNAPSHOT=0` restores the post-commit refresh.

**Data-file reads.** Every Parquet data file is opened with a 64 KiB footer size
hint, so a footer that fits arrives in one GET instead of two, and a file the
probe found a match in hands its parsed footer to the rewrite, so the file is
not opened a second time.

**Log requests.** Four changes remove LIST requests of `_delta_log/` and repeated
reads. Each one has a kill switch that restores the earlier requests: set the
variable to `0` (`false`, `off` and `no` also work).

| Switch | What it controls |
| --- | --- |
| `DELTALITE_PROBE_REFRESH` | A refresh asks if the snapshot is current with one GET and one HEAD, sent together, before it lists the log. The GET is for the commit file after the loaded version: a 404 proves that no newer version exists, because versions have no gaps and a commit file is written one time. The HEAD compares the ETag and the modification time of a commit file that the last load read, so a table that was deleted and created again is loaded again. When a newer commit exists, the refresh lists the log as before. |
| `DELTALITE_OPTIMISTIC_COMMIT_VERSION` | Before the commit put, delta-rs lists the log to find the latest version. The same GET and HEAD replace that LIST. The create-only put (`If-None-Match: *` on S3) stays the conflict check. If the put loses a race, delta-rs lists the log and checks for conflicts as before. If the table was replaced, the commit fails as a conflict, writes nothing, and the upsert runs again on the table that it loads again. |
| `DELTALITE_COMMIT_JSON_CACHE` | During one load each commit file is read one time (the kernel reads it two times), and the commit that an upsert wrote is not read back. The memory is at most 256 files and 8 MiB (1 MiB for one file), counts against `DELTALITE_CHECKPOINT_PREFETCH_MAX_BYTES` and `DELTALITE_PROCESS_MAX_BUFFERED_BYTES`, and is released when the operation ends. A commit that does not fit is read as before. |
| `DELTALITE_SMALL_FILE_SINGLE_GET` | A data file of 64 KiB or less is read with one GET when it is opened without a footer from the probe. The size comes from the Delta log. The reader takes its permit from the fetch budget (`max_fetch_bytes`, `DELTALITE_PROCESS_MAX_FETCH_BYTES`) for the whole file before the request, and the bytes are released with the reader. |

The probe is used only while a 404 is proof:

- The handle lists the log when the last LIST is older than 10 minutes, or older
  than half of `delta.logRetentionDuration` if that is shorter. Log cleanup
  removes only commit files older than the retention, so inside this time a
  missing commit file was never written.
- The handle lists the log when the last load read no commit file (the loaded
  version is a checkpoint version), when the store gives no ETag, and after its
  own commit on a checkpoint boundary.
- A log store that does not commit with a create-only put (for example the
  DynamoDB lock store) keeps the LIST before the commit put.

The probe needs a store that answers a GET or a HEAD with the current state of
the object. S3 does this (reads are strongly consistent after a write or a
delete), and so do SeaweedFS, the local file system and the in-memory store. Set
`DELTALITE_PROBE_REFRESH=0` and `DELTALITE_OPTIMISTIC_COMMIT_VERSION=0` for a
store, or a cache in front of a store, that can answer 404 for an object that
exists.

## Metrics

deltalite emits via the Rust [`metrics`](https://docs.rs/metrics) facade (static
labels only): `deltalite_upserts_total` (`outcome`, `prune_strategy`,
`error_kind`), `deltalite_upsert_duration_seconds`,
`deltalite_files_{added,removed,carried_over,probed}_total`,
`deltalite_rows_{updated,inserted,copied}_total`,
`deltalite_checkpoint_prefetch_total` (`outcome`),
`deltalite_refresh_probe_total` (`outcome`: `current`, `new_commits`,
`replaced`, `unknown`, `listed`, `no_anchor`), and
`deltalite_commit_probe_total` (`outcome`).

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
