//! Small-file compaction: delta-rs's `optimize.compact`, rewritten to stream row groups.
//!
//! delta-rs scans each bin through DataFusion, which decodes a whole row group (up to
//! 8192 rows) per batch and reads several files of a bin at once, so its peak memory
//! follows row width times rows per batch, not the bin's size. This module keeps
//! delta-rs's plan and commit semantics and replaces the execution.
//!
//! **Plan.** Bins come from the loaded snapshot alone, with no storage request, by
//! delta-rs's stable-order rule: a partition's files keep log order, neighbours are
//! packed while the bin's compressed size stays at or under the target, a file above
//! the target is skipped and splits the run, and a bin of one file is dropped. A
//! partition is rewritten only when its bins remove at least
//! [`CompactOptions::min_partition_removable_files`] more files than they produce.
//!
//! **Rewrite.** A bin reads one file at a time, in plan order, in batches bounded by
//! decoded bytes, through the same fetch and decode budgets and the same process-wide
//! partition and file permits the upsert uses (order partition -> file -> fetch -> bytes,
//! see `crate::limits`). A reader task decodes while the bin's writer encodes; a batch
//! keeps its decode permit until the writer has encoded it, and the writer never waits
//! on a budget, so the reader always makes progress. Output goes through
//! [`StreamingWriter`] with the writer properties `optimize` uses (ZSTD level 4), which
//! makes the output the same size as delta-rs's. A bin's output rolls to a new file at the
//! compressed target, or when the decoded bytes written to it (from the input footers)
//! reach [`CompactOptions::max_decoded_file_bytes`], so no output file decodes past the
//! 2 GiB Arrow offset limit. Row groups close at
//! [`CompactOptions::max_row_group_decoded_bytes`], which bounds what a later reader of
//! the output (an upsert, ClickHouse) fetches and decodes per row group.
//!
//! **Commit.** Removes and adds carry `dataChange=false`, and `commitInfo` is an
//! `OPTIMIZE` with `readVersion`, `isBlindAppend=false` and delta-rs's
//! `operationMetrics`. Every bin lands in one commit, or in chunks of
//! [`CompactOptions::max_bins_per_commit`] bins. Conflicts are resolved here, not by
//! delta-rs's checker, whose read set without DataFusion is the whole snapshot (a
//! concurrent merge in any partition would abort the compaction). When another writer
//! commits first, the table is refreshed and a bin is kept only if every file it removes
//! is still live at the same size. A bin that lost a file is dropped and its output
//! deleted, so a compaction never resurrects rows a merge replaced and never removes a
//! file twice. A changed schema, partitioning or protocol aborts with
//! [`Error::Conflict`]. The partitions of dropped bins are planned again from the
//! refreshed snapshot, up to [`CompactOptions::max_replan_rounds`] times.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use arrow_array::{new_null_array, ArrayRef, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use deltalake::kernel::transaction::{CommitBuilder, CommitProperties, TransactionError};
use deltalake::kernel::{Action, Add, Remove};
use deltalake::protocol::DeltaOperation;
use deltalake::table::config::TablePropertiesExt;
use deltalake::table::state::DeltaTableState;
use deltalake::writer::RecordBatchWriter;
use deltalake::{DeltaTable, DeltaTableError, ObjectStore, Path};
use futures::{StreamExt, TryStreamExt};
use object_store::ObjectStoreExt;
use parquet::file::metadata::ParquetMetaData;
use serde_json::{json, Value};
use tokio::sync::mpsc;
use tracing::{info, warn};
use uuid::Uuid;

use crate::errors::{Error, Result};
use crate::limits::ProcessLimits;
use crate::schema::cast_to_schema;
use crate::upsert::{
    best_effort_log_maintenance, byte_bounded_batch_rows, ensure_supported_table,
    max_row_group_fetch_bytes, open_builder, BudgetPermit, Budgets, TargetFile,
    INITIAL_DECODE_ESTIMATE_BYTES,
};
use crate::writer::{optimize_writer_properties, StreamingWriter};

/// Half the 2 GiB Arrow offset limit, the bound maintenance.py already plans bins to.
pub const DEFAULT_MAX_DECODED_FILE_BYTES: usize = 1024 * 1024 * 1024;
/// Decoded bytes per output row group.
pub const DEFAULT_MAX_ROW_GROUP_DECODED_BYTES: usize = 128 * 1024 * 1024;

/// Decoded batches a bin's reader may hold ready for its writer.
const READ_AHEAD_BATCHES: usize = 2;

/// Encoder state on top of the buffered output (page buffers, dictionaries, footer),
/// as a fraction of the target, when sizing bins against a memory slot.
const WRITER_OVERHEAD_DIVISOR: usize = 4;

/// Knobs for one compaction.
///
/// Memory is the fetch and decode budgets plus `max_parallel_bins` output files held
/// until upload, each up to `target_file_size` compressed. `slot_budget_bytes` fits all
/// three into one memory slot.
#[derive(Debug, Clone)]
pub struct CompactOptions {
    /// Bin and output size in compressed bytes; `None` uses `delta.targetFileSize`.
    pub target_file_size: Option<usize>,
    /// Bins rewritten at the same time. Files inside one bin are read one at a time.
    pub max_parallel_bins: usize,
    /// Memory one compaction may use. When set, the decode and fetch budgets are each
    /// capped at a quarter of it, and `max_parallel_bins` is lowered so the output files
    /// fit in the rest. One bin always runs.
    pub slot_budget_bytes: Option<usize>,
    pub max_buffered_bytes: usize,
    pub max_fetch_bytes: usize,
    /// Upper bound on rows per decoded batch; the byte bound usually wins first.
    pub read_batch_size: usize,
    /// Decoded bytes one batch should hold, which sets the rows read per batch.
    pub decode_batch_bytes: usize,
    /// Decoded bytes after which an output file is closed and a new one started.
    pub max_decoded_file_bytes: usize,
    /// Decoded bytes after which an output row group is closed.
    pub max_row_group_decoded_bytes: usize,
    /// Only these partition values are planned (`None` = every partition). Refused for
    /// an unpartitioned table.
    pub partitions: Option<Vec<String>>,
    /// A partition is rewritten only when its bins remove at least this many more files
    /// than they produce (one output per bin). `1` rewrites every partition that has a
    /// mergeable bin, as delta-rs does.
    pub min_partition_removable_files: usize,
    /// Commit after this many bins instead of once at the end (`None` = one commit).
    pub max_bins_per_commit: Option<usize>,
    /// Times the partitions of bins dropped on a conflict are planned and rewritten again.
    pub max_replan_rounds: usize,
    /// Times a commit is re-validated and retried after another writer committed first.
    pub commit_max_retries: usize,
    pub commit_metadata: Option<HashMap<String, Value>>,
    /// Plan only: report what would be rewritten without reading or writing data.
    pub dry_run: bool,
    pub limits: Arc<ProcessLimits>,
}

impl Default for CompactOptions {
    fn default() -> Self {
        Self {
            target_file_size: None,
            max_parallel_bins: 2,
            slot_budget_bytes: None,
            max_buffered_bytes: 64 * 1024 * 1024,
            max_fetch_bytes: 128 * 1024 * 1024,
            read_batch_size: 8192,
            decode_batch_bytes: INITIAL_DECODE_ESTIMATE_BYTES,
            max_decoded_file_bytes: DEFAULT_MAX_DECODED_FILE_BYTES,
            max_row_group_decoded_bytes: DEFAULT_MAX_ROW_GROUP_DECODED_BYTES,
            partitions: None,
            min_partition_removable_files: 1,
            max_bins_per_commit: None,
            max_replan_rounds: 1,
            commit_max_retries: 15,
            commit_metadata: None,
            dry_run: false,
            limits: ProcessLimits::global().clone(),
        }
    }
}

/// What a compaction did. With `dry_run`, the bin, partition and removal figures are
/// what the plan would rewrite.
#[derive(Debug, Clone, Default)]
pub struct CompactStats {
    pub files_considered: usize,
    /// Files the plan left alone: above the target, alone in their bin, or in a
    /// partition under `min_partition_removable_files`.
    pub files_skipped: usize,
    pub partitions_compacted: usize,
    pub bins: usize,
    pub files_removed: usize,
    pub files_added: usize,
    pub bytes_removed: u64,
    pub bytes_added: u64,
    pub rows_rewritten: usize,
    pub batches_read: usize,
    /// Bins that ran at the same time after `slot_budget_bytes` sizing.
    pub parallel_bins: usize,
    pub commits: usize,
    /// Commit attempts repeated because another writer committed first.
    pub commit_retries: usize,
    /// Bins discarded because a concurrent writer removed one of their files.
    pub bins_dropped: usize,
    pub replan_rounds: usize,
    pub largest_bin_files: usize,
    pub plan_ms: u64,
    pub rewrite_ms: u64,
    pub commit_ms: u64,
    /// Version of the last compaction commit, or the table version when none was made.
    pub version: i64,
    pub dry_run: bool,
}

#[derive(Debug, Clone)]
struct PlannedFile {
    path: String,
    size: u64,
    num_records: Option<usize>,
    remove: Remove,
}

#[derive(Debug)]
struct Bin {
    partition: Option<String>,
    files: Vec<PlannedFile>,
}

#[derive(Debug, Default)]
struct Plan {
    considered: usize,
    skipped: usize,
    partitions: usize,
    bins: Vec<Bin>,
}

/// delta-rs's `plan_compaction_bins_in_stable_order` plus its single-file pruning.
fn plan_bins(files: Vec<PlannedFile>, target: u64) -> Vec<Vec<PlannedFile>> {
    let mut bins: Vec<Vec<PlannedFile>> = Vec::new();
    let mut current: Vec<PlannedFile> = Vec::new();
    let mut current_size = 0u64;
    for f in files {
        if f.size > target {
            bins.push(std::mem::take(&mut current));
            current_size = 0;
            continue;
        }
        if !current.is_empty() && current_size + f.size > target {
            bins.push(std::mem::take(&mut current));
            current_size = 0;
        }
        current_size += f.size;
        current.push(f);
    }
    bins.push(current);
    bins.retain(|b| b.len() >= 2);
    bins
}

/// Bins for every selected partition of `table`'s loaded snapshot, in log order.
fn plan(
    table: &DeltaTable,
    partition_col: Option<&str>,
    target: u64,
    only: Option<&HashSet<Option<String>>>,
    min_removable: usize,
) -> Result<Plan> {
    let snapshot = table.snapshot()?;
    let mut order: Vec<Option<String>> = Vec::new();
    let mut by_partition: HashMap<Option<String>, Vec<PlannedFile>> = HashMap::new();
    let mut out = Plan::default();
    for view in snapshot.log_data().iter() {
        let remove = view.remove_action(false);
        let partition = partition_col.and_then(|c| {
            remove
                .partition_values
                .as_ref()
                .and_then(|pv| pv.get(c).cloned().flatten())
        });
        if only.is_some_and(|only| !only.contains(&partition)) {
            continue;
        }
        out.considered += 1;
        let file = PlannedFile {
            path: view.path().into_owned(),
            size: view.size().max(0) as u64,
            num_records: view.num_records(),
            remove,
        };
        by_partition
            .entry(partition.clone())
            .or_insert_with(|| {
                order.push(partition);
                Vec::new()
            })
            .push(file);
    }
    for partition in order {
        let files = by_partition.remove(&partition).unwrap_or_default();
        let total = files.len();
        let bins = plan_bins(files, target);
        let binned: usize = bins.iter().map(Vec::len).sum();
        if bins.is_empty() || binned - bins.len() < min_removable.max(1) {
            out.skipped += total;
            continue;
        }
        out.skipped += total - binned;
        out.partitions += 1;
        out.bins.extend(bins.into_iter().map(|files| Bin {
            partition: partition.clone(),
            files,
        }));
    }
    Ok(out)
}

/// Parallelism and budgets after fitting them into `slot_budget_bytes`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Sizing {
    parallel_bins: usize,
    max_buffered_bytes: usize,
    max_fetch_bytes: usize,
}

fn size_for_slot(opts: &CompactOptions, target: usize) -> Sizing {
    let mut s = Sizing {
        parallel_bins: opts.max_parallel_bins.max(1),
        max_buffered_bytes: opts.max_buffered_bytes,
        max_fetch_bytes: opts.max_fetch_bytes,
    };
    if let Some(slot) = opts.slot_budget_bytes.filter(|s| *s > 0) {
        s.max_buffered_bytes = s.max_buffered_bytes.min(slot / 4).max(1024);
        s.max_fetch_bytes = s.max_fetch_bytes.min(slot / 4).max(1024);
        let writers = slot.saturating_sub(s.max_buffered_bytes + s.max_fetch_bytes);
        let per_bin = target
            .saturating_add(target / WRITER_OVERHEAD_DIVISOR)
            .max(1);
        s.parallel_bins = (writers / per_bin).clamp(1, s.parallel_bins);
    }
    s
}

/// Footer-reported decoded bytes per row of one file (0 when the footer has none).
fn decoded_bytes_per_row(meta: &ParquetMetaData) -> f64 {
    let (bytes, rows) = meta.row_groups().iter().fold((0i64, 0i64), |(b, r), rg| {
        (b + rg.total_byte_size().max(0), r + rg.num_rows().max(0))
    });
    if rows == 0 {
        0.0
    } else {
        bytes as f64 / rows as f64
    }
}

/// `batch` with the partition column set to the log's value for the file. The value is
/// authoritative even when a writer also stored the column in the file.
fn with_partition_column(
    batch: &RecordBatch,
    column: Option<&str>,
    value: Option<&str>,
) -> Result<RecordBatch> {
    let Some(column) = column else {
        return Ok(batch.clone());
    };
    let n = batch.num_rows();
    let values: ArrayRef = match value {
        Some(v) => Arc::new(StringArray::from(vec![v; n])),
        None => new_null_array(&DataType::Utf8, n),
    };
    let schema = batch.schema();
    let mut fields = Vec::with_capacity(schema.fields().len() + 1);
    let mut columns = Vec::with_capacity(schema.fields().len() + 1);
    for (field, col) in schema.fields().iter().zip(batch.columns()) {
        if field.name() != column {
            fields.push(field.clone());
            columns.push(col.clone());
        }
    }
    fields.push(Arc::new(Field::new(column, DataType::Utf8, true)));
    columns.push(values);
    Ok(RecordBatch::try_new(
        Arc::new(Schema::new(fields)),
        columns,
    )?)
}

fn add_num_records(add: &Add) -> Option<usize> {
    let stats: Value = serde_json::from_str(add.stats.as_deref()?).ok()?;
    stats.get("numRecords")?.as_u64().map(|n| n as usize)
}

/// Output file name, unique per file (the writer puts a fresh UUID in it). Compared by
/// name because the log returns paths decoded and the writer records them encoded.
fn file_name(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

struct RewriteCtx {
    table: DeltaTable,
    store: Arc<dyn ObjectStore>,
    table_schema: SchemaRef,
    partition_col: Option<String>,
    budgets: Budgets,
    limits: Arc<ProcessLimits>,
    target_file_size: usize,
    read_batch_size: usize,
    decode_batch_bytes: usize,
    max_decoded_file_bytes: usize,
    max_row_group_decoded_bytes: usize,
    /// Set when one bin fails, so the others stop at their next batch.
    cancel: AtomicBool,
}

impl RewriteCtx {
    fn check_cancelled(&self) -> Result<()> {
        if self.cancel.load(Ordering::Relaxed) {
            return Err(Error::Generic(
                "compaction stopped because another bin failed".into(),
            ));
        }
        Ok(())
    }
}

struct BinOutput {
    partition: Option<String>,
    removes: Vec<Remove>,
    adds: Vec<Add>,
    rows: usize,
    batches: usize,
    bytes_removed: u64,
}

/// Paths of the output files `bins` uploaded.
fn output_paths<'a>(bins: impl IntoIterator<Item = &'a BinOutput>) -> Vec<String> {
    bins.into_iter()
        .flat_map(|b| b.adds.iter().map(|a| a.path.clone()))
        .collect()
}

async fn delete_outputs(store: &Arc<dyn ObjectStore>, paths: Vec<String>) {
    for path in paths {
        let result = match Path::parse(&path) {
            Ok(p) => store.delete(&p).await.map_err(|e| e.to_string()),
            Err(e) => Err(e.to_string()),
        };
        if let Err(error) = result {
            warn!(%path, %error, "could not delete an uncommitted compaction output");
        }
    }
}

/// Rewrite one bin. Output files it uploaded are deleted again when it fails.
async fn rewrite_bin(ctx: Arc<RewriteCtx>, bin: Bin) -> Result<BinOutput> {
    ctx.check_cancelled()?;
    let _partition = ctx.limits.acquire_partition().await?;
    let mut written = Vec::new();
    match rewrite_bin_inner(&ctx, bin, &mut written).await {
        Ok(out) => Ok(out),
        Err(e) => {
            delete_outputs(&ctx.store, written.iter().map(|a| a.path.clone()).collect()).await;
            Err(e)
        }
    }
}

/// A batch on its way from a bin's reader to its writer, cast to the table schema. It
/// keeps its decode budget until the writer has encoded it.
struct ReadBatch {
    batch: RecordBatch,
    /// Decoded bytes by the input footer's measure.
    decoded: f64,
    _permit: BudgetPermit,
}

/// Read `files` in order and send their batches to the bin's writer. Stops quietly when
/// the writer has gone away (it failed, and reports why).
async fn read_bin(
    ctx: Arc<RewriteCtx>,
    files: Vec<PlannedFile>,
    partition: Option<String>,
    tx: mpsc::Sender<ReadBatch>,
) -> Result<()> {
    for f in files {
        ctx.check_cancelled()?;
        let target = TargetFile {
            path: f.path.clone(),
            size: f.size,
            stats: None,
            remove: f.remove,
            metadata: None,
        };
        let _file = ctx.limits.acquire_file().await?;
        let builder = open_builder(&ctx.store, &target).await?;
        let bytes_per_row = decoded_bytes_per_row(builder.metadata());
        let _fetch = ctx
            .budgets
            .acquire_fetch(max_row_group_fetch_bytes(builder.metadata(), None))
            .await?;
        let batch_rows = byte_bounded_batch_rows(
            builder.metadata(),
            ctx.decode_batch_bytes,
            ctx.read_batch_size,
        );
        let mut stream = builder.with_batch_size(batch_rows).build()?;
        let mut estimate = ctx.decode_batch_bytes;
        let mut file_rows = 0usize;
        loop {
            ctx.check_cancelled()?;
            let mut permit = ctx.budgets.acquire_bytes(estimate).await?;
            let Some(batch) = stream.try_next().await? else {
                break;
            };
            let actual = batch.get_array_memory_size();
            ctx.budgets.top_up(&mut permit, actual).await?;
            estimate = actual.max(64 * 1024);
            if batch.num_rows() == 0 {
                continue;
            }
            file_rows += batch.num_rows();
            let decoded = batch.num_rows() as f64 * bytes_per_row;
            let batch =
                with_partition_column(&batch, ctx.partition_col.as_deref(), partition.as_deref())?;
            let item = ReadBatch {
                batch: cast_to_schema(&batch, &ctx.table_schema)?,
                decoded,
                _permit: permit,
            };
            if tx.send(item).await.is_err() {
                return Ok(());
            }
        }
        if let Some(expected) = f.num_records {
            if expected != file_rows {
                return Err(Error::Generic(format!(
                    "read {file_rows} rows from {} but its Add statistics record {expected}",
                    f.path
                )));
            }
        }
    }
    Ok(())
}

/// The bin's writer. A reader task decodes the next batches while this encodes, so one
/// bin keeps two cores busy; files still arrive in plan order, so the output keeps the
/// bin's row order, and the bin holds at most one reader's row group at a time.
async fn rewrite_bin_inner(
    ctx: &Arc<RewriteCtx>,
    bin: Bin,
    written: &mut Vec<Add>,
) -> Result<BinOutput> {
    let mut writer = StreamingWriter::for_table(&ctx.table)?
        .with_writer_properties(optimize_writer_properties());
    let removes: Vec<Remove> = bin.files.iter().map(|f| f.remove.clone()).collect();
    let bytes_removed: u64 = bin.files.iter().map(|f| f.size).sum();
    let (tx, mut rx) = mpsc::channel(READ_AHEAD_BATCHES);
    let reader = tokio::spawn(read_bin(ctx.clone(), bin.files, bin.partition.clone(), tx));

    let (mut rows, mut batches) = (0usize, 0usize);
    let written_ok: Result<()> = async {
        let (mut file_decoded, mut row_group_decoded) = (0f64, 0f64);
        while let Some(item) = rx.recv().await {
            rows += item.batch.num_rows();
            batches += 1;
            writer.write(item.batch)?;
            file_decoded += item.decoded;
            row_group_decoded += item.decoded;
            if writer.buffer_len() >= ctx.target_file_size
                || file_decoded >= ctx.max_decoded_file_bytes as f64
            {
                written.extend(writer.flush().await?);
                file_decoded = 0.0;
                row_group_decoded = 0.0;
            } else if writer.in_progress_rows() == 0 {
                // The encoder closed the row group itself at its row cap.
                row_group_decoded = 0.0;
            } else if row_group_decoded >= ctx.max_row_group_decoded_bytes as f64 {
                writer.flush_row_groups()?;
                row_group_decoded = 0.0;
            }
        }
        Ok(())
    }
    .await;
    // Closing the channel stops a reader the writer gave up on at its next send.
    drop(rx);
    let read_ok = reader
        .await
        .map_err(|e| Error::Generic(format!("compaction reader panicked: {e}")))?;
    written_ok?;
    read_ok?;
    written.extend(writer.flush().await?);

    let rows_written: Option<usize> = written.iter().map(add_num_records).sum();
    if let Some(rows_written) = rows_written {
        if rows_written != rows {
            return Err(Error::Generic(format!(
                "compaction read {rows} rows but wrote {rows_written}"
            )));
        }
    }
    let adds = written
        .drain(..)
        .map(|mut a| {
            a.data_change = false;
            a
        })
        .collect();
    Ok(BinOutput {
        partition: bin.partition,
        removes,
        adds,
        rows,
        batches,
        bytes_removed,
    })
}

/// The file-size summary delta-rs records for `filesAdded` / `filesRemoved`.
fn size_details(sizes: impl Iterator<Item = i64>) -> String {
    let (mut n, mut total, mut min, mut max) = (0usize, 0i64, i64::MAX, 0i64);
    for s in sizes {
        n += 1;
        total += s;
        min = min.min(s);
        max = max.max(s);
    }
    let avg = if n == 0 { 0.0 } else { total as f64 / n as f64 };
    json!({
        "avg": avg,
        "max": max,
        "min": if n == 0 { 0 } else { min },
        "totalFiles": n,
        "totalSize": total,
    })
    .to_string()
}

enum CommitFailure {
    /// The commit did not land; the bins' outputs are safe to delete.
    Unapplied(Error, Vec<BinOutput>),
    /// The outcome is unknown (the log write itself failed); outputs must stay.
    Unknown(Error),
}

/// `true` when the commit lost the race for its version to another writer. With no
/// delta-rs retries both "the log moved" and "the version exists" surface this way.
fn lost_race(e: &DeltaTableError) -> bool {
    matches!(
        e,
        DeltaTableError::Transaction {
            source: TransactionError::MaxCommitAttempts(_)
                | TransactionError::VersionAlreadyExists(_)
        }
    )
}

struct TableShape {
    schema: String,
    partition_columns: Vec<String>,
    protocol: String,
}

impl TableShape {
    fn of(table: &DeltaTable) -> Result<Self> {
        let snapshot = table.snapshot()?;
        let protocol = snapshot.protocol();
        Ok(Self {
            schema: serde_json::to_string(snapshot.schema().as_ref())
                .map_err(|e| Error::Generic(format!("serialising table schema: {e}")))?,
            partition_columns: snapshot.metadata().partition_columns().to_vec(),
            protocol: format!(
                "{}/{}/{:?}/{:?}",
                protocol.min_reader_version(),
                protocol.min_writer_version(),
                protocol.reader_features(),
                protocol.writer_features()
            ),
        })
    }
}

/// Commit state that carries over between chunks and re-plan rounds.
struct Committer {
    /// Working table; its snapshot is the base the next commit attempt validates against.
    table: DeltaTable,
    shape: TableShape,
    operation: DeltaOperation,
    operation_id: Uuid,
    read_version: u64,
    max_retries: usize,
    commit_metadata: HashMap<String, Value>,
    files_considered: usize,
    files_skipped: usize,
    commits: usize,
    retries: usize,
    last_version: Option<u64>,
}

impl Committer {
    fn app_metadata(&self, bins: &[BinOutput]) -> HashMap<String, Value> {
        let partitions: HashSet<&Option<String>> = bins.iter().map(|b| &b.partition).collect();
        let metrics = json!({
            "numFilesAdded": bins.iter().map(|b| b.adds.len()).sum::<usize>(),
            "numFilesRemoved": bins.iter().map(|b| b.removes.len()).sum::<usize>(),
            "filesAdded": size_details(bins.iter().flat_map(|b| b.adds.iter().map(|a| a.size))),
            "filesRemoved": size_details(
                bins.iter().flat_map(|b| b.removes.iter().map(|r| r.size.unwrap_or(0)))
            ),
            "partitionsOptimized": partitions.len(),
            "numBatches": bins.iter().map(|b| b.batches).sum::<usize>(),
            "totalConsideredFiles": self.files_considered,
            "totalFilesSkipped": self.files_skipped,
            "preserveInsertionOrder": true,
        });
        let mut md = self.commit_metadata.clone();
        md.insert("readVersion".into(), json!(self.read_version));
        md.insert("isBlindAppend".into(), json!(false));
        md.insert("operationMetrics".into(), metrics);
        md
    }

    /// Commit `bins`, re-validating them against each commit that beat this one. Returns
    /// the bins that landed and the bins dropped because a file they remove is gone.
    async fn commit(
        &mut self,
        bins: Vec<BinOutput>,
    ) -> std::result::Result<(Vec<BinOutput>, Vec<BinOutput>), CommitFailure> {
        let mut live = bins;
        let mut dropped: Vec<BinOutput> = Vec::new();
        let mut attempt = 0usize;
        loop {
            if live.is_empty() {
                return Ok((live, dropped));
            }
            let snapshot = match self.table.snapshot() {
                Ok(s) => s,
                Err(e) => {
                    live.extend(dropped);
                    return Err(CommitFailure::Unapplied(e.into(), live));
                }
            };
            let checkpoint_interval = snapshot.table_config().checkpoint_interval().get();
            let cleanup_enabled = snapshot.table_config().enable_expired_log_cleanup();
            // Vacuum retention counts from the deletion timestamp, so it is the time of
            // this attempt, not of the plan a long rewrite ago.
            let now = chrono::Utc::now().timestamp_millis();
            let mut actions: Vec<Action> = Vec::new();
            for b in &live {
                actions.extend(b.removes.iter().map(|r| {
                    Action::Remove(Remove {
                        deletion_timestamp: Some(now),
                        ..r.clone()
                    })
                }));
                actions.extend(b.adds.iter().cloned().map(Action::Add));
            }
            // Retries stay here: delta-rs would re-check against the whole snapshot (see
            // the module docs) and could not drop just the bins that lost a file.
            let props = CommitProperties::default()
                .with_max_retries(0)
                .with_create_checkpoint(false)
                .with_cleanup_expired_logs(Some(false))
                .with_metadata(self.app_metadata(&live));
            let result = CommitBuilder::from(props)
                .with_actions(actions)
                .with_operation_id(self.operation_id)
                .build(
                    Some(snapshot),
                    self.table.log_store(),
                    self.operation.clone(),
                )
                .await;
            match result {
                Ok(finalized) => {
                    let version = finalized.version();
                    self.table.state = Some(finalized.snapshot);
                    self.commits += 1;
                    self.last_version = Some(version);
                    if (version + 1) % checkpoint_interval == 0 {
                        best_effort_log_maintenance(&self.table, version, cleanup_enabled).await;
                    }
                    return Ok((live, dropped));
                }
                Err(e) if lost_race(&e) => {
                    attempt += 1;
                    self.retries += 1;
                    tokio::time::sleep(Duration::from_millis(50 * attempt.min(10) as u64)).await;
                    if let Err(e) = self.table.update_incremental(None).await {
                        return Err(CommitFailure::Unknown(e.into()));
                    }
                    let snapshot = match self.table.snapshot() {
                        Ok(s) => s,
                        Err(e) => return Err(CommitFailure::Unknown(e.into())),
                    };
                    let mut live_files: HashMap<String, i64> = HashMap::new();
                    let mut live_names: HashSet<String> = HashSet::new();
                    for view in snapshot.log_data().iter() {
                        let path = view.path().into_owned();
                        live_names.insert(file_name(&path).to_string());
                        live_files.insert(path, view.size());
                    }
                    let version = snapshot.version();
                    // A write whose response was lost reports "version exists" for its own
                    // commit; its outputs being live is the proof.
                    if live
                        .iter()
                        .flat_map(|b| &b.adds)
                        .any(|a| live_names.contains(file_name(&a.path)))
                    {
                        self.commits += 1;
                        self.last_version = Some(version);
                        return Ok((live, dropped));
                    }
                    if let Err(e) = self.check_shape() {
                        live.extend(dropped);
                        return Err(CommitFailure::Unapplied(e, live));
                    }
                    if attempt > self.max_retries {
                        live.extend(dropped);
                        return Err(CommitFailure::Unapplied(
                            Error::Conflict(format!(
                                "compaction lost the commit race {attempt} times; retry later"
                            )),
                            live,
                        ));
                    }
                    let (keep, lost): (Vec<_>, Vec<_>) = live.into_iter().partition(|b| {
                        b.removes
                            .iter()
                            .all(|r| live_files.get(&r.path).copied() == r.size)
                    });
                    if !lost.is_empty() {
                        info!(
                            dropped = lost.len(),
                            kept = keep.len(),
                            version,
                            "compaction bins lost a file to a concurrent commit"
                        );
                    }
                    dropped.extend(lost);
                    live = keep;
                }
                Err(e) => return Err(CommitFailure::Unknown(e.into())),
            }
        }
    }

    fn check_shape(&self) -> Result<()> {
        ensure_supported_table(&self.table)?;
        let now = TableShape::of(&self.table)?;
        if now.schema != self.shape.schema
            || now.partition_columns != self.shape.partition_columns
            || now.protocol != self.shape.protocol
        {
            return Err(Error::Conflict(
                "a concurrent commit changed the table's schema, partitioning or protocol; \
                 compaction must be planned again"
                    .into(),
            ));
        }
        Ok(())
    }
}

/// Commit `pending` and fold the result into `stats`. Bins dropped on a conflict have
/// their outputs deleted and their partitions recorded in `dropped_partitions`.
async fn commit_pending(
    committer: &mut Committer,
    store: &Arc<dyn ObjectStore>,
    pending: &mut Vec<BinOutput>,
    dropped_partitions: &mut HashSet<Option<String>>,
    committed_partitions: &mut HashSet<Option<String>>,
    stats: &mut CompactStats,
) -> Result<()> {
    if pending.is_empty() {
        return Ok(());
    }
    let started = Instant::now();
    let outcome = committer.commit(std::mem::take(pending)).await;
    stats.commit_ms += started.elapsed().as_millis() as u64;
    match outcome {
        Ok((committed, dropped)) => {
            for b in &committed {
                committed_partitions.insert(b.partition.clone());
                stats.bins += 1;
                stats.files_removed += b.removes.len();
                stats.files_added += b.adds.len();
                stats.bytes_removed += b.bytes_removed;
                stats.bytes_added += b.adds.iter().map(|a| a.size.max(0) as u64).sum::<u64>();
                stats.rows_rewritten += b.rows;
                stats.batches_read += b.batches;
                stats.largest_bin_files = stats.largest_bin_files.max(b.removes.len());
            }
            stats.bins_dropped += dropped.len();
            for b in &dropped {
                dropped_partitions.insert(b.partition.clone());
            }
            delete_outputs(store, output_paths(&dropped)).await;
            Ok(())
        }
        Err(CommitFailure::Unapplied(e, bins)) => {
            delete_outputs(store, output_paths(&bins)).await;
            Err(e)
        }
        Err(CommitFailure::Unknown(e)) => {
            warn!(error = %e, "compaction commit outcome unknown; its output files are kept");
            Err(e)
        }
    }
}

/// Rewrite `bins` with `parallel` bins in flight and commit them in chunks of `chunk`.
/// Returns the partitions of bins dropped on a conflict.
async fn run_round(
    committer: &mut Committer,
    ctx: Arc<RewriteCtx>,
    bins: Vec<Bin>,
    parallel: usize,
    chunk: usize,
    committed_partitions: &mut HashSet<Option<String>>,
    stats: &mut CompactStats,
) -> Result<HashSet<Option<String>>> {
    let store = ctx.store.clone();
    let spawn_ctx = ctx.clone();
    let mut results = futures::stream::iter(bins)
        .map(move |bin| tokio::spawn(rewrite_bin(spawn_ctx.clone(), bin)))
        .buffered(parallel.max(1));
    let mut pending: Vec<BinOutput> = Vec::new();
    let mut dropped_partitions = HashSet::new();
    let mut failure: Option<Error> = None;
    while let Some(joined) = results.next().await {
        match joined {
            Ok(Ok(out)) => pending.push(out),
            Ok(Err(e)) => {
                failure = Some(e);
                break;
            }
            Err(e) => {
                failure = Some(Error::Generic(format!("compaction worker panicked: {e}")));
                break;
            }
        }
        if pending.len() >= chunk {
            if let Err(e) = commit_pending(
                committer,
                &store,
                &mut pending,
                &mut dropped_partitions,
                committed_partitions,
                stats,
            )
            .await
            {
                failure = Some(e);
                break;
            }
        }
    }
    if let Some(e) = failure {
        // In-flight bins see the flag, delete their own outputs and stop; bins that
        // already finished were never committed, so their outputs go too.
        ctx.cancel.store(true, Ordering::Relaxed);
        while let Some(joined) = results.next().await {
            if let Ok(Ok(out)) = joined {
                pending.push(out);
            }
        }
        delete_outputs(&store, output_paths(&pending)).await;
        return Err(e);
    }
    commit_pending(
        committer,
        &store,
        &mut pending,
        &mut dropped_partitions,
        committed_partitions,
        stats,
    )
    .await?;
    Ok(dropped_partitions)
}

/// Compact the small files of `table`'s loaded snapshot. Returns the stats and, when a
/// commit was made, the table state after the last one.
pub async fn compact(
    table: &DeltaTable,
    opts: CompactOptions,
) -> Result<(CompactStats, Option<DeltaTableState>)> {
    let plan_started = Instant::now();
    ensure_supported_table(table)?;
    let snapshot = table.snapshot()?;
    let partition_columns: Vec<String> = snapshot.metadata().partition_columns().to_vec();
    if partition_columns.len() > 1 {
        return Err(Error::Unsupported(format!(
            "deltalite supports at most one partition column, table has {partition_columns:?}"
        )));
    }
    let partition_col = partition_columns.first().cloned();
    if partition_col.is_none() && opts.partitions.is_some() {
        return Err(Error::SchemaMismatch(
            "partitions were given but the table is not partitioned".into(),
        ));
    }
    let target_file_size = match opts.target_file_size {
        Some(v) if v > 0 => v,
        _ => snapshot.table_config().target_file_size().get() as usize,
    };
    let only: Option<HashSet<Option<String>>> = opts
        .partitions
        .as_ref()
        .map(|values| values.iter().cloned().map(Some).collect());
    let first = plan(
        table,
        partition_col.as_deref(),
        target_file_size as u64,
        only.as_ref(),
        opts.min_partition_removable_files,
    )?;
    let sizing = size_for_slot(&opts, target_file_size);
    let mut stats = CompactStats {
        files_considered: first.considered,
        files_skipped: first.skipped,
        parallel_bins: sizing.parallel_bins,
        dry_run: opts.dry_run,
        version: i64::try_from(snapshot.version()).unwrap_or(i64::MAX),
        plan_ms: plan_started.elapsed().as_millis() as u64,
        ..Default::default()
    };
    if opts.dry_run || first.bins.is_empty() {
        stats.partitions_compacted = first.partitions;
        stats.bins = first.bins.len();
        for b in &first.bins {
            stats.files_removed += b.files.len();
            stats.bytes_removed += b.files.iter().map(|f| f.size).sum::<u64>();
            stats.largest_bin_files = stats.largest_bin_files.max(b.files.len());
        }
        return Ok((stats, None));
    }

    let predicate = match &opts.partitions {
        Some(values) => {
            json!([[partition_col.clone().unwrap_or_default(), "in", values]]).to_string()
        }
        None => "[]".to_string(),
    };
    let mut committer = Committer {
        table: table.clone(),
        shape: TableShape::of(table)?,
        operation: DeltaOperation::Optimize {
            predicate: Some(predicate),
            target_size: target_file_size as i64,
        },
        operation_id: Uuid::new_v4(),
        read_version: snapshot.version(),
        max_retries: opts.commit_max_retries,
        commit_metadata: opts.commit_metadata.clone().unwrap_or_default(),
        files_considered: first.considered,
        files_skipped: first.skipped,
        commits: 0,
        retries: 0,
        last_version: None,
    };
    let budgets = Budgets::new(
        sizing.max_buffered_bytes,
        sizing.max_fetch_bytes,
        opts.limits.clone(),
    );
    let table_schema = RecordBatchWriter::for_table(table)?.arrow_schema();
    let chunk = opts
        .max_bins_per_commit
        .filter(|n| *n > 0)
        .unwrap_or(usize::MAX);
    let mut committed_partitions: HashSet<Option<String>> = HashSet::new();

    let rewrite_started = Instant::now();
    let mut bins = first.bins;
    let mut round = 0usize;
    loop {
        let ctx = Arc::new(RewriteCtx {
            table: committer.table.clone(),
            store: committer.table.object_store(),
            table_schema: table_schema.clone(),
            partition_col: partition_col.clone(),
            budgets: budgets.clone(),
            limits: opts.limits.clone(),
            target_file_size,
            read_batch_size: opts.read_batch_size,
            decode_batch_bytes: opts.decode_batch_bytes,
            max_decoded_file_bytes: opts.max_decoded_file_bytes.max(1),
            max_row_group_decoded_bytes: opts.max_row_group_decoded_bytes.max(1),
            cancel: AtomicBool::new(false),
        });
        let dropped = run_round(
            &mut committer,
            ctx,
            bins,
            sizing.parallel_bins,
            chunk,
            &mut committed_partitions,
            &mut stats,
        )
        .await?;
        if dropped.is_empty() || round >= opts.max_replan_rounds {
            break;
        }
        round += 1;
        stats.replan_rounds = round;
        // The committer refreshed its table while it resolved the conflict, so this plans
        // against what the concurrent writer left behind.
        let again = plan(
            &committer.table,
            partition_col.as_deref(),
            target_file_size as u64,
            Some(&dropped),
            opts.min_partition_removable_files,
        )?;
        if again.bins.is_empty() {
            break;
        }
        bins = again.bins;
    }
    stats.rewrite_ms =
        (rewrite_started.elapsed().as_millis() as u64).saturating_sub(stats.commit_ms);
    stats.partitions_compacted = committed_partitions.len();
    stats.commits = committer.commits;
    stats.commit_retries = committer.retries;
    if let Some(v) = committer.last_version {
        stats.version = i64::try_from(v)
            .map_err(|_| Error::Generic("committed version overflows i64".into()))?;
    }
    info!(
        version = stats.version,
        bins = stats.bins,
        bins_dropped = stats.bins_dropped,
        files_removed = stats.files_removed,
        files_added = stats.files_added,
        commits = stats.commits,
        commit_retries = stats.commit_retries,
        plan_ms = stats.plan_ms,
        rewrite_ms = stats.rewrite_ms,
        commit_ms = stats.commit_ms,
        "compaction finished"
    );
    let state = if committer.commits > 0 {
        committer.table.state
    } else {
        None
    };
    Ok((stats, state))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn file(size: u64) -> PlannedFile {
        PlannedFile {
            path: format!("f{size}"),
            size,
            num_records: None,
            remove: Remove {
                path: format!("f{size}"),
                data_change: false,
                deletion_timestamp: None,
                extended_file_metadata: None,
                partition_values: None,
                size: Some(size as i64),
                tags: None,
                deletion_vector: None,
                base_row_id: None,
                default_row_commit_version: None,
            },
        }
    }

    fn sizes(bins: &[Vec<PlannedFile>]) -> Vec<Vec<u64>> {
        bins.iter()
            .map(|b| b.iter().map(|f| f.size).collect())
            .collect()
    }

    #[test]
    fn bins_pack_neighbours_skip_large_files_and_drop_singletons() {
        let files = [10, 20, 80, 30, 200, 5, 6, 7, 100]
            .into_iter()
            .map(file)
            .collect();
        // 10+20 fit and 80 would overflow; [80] then meets 30 (overflow) and is dropped;
        // [30] is cut by the oversized 200; [5,6,7] packs; 100 equals the target, so it
        // is a candidate, but 5+6+7+100 overflows and [100] alone is dropped.
        assert_eq!(
            sizes(&plan_bins(files, 100)),
            vec![vec![10, 20], vec![5, 6, 7]]
        );
    }

    #[test]
    fn a_partition_of_one_file_or_only_oversized_files_plans_nothing() {
        assert!(plan_bins(vec![file(10)], 100).is_empty());
        assert!(plan_bins(vec![file(101), file(150)], 100).is_empty());
        assert!(plan_bins(Vec::new(), 100).is_empty());
    }

    #[test]
    fn a_bin_may_reach_the_target_exactly() {
        assert_eq!(
            sizes(&plan_bins(vec![file(50), file(50), file(1)], 100)),
            vec![vec![50, 50]]
        );
    }

    fn opts_with(slot: Option<usize>, bins: usize) -> CompactOptions {
        CompactOptions {
            slot_budget_bytes: slot,
            max_parallel_bins: bins,
            max_buffered_bytes: 64 << 20,
            max_fetch_bytes: 128 << 20,
            ..Default::default()
        }
    }

    #[test]
    fn slot_budget_caps_parallel_bins_and_budgets() {
        let mb = 1 << 20;
        assert_eq!(
            size_for_slot(&opts_with(None, 4), 100 * mb),
            Sizing {
                parallel_bins: 4,
                max_buffered_bytes: 64 * mb,
                max_fetch_bytes: 128 * mb
            }
        );
        // 2000 MB: both budgets sit under a quarter and 1808 MB of writers fits 14 bins
        // of 125 MB, capped at the 4 asked for.
        assert_eq!(
            size_for_slot(&opts_with(Some(2000 * mb), 4), 100 * mb).parallel_bins,
            4
        );
        // 400 MB: the fetch budget drops to 100 MB, leaving 236 MB, one 125 MB bin.
        assert_eq!(
            size_for_slot(&opts_with(Some(400 * mb), 4), 100 * mb),
            Sizing {
                parallel_bins: 1,
                max_buffered_bytes: 64 * mb,
                max_fetch_bytes: 100 * mb
            }
        );
        // 1000 MB: 808 MB of writers fits 6 bins, capped at 4; with 8 asked, 6.
        assert_eq!(
            size_for_slot(&opts_with(Some(1000 * mb), 8), 100 * mb).parallel_bins,
            6
        );
        assert_eq!(
            size_for_slot(&opts_with(Some(10 * mb), 4), 100 * mb).parallel_bins,
            1
        );
        assert_eq!(
            size_for_slot(&opts_with(Some(0), 3), 100 * mb).parallel_bins,
            3
        );
    }

    #[test]
    fn partition_column_takes_the_log_value_and_replaces_a_stored_one() {
        let id: ArrayRef = Arc::new(StringArray::from(vec!["a", "b"]));
        let stored: ArrayRef = Arc::new(StringArray::from(vec!["stale", "stale"]));
        let batch = RecordBatch::try_from_iter(vec![("id", id), ("p", stored)]).unwrap();
        let out = with_partition_column(&batch, Some("p"), Some("x y")).unwrap();
        assert_eq!(out.num_columns(), 2);
        let p = out
            .column_by_name("p")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(p.iter().collect::<Vec<_>>(), vec![Some("x y"), Some("x y")]);

        let null = with_partition_column(&batch, Some("p"), None).unwrap();
        assert_eq!(null.column_by_name("p").unwrap().null_count(), 2);

        let unpartitioned = with_partition_column(&batch, None, Some("x")).unwrap();
        assert_eq!(unpartitioned.schema(), batch.schema());
    }

    #[test]
    fn size_details_match_the_delta_rs_shape() {
        let v: Value = serde_json::from_str(&size_details([10i64, 30].into_iter())).unwrap();
        assert_eq!(v["totalFiles"], 2);
        assert_eq!(v["totalSize"], 40);
        assert_eq!(v["min"], 10);
        assert_eq!(v["max"], 30);
        assert_eq!(v["avg"], 20.0);
        let empty: Value = serde_json::from_str(&size_details(std::iter::empty())).unwrap();
        assert_eq!(empty["min"], 0);
        assert_eq!(empty["totalFiles"], 0);
    }

    #[test]
    fn output_files_match_by_name_across_path_encodings() {
        assert_eq!(
            file_name("p=a%20b/part-1-abc.zstd.parquet"),
            "part-1-abc.zstd.parquet"
        );
        assert_eq!(
            file_name("p=a b/part-1-abc.zstd.parquet"),
            "part-1-abc.zstd.parquet"
        );
        assert_eq!(file_name("part-1-abc.parquet"), "part-1-abc.parquet");
    }
}
