//! Streaming partition-level upsert.
//!
//! For each affected partition: build a PK hash set over the incoming rows, stream the
//! partition's existing Parquet files a row group at a time, drop rows whose PK is being
//! replaced, write survivors plus the new rows through a stats-producing writer, and
//! collect Add/Remove actions. All partitions land in a single `CommitBuilder` commit.
//!
//! No DataFusion, no join, no spill. Within a partition, files are read and filtered by
//! up to `max_parallel_files` concurrent readers feeding one writer task through a
//! channel; every surviving batch holds byte-budget permits from decode until it has
//! been handed to the write buffer, so decompressed survivor data in flight never
//! exceeds the budget no matter what the product of the parallelism knobs is. All three
//! budgets are enforced twice: per call (the `UpsertOptions` knobs) and per process
//! ([`ProcessLimits`]), because production runs many upserts concurrently as threads in
//! one worker process.
//!
//! The source is held exactly once: partition membership is planned as row selections
//! (`RowSel`) into the caller's cast batches, and a partition's rows are materialised
//! only inside its worker -- transiently for the PK set (narrow columns) and the final
//! write. Peak memory is bounded by `source (1x, shared with the caller)
//!  + max_parallel_partitions * (one partition's slice + PK set + write buffer)
//!  + max_buffered_bytes + in-flight read batches`, and the source term is guarded by
//! [`crate::limits::check_source_size`].

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Instant;

use arrow_array::{Array, RecordBatch, StringArray, UInt32Array};
use arrow_cast::{cast_with_options, CastOptions};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use arrow_select::filter::filter_record_batch;
use arrow_select::take::{take, take_record_batch};
use deltalake::kernel::transaction::{CommitBuilder, CommitProperties};
use deltalake::kernel::{Action, Remove};
use deltalake::protocol::{DeltaOperation, SaveMode};
use deltalake::table::config::TablePropertiesExt;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalake::{DeltaTable, ObjectStore, PartitionFilter, PartitionValue, Path};
use futures::{StreamExt, TryStreamExt};
use metrics::{counter, histogram};
use parquet::arrow::async_reader::ParquetObjectReader;
use parquet::arrow::ParquetRecordBatchStreamBuilder;
use parquet::arrow::ProjectionMask;
use serde_json::Value;
use tokio::sync::{mpsc, OwnedSemaphorePermit, Semaphore};
use tracing::{debug, info, instrument};

use crate::errors::{Error, Result};
use crate::limits::{
    check_source_size, estimate_pk_set_bytes, resolve_max_source_bytes, ProcessLimits,
    SourceFootprint,
};
use crate::pkset::PkSet;
use crate::schema::{cast_to_schema, unknown_columns};

/// One logical group of work: a partition value (or the whole table when unpartitioned).
const WHOLE_TABLE: &str = "__deltalite_whole_table__";

/// How the set of existing files to rewrite is chosen within each affected partition.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum PruneStrategy {
    /// Rewrite every live file in the partition.
    None,
    /// Skip files whose Add-action statistics *prove* they hold no match: min/max
    /// disjointness on the first PK column, or a PK column that is entirely NULL
    /// (`nullCount == numRecords`; SQL NULL never matches). Zero extra I/O, but
    /// approximate-conservative: with random UUID keys min/max excludes nothing.
    Stats,
    /// `Stats` first, then read ONLY the PK column(s) of each surviving file (Parquet
    /// projection pushdown) and probe them against the source PK set, skipping files
    /// with zero matches. Exact, like MERGE's join-based file selection, at the cost of
    /// one streamed pass over one narrow column per candidate file. With random UUID
    /// keys (whose min/max stats prune nothing), this is what keeps bytes written
    /// identical to MERGE instead of rewriting every candidate file.
    #[default]
    Probe,
}

impl PruneStrategy {
    /// Static label for metrics; never allocate for metric labels (rust/CLAUDE.md).
    pub fn as_str(&self) -> &'static str {
        match self {
            PruneStrategy::None => "none",
            PruneStrategy::Stats => "stats",
            PruneStrategy::Probe => "probe",
        }
    }
}

impl std::str::FromStr for PruneStrategy {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self> {
        match s.to_ascii_lowercase().as_str() {
            "none" => Ok(Self::None),
            "stats" => Ok(Self::Stats),
            "probe" => Ok(Self::Probe),
            other => Err(Error::Generic(format!(
                "unknown prune_strategy '{other}' (expected 'none', 'stats' or 'probe')"
            ))),
        }
    }
}

/// Options controlling a single `upsert` call.
pub struct UpsertOptions {
    /// Column names forming the primary key, in order.
    pub primary_keys: Vec<String>,
    /// The partition column the caller believes the table uses; the table's own
    /// metadata remains the source of truth.
    pub partition_key: Option<String>,
    /// Extra `commitInfo` metadata (e.g. `run_uuid` / `batch_index` idempotency tags).
    pub commit_metadata: Option<HashMap<String, Value>>,
    /// Concurrent partition workers within this call.
    pub max_parallel_partitions: usize,
    /// How the rewrite set is chosen. See [`PruneStrategy`].
    pub prune_strategy: PruneStrategy,
    /// How many files a partition worker probes concurrently. Each in-flight probe
    /// holds only a Parquet footer plus one decoded batch of the PK column(s), so the
    /// memory bound is `max_parallel_partitions * probe_concurrency * O(batch of PKs)`
    /// -- a few MB, independent of table size.
    pub probe_concurrency: usize,
    /// Concurrent file readers *within* one partition. Files are independent for the
    /// read->probe->filter stage; a single writer task per partition consumes their
    /// output, so file count and output-file sizing are unchanged by this knob.
    pub max_parallel_files: usize,
    /// Per-call cap (bytes) on decompressed survivor batches in flight across this
    /// call's partition workers and file readers. The process-wide cap in
    /// [`ProcessLimits`] applies on top.
    pub max_buffered_bytes: usize,
    /// Commit retry budget handed to `CommitBuilder`.
    pub commit_max_retries: usize,
    /// Row-count granularity for Parquet reads and source-slice writes.
    pub read_batch_size: usize,
    /// Flush the write buffer once it exceeds this many bytes, bounding resident memory
    /// at the cost of more (smaller) output files.
    ///
    /// `None` means "use the table's own `delta.targetFileSize`", falling back to
    /// delta-rs's `DEFAULT_TARGET_FILE_SIZE` (100 MiB) when the table does not set it --
    /// which is what every other delta-rs operation (optimize, merge, delete, update,
    /// write) does. Hardcoding a value here would make `upsert` the one writer that
    /// ignores a table explicitly configured with a different target.
    ///
    /// Note this knob does double duty in deltalite: it shapes output file size *and*
    /// is the write-buffer flush threshold, so it is also a memory knob worth
    /// `max_parallel_partitions x target_file_size` of exposure.
    pub target_file_size: Option<usize>,
    /// Ceiling for the source-size guard; `None` resolves from the environment,
    /// `Some(0)` disables. See [`crate::limits::resolve_max_source_bytes`].
    pub max_source_bytes: Option<usize>,
    /// Process-wide concurrency budgets shared with every other concurrent upsert.
    pub limits: Arc<ProcessLimits>,
}

impl Default for UpsertOptions {
    fn default() -> Self {
        Self {
            primary_keys: Vec::new(),
            partition_key: None,
            commit_metadata: None,
            max_parallel_partitions: 2,
            prune_strategy: PruneStrategy::Probe,
            probe_concurrency: 8,
            max_parallel_files: 4,
            max_buffered_bytes: 64 * 1024 * 1024,
            commit_max_retries: 15,
            read_batch_size: 8192,
            target_file_size: None,
            max_source_bytes: None,
            limits: ProcessLimits::global().clone(),
        }
    }
}

/// Counters describing what one `upsert` did.
#[derive(Default, Debug, Clone)]
pub struct UpsertStats {
    /// The committed table version.
    pub version: i64,
    /// Distinct partitions the batch touched.
    pub partitions_touched: usize,
    /// Existing files tombstoned (rewritten).
    pub files_removed: usize,
    /// New files written.
    pub files_added: usize,
    /// Live files proven match-free and left untouched.
    pub files_carried_over: usize,
    /// Files whose PK column(s) were actually read by the probe (prune_strategy=probe).
    pub files_probed: usize,
    /// Existing rows dropped in favour of an incoming row.
    pub rows_updated: usize,
    /// Incoming rows with no existing match.
    pub rows_inserted: usize,
    /// Unchanged rows rewritten into new files.
    pub rows_copied: usize,
    /// Rows in the (deduped) source batch.
    pub source_rows: usize,
    /// Source rows carrying a NULL PK component (always inserted, never matched).
    pub null_pk_rows: usize,
}

/// A file selected for rewrite, with the metadata needed to tombstone it.
struct TargetFile {
    path: String,
    size: u64,
    stats: Option<String>,
    remove: Remove,
}

/// Which rows of one source batch belong to a partition. Chosen so the common shapes
/// are zero-copy: a batch wholly inside one partition is `All`, a partition-sorted
/// batch yields `Range`s (Arc-sharing slices), and only genuinely interleaved input
/// pays for a `take` copy -- and even then only inside the partition's worker, while
/// it runs, never all partitions at once.
#[derive(Debug)]
enum RowSel {
    /// Every row of the batch.
    All,
    /// A contiguous run of rows: `batch.slice(offset, len)`, zero-copy.
    Range { offset: usize, len: usize },
    /// Arbitrary row indices, materialised with `take` when the worker needs them.
    Indices(UInt32Array),
}

impl RowSel {
    /// `idx` must be strictly ascending (rows are scanned in order).
    fn from_indices(idx: Vec<u32>, batch_rows: usize) -> Self {
        if idx.len() == batch_rows {
            return RowSel::All;
        }
        match (idx.first(), idx.last()) {
            (Some(&first), Some(&last)) if idx.len() == (last - first) as usize + 1 => {
                // Ascending with span == count => consecutive.
                RowSel::Range {
                    offset: first as usize,
                    len: idx.len(),
                }
            }
            _ => RowSel::Indices(UInt32Array::from(idx)),
        }
    }

    fn len(&self, batch_rows: usize) -> usize {
        match self {
            RowSel::All => batch_rows,
            RowSel::Range { len, .. } => *len,
            RowSel::Indices(idx) => idx.len(),
        }
    }

    /// Materialise the selected rows of one column. `All`/`Range` are O(1) Arc clones.
    fn select_array(&self, col: &Arc<dyn Array>) -> Result<Arc<dyn Array>> {
        Ok(match self {
            RowSel::All => col.clone(),
            RowSel::Range { offset, len } => col.slice(*offset, *len),
            RowSel::Indices(idx) => take(col.as_ref(), idx, None)?,
        })
    }

    /// Materialise the selected rows of a whole batch. `All`/`Range` are O(1).
    fn select_batch(&self, batch: &RecordBatch) -> Result<RecordBatch> {
        Ok(match self {
            RowSel::All => batch.clone(),
            RowSel::Range { offset, len } => batch.slice(*offset, *len),
            RowSel::Indices(idx) => take_record_batch(batch, idx)?,
        })
    }
}

/// A partition's source rows, described by row selections into the shared cast batches
/// instead of a materialised slice. Holding this costs O(rows) u32 indices at worst and
/// nothing at best -- the data itself is materialised only inside the partition's
/// worker, bounded by `max_parallel_partitions`.
#[derive(Debug)]
struct PartitionSource {
    batches: Arc<Vec<RecordBatch>>,
    /// One selection per source batch, in batch order.
    sel: Vec<RowSel>,
    /// Total selected rows across all batches.
    rows: usize,
}

impl PartitionSource {
    /// The selected rows of one column (by table-schema index), per batch, skipping
    /// batches that contribute no rows. Narrow: used for PK columns only.
    fn select_column(&self, col_idx: usize) -> Result<Vec<Arc<dyn Array>>> {
        let mut out = Vec::new();
        for (b, sel) in self.batches.iter().zip(&self.sel) {
            if sel.len(b.num_rows()) == 0 {
                continue;
            }
            out.push(sel.select_array(b.column(col_idx))?);
        }
        Ok(out)
    }
}

struct PartitionWork {
    value: String,
    source: PartitionSource,
    rewrite: Vec<TargetFile>,
    carried: usize,
}

struct PartitionOutcome {
    actions: Vec<Action>,
    files_added: usize,
    files_removed: usize,
    files_probed: usize,
    rows_updated: usize,
    rows_copied: usize,
    rows_inserted: usize,
    null_pk_rows: usize,
    carried: usize,
}

/// A unit of byte budget: one permit from the per-call budget and one from the
/// process-global budget. Both ride with a batch from decode until the writer has
/// copied it into its buffer.
type BudgetPermit = (OwnedSemaphorePermit, OwnedSemaphorePermit);

/// Per-call view of the budget semaphores plus their process-global counterparts.
#[derive(Clone)]
struct Budgets {
    local: Arc<Semaphore>,
    local_cap_kb: u32,
    limits: Arc<ProcessLimits>,
}

impl Budgets {
    /// Acquire byte budget for `bytes`, capped at both budgets' capacities so a batch
    /// larger than either budget still makes progress. Local before global, the fixed
    /// order used everywhere (see `crate::limits` module docs).
    async fn acquire_bytes(&self, bytes: usize) -> Result<BudgetPermit> {
        let kb = ((bytes / 1024).max(1) as u64).min(self.local_cap_kb as u64) as u32;
        let local = self
            .local
            .clone()
            .acquire_many_owned(kb)
            .await
            .map_err(|_| Error::Generic("byte-budget semaphore closed".into()))?;
        let global = self.limits.acquire_buffer_kb(kb).await?;
        Ok((local, global))
    }
}

/// Run one streaming partition upsert against `table` and commit the result.
///
/// This is the replacement for `DeltaTable.merge(...).when_matched_update_all()
/// .when_not_matched_insert_all().execute()`: identity is `(primary_keys, partition)`,
/// matched target rows are replaced wholesale by the source row, unmatched source rows
/// insert, unmatched target rows survive verbatim, and SQL NULL semantics apply to the
/// primary keys (a NULL component never matches). The whole batch lands in ONE commit
/// carrying `opts.commit_metadata` in flat `commitInfo`.
#[instrument(
    level = "info",
    skip_all,
    fields(
        prune_strategy = opts.prune_strategy.as_str(),
        source_rows = tracing::field::Empty,
        partitions = tracing::field::Empty,
        version = tracing::field::Empty,
    )
)]
pub async fn upsert(
    table: &DeltaTable,
    source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: UpsertOptions,
) -> Result<UpsertStats> {
    let started = Instant::now();
    let strategy = opts.prune_strategy.as_str();
    let result = upsert_inner(table, source_batches, source_schema, opts).await;

    // Static label values only -- no per-call allocation (rust/CLAUDE.md).
    histogram!("deltalite_upsert_duration_seconds").record(started.elapsed().as_secs_f64());
    match &result {
        Ok(stats) => {
            counter!("deltalite_upserts_total", "outcome" => "ok", "prune_strategy" => strategy)
                .increment(1);
            counter!("deltalite_files_added_total").increment(stats.files_added as u64);
            counter!("deltalite_files_removed_total").increment(stats.files_removed as u64);
            counter!("deltalite_files_carried_over_total")
                .increment(stats.files_carried_over as u64);
            counter!("deltalite_files_probed_total").increment(stats.files_probed as u64);
            counter!("deltalite_rows_updated_total").increment(stats.rows_updated as u64);
            counter!("deltalite_rows_inserted_total").increment(stats.rows_inserted as u64);
            counter!("deltalite_rows_copied_total").increment(stats.rows_copied as u64);
        }
        Err(e) => {
            counter!(
                "deltalite_upserts_total",
                "outcome" => "error",
                "prune_strategy" => strategy,
                "error_kind" => e.kind()
            )
            .increment(1);
        }
    }
    result
}

async fn upsert_inner(
    table: &DeltaTable,
    mut source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: UpsertOptions,
) -> Result<UpsertStats> {
    if opts.primary_keys.is_empty() {
        return Err(Error::Generic(
            "primary_keys must not be empty for an upsert".into(),
        ));
    }

    let snapshot = table.snapshot()?;
    ensure_supported_table(table)?;

    // Explicit argument wins; otherwise honour the table's own `delta.targetFileSize`,
    // exactly as delta-rs's own operations do.
    let effective_target_file_size = resolve_target_file_size(
        opts.target_file_size,
        snapshot.table_config().target_file_size().get() as usize,
    );

    // Take the arrow schema from a writer built for this table: it is by construction
    // exactly the schema the writer will expect on the way back in, so casting to it
    // cannot drift from what `RecordBatchWriter` accepts.
    let table_schema: SchemaRef = RecordBatchWriter::for_table(table)?.arrow_schema();

    let extra = unknown_columns(&source_schema, &table_schema);
    if !extra.is_empty() {
        return Err(Error::SchemaMismatch(format!(
            "source has columns not present in the table schema: {extra:?}. \
             Additive schema evolution must run before upsert."
        )));
    }

    // The table's own metadata is the source of truth for partitioning, not the caller's
    // hint: a table created unpartitioned must be treated as unpartitioned even if a
    // partition_key is passed (this mirrors the helper's partition-downgrade check).
    let partition_columns: Vec<String> = snapshot.metadata().partition_columns().to_vec();
    if partition_columns.len() > 1 {
        return Err(Error::Unsupported(format!(
            "deltalite supports at most one partition column, table has {partition_columns:?}"
        )));
    }
    let partition_col: Option<String> = partition_columns.first().cloned();
    if let (Some(tbl), Some(req)) = (&partition_col, &opts.partition_key) {
        if tbl != req {
            return Err(Error::Generic(format!(
                "table is partitioned by '{tbl}' but upsert was called with partition_key '{req}'"
            )));
        }
    }

    // --- Ingest: cast each source batch to the table schema, and stop there. ---------
    //
    // The source is the one memory term that scales with caller-supplied size rather
    // than being bounded by a knob, so it is held exactly once. The batches are never
    // concatenated and never split eagerly: partition membership is planned as row
    // selections (`RowSel`, O(rows) u32 indices at worst), and each partition's worker
    // materialises its own rows only when it runs. The previous concat-then-split form
    // held the concatenated batch and every partition's slice simultaneously --
    // measured at ~3x the source; now at most `max_parallel_partitions` slices exist
    // at any moment on top of the single shared copy.
    let mut cast: Vec<RecordBatch> = Vec::with_capacity(source_batches.len());
    for b in source_batches.drain(..) {
        // `b` is dropped each iteration; when no cast is needed `cast_to_schema`
        // returns Arc-shared columns, so this does not duplicate buffers.
        cast.push(cast_to_schema(&b, &table_schema)?);
    }
    let source_rows: usize = cast.iter().map(RecordBatch::num_rows).sum();

    // --- Source-size guard: fail at the front door, not as an OOM mid-rewrite. -------
    let footprint = source_footprint(&cast, &table_schema, &opts.primary_keys)?;
    check_source_size(&footprint, resolve_max_source_bytes(opts.max_source_bytes))?;

    let batches = Arc::new(cast);
    let groups = plan_partition_sources(&batches, partition_col.as_deref())?;

    tracing::Span::current().record("source_rows", source_rows);
    tracing::Span::current().record("partitions", groups.len());
    debug!(
        source_rows,
        source_bytes = footprint.source_bytes,
        partitions = groups.len(),
        target_file_size = effective_target_file_size,
        "planned partition groups"
    );

    // Index of the first PK column in the table schema, for stats-based pruning.
    let pk0_idx = table_schema.index_of(&opts.primary_keys[0]).ok();

    let mut work = Vec::new();
    for (value, source) in groups {
        let files = list_partition_files(table, partition_col.as_deref(), &value).await?;
        // Stats-based pruning is free (the Add-action stats are already in memory), so
        // both `Stats` and `Probe` apply it; `Probe` then verifies the survivors by
        // reading their PK columns inside the partition worker.
        let (rewrite, carried) = match opts.prune_strategy {
            PruneStrategy::None => (files, 0usize),
            PruneStrategy::Stats | PruneStrategy::Probe => {
                let src_range = match pk0_idx {
                    Some(idx) => source_pk_range(&source, idx)?,
                    None => None,
                };
                prune_by_pk_stats(files, src_range.as_ref(), &opts.primary_keys)
            }
        };
        work.push(PartitionWork {
            value,
            source,
            rewrite,
            carried,
        });
    }

    // --- Rewrite (parallel across partitions) ----------------------------------------
    let partitions_touched = work.len();
    let semaphore = Arc::new(Semaphore::new(opts.max_parallel_partitions.max(1)));
    // Per-call byte budget in KiB units (tokio's acquire_many takes u32); the
    // process-global budget in `opts.limits` applies on top of it.
    let local_cap_kb: u32 = (opts.max_buffered_bytes / 1024).clamp(1, u32::MAX as usize) as u32;
    let budgets = Budgets {
        local: Arc::new(Semaphore::new(local_cap_kb as usize)),
        local_cap_kb,
        limits: opts.limits.clone(),
    };
    let opts = Arc::new(opts);
    let mut handles = Vec::new();

    for w in work {
        // Fixed acquisition order everywhere: local partition permit, then the
        // process-global one. Consistent ordering is what makes the two semaphore
        // layers deadlock-free against each other.
        let local_permit = semaphore
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| Error::Generic("partition semaphore closed".into()))?;
        let global_permit = opts.limits.acquire_partition().await?;
        let table = table.clone();
        let schema = table_schema.clone();
        let opts = opts.clone();
        let pcol = partition_col.clone();
        let budgets = budgets.clone();
        handles.push(tokio::spawn(async move {
            let r = rewrite_partition(
                &table,
                w,
                schema,
                pcol,
                &opts,
                budgets,
                effective_target_file_size,
            )
            .await;
            drop(local_permit);
            drop(global_permit);
            r
        }));
    }

    let mut stats = UpsertStats {
        partitions_touched,
        source_rows,
        ..Default::default()
    };
    let mut actions: Vec<Action> = Vec::new();

    for h in handles {
        let outcome = h
            .await
            .map_err(|e| Error::Generic(format!("partition worker panicked: {e}")))??;
        stats.files_added += outcome.files_added;
        stats.files_removed += outcome.files_removed;
        stats.files_probed += outcome.files_probed;
        stats.files_carried_over += outcome.carried;
        stats.rows_updated += outcome.rows_updated;
        stats.rows_copied += outcome.rows_copied;
        stats.rows_inserted += outcome.rows_inserted;
        stats.null_pk_rows += outcome.null_pk_rows;
        actions.extend(outcome.actions);
    }

    // --- Commit ----------------------------------------------------------------------
    let predicate = partition_col.as_ref().map(|c| {
        let vals: Vec<String> = actions
            .iter()
            .filter_map(|a| match a {
                Action::Add(add) => add.partition_values.get(c).cloned().flatten(),
                _ => None,
            })
            .collect::<HashSet<_>>()
            .into_iter()
            .map(|v| format!("'{}'", v.replace('\'', "''")))
            .collect();
        format!("{c} IN ({})", vals.join(", "))
    });

    let operation = DeltaOperation::Write {
        mode: SaveMode::Overwrite,
        partition_by: if partition_columns.is_empty() {
            None
        } else {
            Some(partition_columns.clone())
        },
        predicate,
    };

    let mut props = CommitProperties::default().with_max_retries(opts.commit_max_retries);
    if let Some(md) = opts.commit_metadata.clone() {
        props = props.with_metadata(md);
    }

    let finalized = CommitBuilder::from(props)
        .with_actions(actions)
        .build(Some(snapshot), table.log_store(), operation)
        .await?;

    stats.version = i64::try_from(finalized.version())
        .map_err(|_| Error::Generic("committed version overflows i64".into()))?;
    tracing::Span::current().record("version", stats.version);
    info!(
        version = stats.version,
        partitions = stats.partitions_touched,
        files_added = stats.files_added,
        files_removed = stats.files_removed,
        files_carried_over = stats.files_carried_over,
        rows_updated = stats.rows_updated,
        rows_inserted = stats.rows_inserted,
        rows_copied = stats.rows_copied,
        "upsert committed"
    );
    Ok(stats)
}

/// Explicit argument > table property (already folded with delta-rs's default by the
/// caller). Zero/absent explicit values fall through to the table's value.
fn resolve_target_file_size(explicit: Option<usize>, table_value: usize) -> usize {
    match explicit {
        Some(v) if v > 0 => v,
        _ => table_value,
    }
}

/// Estimate what this upsert keeps resident: the cast source batches plus the PK set
/// that will be built over them.
fn source_footprint(
    batches: &[RecordBatch],
    table_schema: &SchemaRef,
    primary_keys: &[String],
) -> Result<SourceFootprint> {
    let source_bytes: usize = batches.iter().map(RecordBatch::get_array_memory_size).sum();
    let rows: usize = batches.iter().map(RecordBatch::num_rows).sum();
    let mut pk_bytes = 0usize;
    for pk in primary_keys {
        let idx = table_schema.index_of(pk).map_err(|_| {
            Error::SchemaMismatch(format!(
                "primary key column '{pk}' not found in table schema"
            ))
        })?;
        pk_bytes += batches
            .iter()
            .map(|b| b.column(idx).get_array_memory_size())
            .sum::<usize>();
    }
    Ok(SourceFootprint {
        source_bytes,
        pk_set_bytes: estimate_pk_set_bytes(pk_bytes, rows),
    })
}

/// Refuse tables whose features would make a blind file rewrite unsafe.
fn ensure_supported_table(table: &DeltaTable) -> Result<()> {
    let snapshot = table.snapshot()?;
    let protocol = snapshot.protocol();

    let has = |feats: Option<&[String]>, name: &str| {
        feats.map(|f| f.iter().any(|x| x == name)).unwrap_or(false)
    };
    let reader: Option<Vec<String>> = protocol
        .reader_features()
        .map(|f| f.iter().map(|x| x.to_string()).collect());
    let writer: Option<Vec<String>> = protocol
        .writer_features()
        .map(|f| f.iter().map(|x| x.to_string()).collect());

    for (kind, feats) in [("reader", &reader), ("writer", &writer)] {
        let slice = feats.as_deref();
        for bad in ["deletionVectors", "columnMapping"] {
            if has(slice, bad) {
                return Err(Error::Unsupported(format!(
                    "table declares {kind} feature '{bad}', which deltalite cannot safely \
                     rewrite (a blind file rewrite would resurrect deleted rows or write \
                     wrongly-named columns)"
                )));
            }
        }
    }

    if snapshot
        .metadata()
        .configuration()
        .get("delta.enableDeletionVectors")
        .map(|v| v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        return Err(Error::Unsupported(
            "table has delta.enableDeletionVectors=true; deltalite cannot safely rewrite it".into(),
        ));
    }

    // Legacy column mapping (minReaderVersion=2/minWriterVersion=5, as Spark writes it)
    // carries no reader/writer *feature* list, so the check above cannot see it. Without
    // this, such a table only fails later inside `RecordBatchWriter::for_table` with a
    // generic error -- safe, but by luck rather than by design.
    if let Some(mode) = snapshot
        .metadata()
        .configuration()
        .get("delta.columnMapping.mode")
    {
        if !mode.eq_ignore_ascii_case("none") {
            return Err(Error::Unsupported(format!(
                "table has delta.columnMapping.mode={mode}; deltalite cannot safely rewrite \
                 it (physical column names differ from logical ones)"
            )));
        }
    }
    Ok(())
}

/// Plan which rows of which source batches belong to each distinct partition value,
/// without copying any row data. Returns groups in first-seen order (scanning batches
/// in order, rows in order), the same deterministic order the eager split produced.
///
/// Partition values are compared as their Delta string representation, which is what the
/// log stores and what the writer uses to build the Hive path. NULL partition values are
/// rejected here, before any worker starts.
fn plan_partition_sources(
    batches: &Arc<Vec<RecordBatch>>,
    partition_col: Option<&str>,
) -> Result<Vec<(String, PartitionSource)>> {
    let n_batches = batches.len();
    let total_rows: usize = batches.iter().map(RecordBatch::num_rows).sum();

    let Some(col) = partition_col else {
        // Unpartitioned: one group covering every row of every batch, zero-copy.
        return Ok(vec![(
            WHOLE_TABLE.to_string(),
            PartitionSource {
                batches: batches.clone(),
                sel: (0..n_batches).map(|_| RowSel::All).collect(),
                rows: total_rows,
            },
        )]);
    };

    // Preserve first-seen order for deterministic behaviour.
    let mut order: Vec<String> = Vec::new();
    // partition value -> per-batch ascending row indices.
    let mut indices: HashMap<String, Vec<Vec<u32>>> = HashMap::new();
    let mut row_base = 0usize;

    for (bi, batch) in batches.iter().enumerate() {
        if batch.num_rows() > u32::MAX as usize {
            return Err(Error::Generic(format!(
                "source batch has {} rows, more than a single batch supports",
                batch.num_rows()
            )));
        }
        let idx = batch.schema().index_of(col).map_err(|_| {
            Error::SchemaMismatch(format!(
                "partition column '{col}' is missing from the incoming batch"
            ))
        })?;
        let as_str = arrow_cast::cast(batch.column(idx), &DataType::Utf8)?;
        let as_str = as_str
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(|| Error::Generic("partition column did not cast to Utf8".into()))?;

        for i in 0..batch.num_rows() {
            if as_str.is_null(i) {
                return Err(Error::Generic(format!(
                    "partition column '{col}' contains NULL at row {}; \
                     Delta partition values must not be null",
                    row_base + i
                )));
            }
            let v = as_str.value(i);
            if !indices.contains_key(v) {
                order.push(v.to_string());
                indices.insert(v.to_string(), vec![Vec::new(); n_batches]);
            }
            // The key was just inserted if absent, so this lookup cannot fail.
            if let Some(per_batch) = indices.get_mut(v) {
                per_batch[bi].push(i as u32);
            }
        }
        row_base += batch.num_rows();
    }

    let mut out = Vec::with_capacity(order.len());
    for v in order {
        let per_batch = indices.remove(&v).ok_or_else(|| {
            Error::Generic("internal: partition index vanished during planning".into())
        })?;
        let rows: usize = per_batch.iter().map(Vec::len).sum();
        let sel: Vec<RowSel> = per_batch
            .into_iter()
            .zip(batches.iter())
            .map(|(idx, b)| RowSel::from_indices(idx, b.num_rows()))
            .collect();
        out.push((
            v,
            PartitionSource {
                batches: batches.clone(),
                sel,
                rows,
            },
        ));
    }
    Ok(out)
}

/// Min/max of the partition's selected rows of one column, as JSON values comparable
/// against Add-action stats. Only the selected rows of the (narrow) PK column are ever
/// materialised, and only transiently.
fn source_pk_range(source: &PartitionSource, col_idx: usize) -> Result<Option<(Value, Value)>> {
    let mut acc: Option<(Value, Value)> = None;
    for chunk in source.select_column(col_idx)? {
        if let Some((mn, mx)) = min_max_json(chunk.as_ref()) {
            acc = Some(match acc {
                None => (mn, mx),
                Some((amn, amx)) => (
                    if matches!(json_cmp(&mn, &amn), Some(std::cmp::Ordering::Less)) {
                        mn
                    } else {
                        amn
                    },
                    if matches!(json_cmp(&mx, &amx), Some(std::cmp::Ordering::Greater)) {
                        mx
                    } else {
                        amx
                    },
                ),
            });
        }
    }
    Ok(acc)
}

async fn list_partition_files(
    table: &DeltaTable,
    partition_col: Option<&str>,
    value: &str,
) -> Result<Vec<TargetFile>> {
    let filters = match partition_col {
        Some(c) => vec![PartitionFilter {
            key: c.to_string(),
            value: PartitionValue::Equal(value.to_string()),
        }],
        None => vec![],
    };

    let views: Vec<_> = table
        .get_active_add_actions_by_partitions(&filters)
        .try_collect()
        .await?;

    Ok(views
        .into_iter()
        .map(|v| TargetFile {
            path: v.path().to_string(),
            size: v.size() as u64,
            stats: v.stats(),
            remove: v.remove_action(true),
        })
        .collect())
}

/// Drop files whose Add-action stats prove they hold no match: min/max disjointness on
/// the first PK column, or a PK column that is entirely NULL in the file (SQL NULL never
/// matches, so such a file cannot contain a matched row). Both checks are exact
/// negatives; anything unprovable stays in the rewrite set. Returns (files to rewrite,
/// count carried over untouched).
fn prune_by_pk_stats(
    files: Vec<TargetFile>,
    src_range: Option<&(Value, Value)>,
    primary_keys: &[String],
) -> (Vec<TargetFile>, usize) {
    let mut rewrite = Vec::with_capacity(files.len());
    let mut carried = 0usize;
    for f in files {
        if file_cannot_match(&f, primary_keys, src_range) {
            carried += 1;
        } else {
            rewrite.push(f);
        }
    }
    (rewrite, carried)
}

fn file_cannot_match(
    f: &TargetFile,
    primary_keys: &[String],
    src_range: Option<&(Value, Value)>,
) -> bool {
    let Some(stats) = &f.stats else { return false };
    let Ok(parsed): std::result::Result<Value, _> = serde_json::from_str(stats) else {
        return false;
    };

    // A PK column that is NULL in every row of the file (e.g. it was added by schema
    // evolution after the file was written) means no row of the file can match.
    if let Some(n) = parsed.get("numRecords").and_then(Value::as_i64) {
        if n == 0 {
            return true;
        }
        if let Some(nulls) = parsed.get("nullCount") {
            for pk in primary_keys {
                if nulls.get(pk).and_then(Value::as_i64) == Some(n) {
                    return true;
                }
            }
        }
    }

    let pk0 = &primary_keys[0];
    let Some((src_min, src_max)) = src_range else {
        return false;
    };
    let fmin = parsed.get("minValues").and_then(|m| m.get(pk0));
    let fmax = parsed.get("maxValues").and_then(|m| m.get(pk0));
    let (Some(fmin), Some(fmax)) = (fmin, fmax) else {
        return false;
    };
    // file_max < src_min  ||  file_min > src_max
    matches!(json_cmp(fmax, src_min), Some(std::cmp::Ordering::Less))
        || matches!(json_cmp(fmin, src_max), Some(std::cmp::Ordering::Greater))
}

fn json_cmp(a: &Value, b: &Value) -> Option<std::cmp::Ordering> {
    match (a, b) {
        (Value::String(x), Value::String(y)) => Some(x.cmp(y)),
        (Value::Number(x), Value::Number(y)) => x.as_f64()?.partial_cmp(&y.as_f64()?),
        _ => None,
    }
}

fn min_max_json(col: &dyn Array) -> Option<(Value, Value)> {
    use arrow_array::cast::AsArray;
    use arrow_array::types::*;

    macro_rules! num {
        ($t:ty) => {{
            let a = col.as_primitive::<$t>();
            let mut mn = None;
            let mut mx = None;
            for i in 0..a.len() {
                if a.is_null(i) {
                    continue;
                }
                let v = a.value(i);
                mn = Some(mn.map_or(
                    v,
                    |m: <$t as ArrowPrimitiveType>::Native| {
                        if v < m {
                            v
                        } else {
                            m
                        }
                    },
                ));
                mx = Some(mx.map_or(
                    v,
                    |m: <$t as ArrowPrimitiveType>::Native| {
                        if v > m {
                            v
                        } else {
                            m
                        }
                    },
                ));
            }
            match (mn, mx) {
                (Some(a), Some(b)) => Some((
                    Value::Number(serde_json::Number::from(i64::from(a))),
                    Value::Number(serde_json::Number::from(i64::from(b))),
                )),
                _ => None,
            }
        }};
    }

    match col.data_type() {
        DataType::Utf8 => {
            let a = col.as_string::<i32>();
            let mut mn: Option<&str> = None;
            let mut mx: Option<&str> = None;
            for i in 0..a.len() {
                if a.is_null(i) {
                    continue;
                }
                let v = a.value(i);
                mn = Some(mn.map_or(v, |m| if v < m { v } else { m }));
                mx = Some(mx.map_or(v, |m| if v > m { v } else { m }));
            }
            match (mn, mx) {
                (Some(a), Some(b)) => {
                    Some((Value::String(a.to_string()), Value::String(b.to_string())))
                }
                _ => None,
            }
        }
        DataType::Int64 => num!(Int64Type),
        DataType::Int32 => num!(Int32Type),
        DataType::Int16 => num!(Int16Type),
        DataType::Int8 => num!(Int8Type),
        _ => None,
    }
}

/// Append a constant partition column to a batch read from a data file.
///
/// Delta stores partition columns in the path, not in the Parquet file, so a row group
/// read back from storage is missing the column that the writer needs in order to route
/// the rows back to the same partition. Getting this wrong would silently misroute
/// rewritten rows.
fn add_partition_column(batch: &RecordBatch, name: &str, value: &str) -> Result<RecordBatch> {
    let n = batch.num_rows();
    let arr: Arc<dyn Array> = Arc::new(StringArray::from(vec![value; n]));
    let mut fields: Vec<Field> = batch
        .schema()
        .fields()
        .iter()
        .map(|f| f.as_ref().clone())
        .collect();
    fields.push(Field::new(name, DataType::Utf8, false));
    let mut cols = batch.columns().to_vec();
    cols.push(arr);
    Ok(RecordBatch::try_new(Arc::new(Schema::new(fields)), cols)?)
}

/// Where one PK column of a candidate file comes from during the probe.
enum PkSource {
    /// Physically present in the Parquet file; read via projection pushdown.
    Physical,
    /// The partition column: not stored in the data file, constant for every row.
    PartitionConst,
}

/// Assemble the PK columns (in PK order, cast to the table schema's PK types) for a
/// probe batch. `batch` is `None` only in the all-`PartitionConst` case.
fn build_pk_columns(
    primary_keys: &[String],
    sources: &[PkSource],
    batch: Option<&RecordBatch>,
    num_rows: usize,
    partition_value: &str,
    pk_types: &[DataType],
) -> Result<Vec<Arc<dyn Array>>> {
    let cast_opts = CastOptions {
        safe: false,
        ..Default::default()
    };
    let mut cols: Vec<Arc<dyn Array>> = Vec::with_capacity(primary_keys.len());
    for (i, src) in sources.iter().enumerate() {
        let raw: Arc<dyn Array> = match src {
            PkSource::Physical => batch
                .and_then(|b| b.column_by_name(&primary_keys[i]))
                .cloned()
                .ok_or_else(|| {
                    Error::Generic(format!(
                        "probe projection lost PK column '{}'",
                        primary_keys[i]
                    ))
                })?,
            PkSource::PartitionConst => {
                Arc::new(StringArray::from(vec![partition_value; num_rows]))
            }
        };
        cols.push(if raw.data_type() == &pk_types[i] {
            raw
        } else {
            cast_with_options(&raw, &pk_types[i], &cast_opts)?
        });
    }
    Ok(cols)
}

/// Read ONLY the PK column(s) of `f` and return whether any row matches the source PK
/// set. Streams one projected batch at a time and short-circuits on the first hit, so
/// resident memory is a Parquet footer plus one narrow batch.
///
/// Exactness of the negative answer is what licenses skipping the file: a PK column
/// absent from the file reads as all-NULL, and SQL NULL never matches, so such a file
/// is an exact negative without any I/O beyond the footer.
async fn probe_file(
    store: &Arc<dyn ObjectStore>,
    f: &TargetFile,
    pkset: &PkSet,
    table_schema: &SchemaRef,
    partition_col: &Option<String>,
    partition_value: &str,
    opts: &UpsertOptions,
) -> Result<bool> {
    let path = Path::parse(&f.path)
        .map_err(|e| Error::Generic(format!("bad data file path {:?}: {e}", f.path)))?;
    let reader = ParquetObjectReader::new(store.clone(), path).with_file_size(f.size);
    let builder = ParquetRecordBatchStreamBuilder::new(reader).await?;
    let file_schema = builder.schema().clone();

    let mut pk_types: Vec<DataType> = Vec::with_capacity(opts.primary_keys.len());
    for pk in &opts.primary_keys {
        pk_types.push(
            table_schema
                .field_with_name(pk)
                .map_err(|e| Error::Generic(format!("PK column lookup: {e}")))?
                .data_type()
                .clone(),
        );
    }

    let mut sources: Vec<PkSource> = Vec::with_capacity(opts.primary_keys.len());
    let mut projection: Vec<usize> = Vec::new();
    for pk in &opts.primary_keys {
        if let Ok(idx) = file_schema.index_of(pk) {
            projection.push(idx);
            sources.push(PkSource::Physical);
        } else if partition_col.as_deref() == Some(pk.as_str()) {
            sources.push(PkSource::PartitionConst);
        } else {
            // The column is physically absent (file predates schema evolution): every
            // row has NULL for this PK component, and NULL never matches.
            return Ok(false);
        }
    }

    if projection.is_empty() {
        // Every PK component is the partition constant: all rows share one PK tuple, so
        // one synthetic row decides the whole file.
        let cols = build_pk_columns(
            &opts.primary_keys,
            &sources,
            None,
            1,
            partition_value,
            &pk_types,
        )?;
        return pkset.contains_any_columns(&cols, 1);
    }

    let mask = ProjectionMask::roots(builder.parquet_schema(), projection);
    let mut stream = builder
        .with_projection(mask)
        .with_batch_size(opts.read_batch_size)
        .build()?;

    while let Some(batch) = stream.try_next().await? {
        let cols = build_pk_columns(
            &opts.primary_keys,
            &sources,
            Some(&batch),
            batch.num_rows(),
            partition_value,
            &pk_types,
        )?;
        if pkset.contains_any_columns(&cols, batch.num_rows())? {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Probe `files` with bounded concurrency, splitting them into (files that contain at
/// least one match, count of files proven match-free). Order is preserved.
async fn probe_files(
    store: &Arc<dyn ObjectStore>,
    files: Vec<TargetFile>,
    pkset: &PkSet,
    table_schema: &SchemaRef,
    partition_col: &Option<String>,
    partition_value: &str,
    opts: &UpsertOptions,
) -> Result<(Vec<TargetFile>, usize)> {
    let results: Vec<(TargetFile, bool)> = futures::stream::iter(files.into_iter().map(|f| {
        let store = store.clone();
        async move {
            let hit = probe_file(
                &store,
                &f,
                pkset,
                table_schema,
                partition_col,
                partition_value,
                opts,
            )
            .await?;
            Ok::<_, Error>((f, hit))
        }
    }))
    .buffered(opts.probe_concurrency.max(1))
    .try_collect()
    .await?;

    let mut keep = Vec::new();
    let mut skipped = 0usize;
    for (f, hit) in results {
        if hit {
            keep.push(f);
        } else {
            skipped += 1;
        }
    }
    Ok((keep, skipped))
}

/// Per-file result from a reader task.
struct FileOutcome {
    rows_updated: usize,
    rows_copied: usize,
    remove: Action,
}

/// Stream one existing file, drop replaced rows, and send surviving batches to the
/// partition's writer task. Every batch sent carries byte-budget permits acquired
/// *before* the send; the writer releases them only after `write()` has copied the
/// batch into its buffer, so queued + in-write survivor data across the whole process
/// never exceeds the budgets.
#[allow(clippy::too_many_arguments)]
async fn filter_file(
    store: Arc<dyn ObjectStore>,
    f: TargetFile,
    pkset: Arc<PkSet>,
    table_schema: SchemaRef,
    partition_col: Option<String>,
    partition_value: String,
    opts: Arc<UpsertOptions>,
    budgets: Budgets,
    tx: mpsc::UnboundedSender<(RecordBatch, BudgetPermit)>,
) -> Result<FileOutcome> {
    let path = Path::parse(&f.path)
        .map_err(|e| Error::Generic(format!("bad data file path {:?}: {e}", f.path)))?;
    let reader = ParquetObjectReader::new(store, path).with_file_size(f.size);
    let builder = ParquetRecordBatchStreamBuilder::new(reader)
        .await?
        .with_batch_size(opts.read_batch_size);
    let mut stream = builder.build()?;

    let mut rows_updated = 0usize;
    let mut rows_copied = 0usize;

    while let Some(batch) = stream.try_next().await? {
        // Budget the decoded batch *immediately*: without this, every concurrent
        // reader holds an unaccounted row group through probe/filter and the knob
        // product (partitions x files x concurrent upserts) multiplies resident
        // memory. The permits ride with the data through probe, filter, and the
        // writer queue, and are released by the writer only after write(); a reader
        // that cannot get budget parks here, before doing any further allocation.
        let permit = budgets.acquire_bytes(batch.get_array_memory_size()).await?;

        // Old files may predate a column addition, and never carry the partition
        // column; restore both before probing so PK encodings line up.
        let batch = match (&partition_col, partition_value.as_str()) {
            (Some(c), v) => add_partition_column(&batch, c, v)?,
            _ => batch,
        };
        let batch = cast_to_schema(&batch, &table_schema)?;

        let hits = pkset.contains_rows(&batch)?;
        let n_hits = hits.iter().filter(|h| **h).count();
        rows_updated += n_hits;

        if n_hits == batch.num_rows() {
            continue; // every row replaced; permits drop here and free their budget
        }
        let keep: arrow_array::BooleanArray = hits.iter().map(|h| Some(!*h)).collect();
        let survivors = filter_record_batch(&batch, &keep)?;
        rows_copied += survivors.num_rows();

        tx.send((survivors, permit))
            .map_err(|_| Error::Generic("writer task ended before its readers".into()))?;
    }

    Ok(FileOutcome {
        rows_updated,
        rows_copied,
        remove: Action::Remove(f.remove),
    })
}

async fn rewrite_partition(
    table: &DeltaTable,
    work: PartitionWork,
    table_schema: SchemaRef,
    partition_col: Option<String>,
    opts: &Arc<UpsertOptions>,
    budgets: Budgets,
    target_file_size: usize,
) -> Result<PartitionOutcome> {
    let PartitionWork {
        value,
        source,
        mut rewrite,
        mut carried,
    } = work;

    // Build the PK set from the partition's source rows without materialising the
    // full-width slice: only the (narrow) PK columns are selected, per source batch,
    // and dropped as soon as they are encoded into the set. Duplicate detection is
    // unchanged -- the set persists across sub-batches, so a duplicate anywhere in the
    // partition's rows still fires.
    let mut pkset = PkSet::new(&table_schema, &opts.primary_keys)?;
    {
        let mut pk_idx: Vec<usize> = Vec::with_capacity(opts.primary_keys.len());
        for pk in &opts.primary_keys {
            pk_idx.push(table_schema.index_of(pk).map_err(|_| {
                Error::SchemaMismatch(format!(
                    "primary key column '{pk}' not found in table schema"
                ))
            })?);
        }
        let mut duplicates = 0usize;
        for (b, sel) in source.batches.iter().zip(&source.sel) {
            let n = sel.len(b.num_rows());
            if n == 0 {
                continue;
            }
            let mut cols: Vec<Arc<dyn Array>> = Vec::with_capacity(pk_idx.len());
            for &ci in &pk_idx {
                cols.push(sel.select_array(b.column(ci))?);
            }
            duplicates += pkset.insert_columns(&cols, n)?;
        }
        if duplicates > 0 {
            // Stricter than MERGE on purpose: MERGE errors on duplicates that match an
            // existing row but silently double-inserts ones that do not, breaking PK
            // uniqueness. Refusing here leaves the table byte-identical.
            return Err(Error::Generic(format!(
                "source batch contains {duplicates} duplicate primary-key tuple(s) in partition \
                 '{value}'; the batch must be deduped keep-last before upsert"
            )));
        }
    }
    let null_pk_rows = pkset.null_pk_rows;
    // Insert phase done; from here the set is read-only and shared by every reader.
    let pkset = Arc::new(pkset);

    let writer = RecordBatchWriter::for_table(table)?;
    let store: Arc<dyn ObjectStore> = table.object_store();

    // Content-based file selection: keep only files that actually contain a matched
    // row, exactly as MERGE's join does. Files proven match-free are carried over --
    // neither read again, rewritten, nor tombstoned.
    let mut files_probed = 0usize;
    if opts.prune_strategy == PruneStrategy::Probe && !rewrite.is_empty() {
        if pkset.is_empty() {
            // Every source row has a NULL PK component: nothing can match, so every
            // file is an exact negative without reading anything.
            carried += rewrite.len();
            rewrite = Vec::new();
        } else {
            files_probed = rewrite.len();
            let (keep, skipped) = probe_files(
                &store,
                rewrite,
                &pkset,
                &table_schema,
                &partition_col,
                &value,
                opts,
            )
            .await?;
            rewrite = keep;
            carried += skipped;
        }
    }

    // Single writer task per partition: file count and output sizing behave exactly as
    // in the sequential implementation. The channel is unbounded; memory is bounded by
    // the byte-budget permits attached to every message, not by message count.
    let (tx, mut rx) = mpsc::unbounded_channel::<(RecordBatch, BudgetPermit)>();
    let writer_task = tokio::spawn(async move {
        let mut writer = writer;
        let mut adds = Vec::new();
        while let Some((batch, permit)) = rx.recv().await {
            writer.write(batch).await?;
            // The batch now lives (compressed) in the write buffer; release its budget.
            drop(permit);

            // Bound resident memory: RecordBatchWriter buffers the whole partition as
            // compressed Parquet until flushed, so flush on a size threshold instead of
            // once at the end. Each flush yields Add actions and resets the buffer.
            if writer.buffer_len() >= target_file_size {
                adds.extend(writer.flush().await?);
            }
        }
        Ok::<_, Error>((writer, adds))
    });

    // Reader tasks: up to max_parallel_files files stream concurrently (per call AND
    // per process). Each task takes its concurrency permits *inside* the task so
    // spawning never blocks this function.
    let file_sem = Arc::new(Semaphore::new(opts.max_parallel_files.max(1)));
    let mut readers = Vec::with_capacity(rewrite.len());
    for f in rewrite {
        let sem = file_sem.clone();
        let store = store.clone();
        let pkset = pkset.clone();
        let schema = table_schema.clone();
        let pcol = partition_col.clone();
        let value = value.clone();
        let opts = opts.clone();
        let budgets = budgets.clone();
        let tx = tx.clone();
        readers.push(tokio::spawn(async move {
            // Local before global, matching the fixed order used for partitions.
            let _local = sem
                .acquire_owned()
                .await
                .map_err(|_| Error::Generic("file semaphore closed".into()))?;
            let _global = opts.limits.acquire_file().await?;
            filter_file(store, f, pkset, schema, pcol, value, opts, budgets, tx).await
        }));
    }
    // Drop the parent's sender so the writer task ends when the readers do.
    drop(tx);

    let mut rows_updated = 0usize;
    let mut rows_copied = 0usize;
    let mut removes: Vec<Action> = Vec::new();
    let mut reader_err: Option<Error> = None;
    for h in readers {
        match h
            .await
            .map_err(|e| Error::Generic(format!("file worker panicked: {e}")))?
        {
            Ok(o) => {
                rows_updated += o.rows_updated;
                rows_copied += o.rows_copied;
                removes.push(o.remove);
            }
            // Keep the first reader error, but keep draining so the writer terminates.
            Err(e) => reader_err = reader_err.or(Some(e)),
        }
    }

    // Writer errors take precedence: when the writer dies, readers fail secondarily on
    // send, and reporting those would mask the root cause.
    let (mut writer, mut adds) = writer_task
        .await
        .map_err(|e| Error::Generic(format!("writer task panicked: {e}")))??;
    if let Some(e) = reader_err {
        return Err(e);
    }

    // Source rows are written LAST: an updated row therefore carries the source values,
    // which is exactly `when_matched_update_all`. The ordering is semantic, not
    // stylistic. Each sub-batch's slice is materialised here, inside the worker (so at
    // most `max_parallel_partitions` slices exist at once), and dropped as soon as
    // `write` has copied it into the compressed buffer. Sub-batches are written in
    // batch order and rows in ascending order within each, preserving exactly the row
    // order the eager concat-then-split produced.
    for (b, sel) in source.batches.iter().zip(&source.sel) {
        if sel.len(b.num_rows()) == 0 {
            continue;
        }
        // Written in row slices (zero-copy) rather than one call, so the threshold can
        // be checked *between* slices. The survivor loop above only ever sees survivors,
        // so a batch matching every target row never passes through it; without this a
        // large source produced one oversized file and an unbounded write buffer.
        // Flushing mid-source is order-safe: it closes the current file and opens
        // another, and every source row still lands after every survivor.
        let selected = sel.select_batch(b)?;
        let mut offset = 0usize;
        while offset < selected.num_rows() {
            let n = (selected.num_rows() - offset).min(opts.read_batch_size.max(1));
            writer.write(selected.slice(offset, n)).await?;
            offset += n;
            if writer.buffer_len() >= target_file_size {
                adds.extend(writer.flush().await?);
            }
        }
    }
    adds.extend(writer.flush().await?);

    // Every source row is written, but a source row that replaced an existing one is an
    // update, not an insert -- the batch is deduped, so each match consumes exactly one
    // source row. Counting the whole slice here double-counted matches as both.
    let rows_inserted = source.rows.saturating_sub(rows_updated);
    let files_added = adds.len();
    let files_removed = removes.len();

    let mut actions: Vec<Action> = removes;
    actions.extend(adds.into_iter().map(Action::Add));

    Ok(PartitionOutcome {
        actions,
        files_added,
        files_removed,
        files_probed,
        rows_updated,
        rows_copied,
        rows_inserted,
        null_pk_rows,
        carried,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- PruneStrategy parsing -------------------------------------------------------

    #[test]
    fn prune_strategy_parses_case_insensitively_and_rejects_unknown() {
        assert_eq!(
            "none".parse::<PruneStrategy>().unwrap(),
            PruneStrategy::None
        );
        assert_eq!(
            "STATS".parse::<PruneStrategy>().unwrap(),
            PruneStrategy::Stats
        );
        assert_eq!(
            "Probe".parse::<PruneStrategy>().unwrap(),
            PruneStrategy::Probe
        );
        assert!("join".parse::<PruneStrategy>().is_err());
        assert_eq!(PruneStrategy::default(), PruneStrategy::Probe);
    }

    // ---- target_file_size resolution -------------------------------------------------

    #[test]
    fn explicit_target_file_size_wins_and_zero_falls_through() {
        assert_eq!(resolve_target_file_size(Some(42), 100), 42);
        assert_eq!(resolve_target_file_size(Some(0), 100), 100);
        assert_eq!(resolve_target_file_size(None, 100), 100);
    }

    // ---- RowSel ----------------------------------------------------------------------

    use arrow_array::Int64Array;
    use arrow_schema::Field as AField;

    fn int_batch(vals: &[i64]) -> RecordBatch {
        RecordBatch::try_new(
            Arc::new(Schema::new(vec![AField::new("v", DataType::Int64, false)])),
            vec![Arc::new(Int64Array::from(vals.to_vec()))],
        )
        .unwrap()
    }

    #[test]
    fn rowsel_all_range_and_indices_are_detected() {
        assert!(matches!(
            RowSel::from_indices(vec![0, 1, 2], 3),
            RowSel::All
        ));
        assert!(matches!(
            RowSel::from_indices(vec![2, 3, 4], 6),
            RowSel::Range { offset: 2, len: 3 }
        ));
        assert!(matches!(
            RowSel::from_indices(vec![0, 2], 3),
            RowSel::Indices(_)
        ));
        assert!(matches!(
            RowSel::from_indices(vec![], 3),
            RowSel::Indices(_)
        ));
    }

    #[test]
    fn rowsel_select_batch_matches_selection() {
        let b = int_batch(&[10, 20, 30, 40]);
        let all = RowSel::from_indices(vec![0, 1, 2, 3], 4)
            .select_batch(&b)
            .unwrap();
        assert_eq!(all.num_rows(), 4);
        let range = RowSel::from_indices(vec![1, 2], 4)
            .select_batch(&b)
            .unwrap();
        let col = range
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        assert_eq!(col.values(), &[20, 30]);
        let scattered = RowSel::from_indices(vec![0, 3], 4)
            .select_batch(&b)
            .unwrap();
        let col = scattered
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        assert_eq!(col.values(), &[10, 40]);
    }

    // ---- partition planning ----------------------------------------------------------

    fn part_batch(parts: &[&str]) -> RecordBatch {
        RecordBatch::try_new(
            Arc::new(Schema::new(vec![
                AField::new("p", DataType::Utf8, true),
                AField::new("v", DataType::Int64, false),
            ])),
            vec![
                Arc::new(StringArray::from(parts.to_vec())),
                Arc::new(Int64Array::from(
                    (0..parts.len() as i64).collect::<Vec<_>>(),
                )),
            ],
        )
        .unwrap()
    }

    #[test]
    fn plan_groups_in_first_seen_order_with_correct_rows() {
        let batches = Arc::new(vec![part_batch(&["b", "a", "b"]), part_batch(&["a"])]);
        let groups = plan_partition_sources(&batches, Some("p")).unwrap();
        let names: Vec<_> = groups.iter().map(|(v, _)| v.as_str()).collect();
        assert_eq!(names, vec!["b", "a"]);
        let rows: Vec<_> = groups.iter().map(|(_, s)| s.rows).collect();
        assert_eq!(rows, vec![2, 2]);
    }

    #[test]
    fn plan_unpartitioned_is_one_zero_copy_group() {
        let batches = Arc::new(vec![part_batch(&["x", "y"])]);
        let groups = plan_partition_sources(&batches, None).unwrap();
        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].0, WHOLE_TABLE);
        assert_eq!(groups[0].1.rows, 2);
        assert!(matches!(groups[0].1.sel[0], RowSel::All));
    }

    #[test]
    fn plan_rejects_null_partition_values() {
        let b = RecordBatch::try_new(
            Arc::new(Schema::new(vec![AField::new("p", DataType::Utf8, true)])),
            vec![Arc::new(StringArray::from(vec![Some("a"), None]))],
        )
        .unwrap();
        let err = plan_partition_sources(&Arc::new(vec![b]), Some("p")).unwrap_err();
        assert!(err.to_string().contains("NULL"), "{err}");
    }

    #[test]
    fn plan_rejects_missing_partition_column() {
        let batches = Arc::new(vec![int_batch(&[1])]);
        let err = plan_partition_sources(&batches, Some("p")).unwrap_err();
        assert!(matches!(err, Error::SchemaMismatch(_)), "{err}");
    }

    // ---- stats-based pruning ---------------------------------------------------------

    fn target_file(stats: Option<&str>) -> TargetFile {
        TargetFile {
            path: "part-0.parquet".into(),
            size: 1,
            stats: stats.map(|s| s.to_string()),
            remove: Remove::default(),
        }
    }

    fn pk() -> Vec<String> {
        vec!["id".to_string()]
    }

    #[test]
    fn file_without_stats_is_never_pruned() {
        let range = (Value::String("a".into()), Value::String("z".into()));
        assert!(!file_cannot_match(&target_file(None), &pk(), Some(&range)));
    }

    #[test]
    fn disjoint_minmax_range_is_pruned_overlap_is_not() {
        let stats = r#"{"numRecords": 5, "minValues": {"id": "a"}, "maxValues": {"id": "c"}}"#;
        let f = target_file(Some(stats));
        let disjoint = (Value::String("d".into()), Value::String("f".into()));
        assert!(file_cannot_match(&f, &pk(), Some(&disjoint)));
        let overlap = (Value::String("b".into()), Value::String("f".into()));
        assert!(!file_cannot_match(&f, &pk(), Some(&overlap)));
        // No source range at all: cannot prove anything.
        assert!(!file_cannot_match(&f, &pk(), None));
    }

    #[test]
    fn all_null_pk_column_is_an_exact_negative() {
        // PK column added by schema evolution after this file was written: every row
        // reads NULL, and SQL NULL never matches.
        let stats = r#"{"numRecords": 7, "nullCount": {"id": 7}}"#;
        let f = target_file(Some(stats));
        let range = (Value::String("a".into()), Value::String("z".into()));
        assert!(file_cannot_match(&f, &pk(), Some(&range)));
        // Partially-null PK column proves nothing.
        let stats = r#"{"numRecords": 7, "nullCount": {"id": 6}}"#;
        assert!(!file_cannot_match(
            &target_file(Some(stats)),
            &pk(),
            Some(&range)
        ));
    }

    #[test]
    fn empty_file_is_pruned_and_malformed_stats_are_kept() {
        let range = (Value::String("a".into()), Value::String("z".into()));
        let empty = target_file(Some(r#"{"numRecords": 0}"#));
        assert!(file_cannot_match(&empty, &pk(), Some(&range)));
        let broken = target_file(Some("not json"));
        assert!(!file_cannot_match(&broken, &pk(), Some(&range)));
    }

    #[test]
    fn numeric_stats_compare_numerically_not_lexically() {
        let stats = r#"{"numRecords": 2, "minValues": {"id": 9}, "maxValues": {"id": 11}}"#;
        let f = target_file(Some(stats));
        // Lexically "11" < "9"; numerically the file range [9, 11] overlaps [10, 10].
        let range = (Value::Number(10.into()), Value::Number(10.into()));
        assert!(!file_cannot_match(&f, &pk(), Some(&range)));
        let range = (Value::Number(12.into()), Value::Number(20.into()));
        assert!(file_cannot_match(&f, &pk(), Some(&range)));
    }

    #[test]
    fn prune_by_pk_stats_partitions_files() {
        let range = (Value::String("a".into()), Value::String("b".into()));
        let keep = target_file(Some(
            r#"{"numRecords": 5, "minValues": {"id": "a"}, "maxValues": {"id": "z"}}"#,
        ));
        let skip = target_file(Some(
            r#"{"numRecords": 5, "minValues": {"id": "x"}, "maxValues": {"id": "z"}}"#,
        ));
        let (rewrite, carried) = prune_by_pk_stats(vec![keep, skip], Some(&range), &pk());
        assert_eq!(rewrite.len(), 1);
        assert_eq!(carried, 1);
    }

    // ---- source PK range across chunks ----------------------------------------------

    #[test]
    fn source_pk_range_spans_all_selected_chunks() {
        let batches = Arc::new(vec![part_batch(&["a", "a"]), part_batch(&["a"])]);
        let source = PartitionSource {
            batches: batches.clone(),
            sel: vec![RowSel::All, RowSel::All],
            rows: 3,
        };
        // Column 1 is v: [0, 1] and [0].
        let (mn, mx) = source_pk_range(&source, 1).unwrap().unwrap();
        assert_eq!(mn, Value::Number(0.into()));
        assert_eq!(mx, Value::Number(1.into()));
    }

    // ---- partition column re-adding --------------------------------------------------

    #[test]
    fn add_partition_column_appends_constant_column() {
        let b = int_batch(&[1, 2]);
        let out = add_partition_column(&b, "p", "2026-01-01").unwrap();
        assert_eq!(out.num_columns(), 2);
        let col = out
            .column_by_name("p")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(col.value(0), "2026-01-01");
        assert_eq!(col.value(1), "2026-01-01");
    }

    // ---- footprint estimation --------------------------------------------------------

    #[test]
    fn source_footprint_counts_pk_columns_only_once() {
        let schema: SchemaRef = Arc::new(Schema::new(vec![
            AField::new("p", DataType::Utf8, true),
            AField::new("v", DataType::Int64, false),
        ]));
        let b = part_batch(&["a", "b"]);
        let fp = source_footprint(std::slice::from_ref(&b), &schema, &["v".to_string()]).unwrap();
        assert_eq!(fp.source_bytes, b.get_array_memory_size());
        assert!(fp.pk_set_bytes >= b.column(1).get_array_memory_size());
        // Unknown PK column errors.
        assert!(source_footprint(&[b], &schema, &["nope".to_string()]).is_err());
    }
}
