//! Small-file compaction that streams row groups instead of materialising bins.
//!
//! delta-rs's `optimize.compact` scans each bin through DataFusion. A scan decodes a whole
//! row group (up to 8192 rows) per batch and reads several files of a bin at once, so its
//! peak memory follows row width times rows per batch, not the bin's size. This module
//! plans bins the way delta-rs plans them (same stable-order binning, same skip rules), but
//! rewrites each bin by reading one file at a time, one byte-bounded batch at a time,
//! through the same fetch and decode budgets and the same [`StreamingWriter`] the upsert
//! uses. Only partitions that hold a bin with two or more files are read, and every bin
//! lands in ONE commit.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use deltalake::kernel::transaction::{CommitBuilder, CommitProperties};
use deltalake::kernel::Action;
use deltalake::protocol::DeltaOperation;
use deltalake::table::config::TablePropertiesExt;
use deltalake::table::state::DeltaTableState;
use deltalake::writer::RecordBatchWriter;
use deltalake::{DeltaTable, ObjectStore};
use futures::TryStreamExt;
use parquet::basic::{Compression, ZstdLevel};
use serde_json::Value;
use tokio::sync::Semaphore;
use tracing::info;

use crate::errors::{Error, Result};
use crate::limits::ProcessLimits;
use crate::schema::cast_to_schema;
use crate::upsert::{
    add_partition_column, best_effort_log_maintenance, byte_bounded_batch_rows,
    ensure_supported_table, max_row_group_fetch_bytes, open_builder, resolve_target_file_size,
    Budgets, TargetFile, INITIAL_DECODE_ESTIMATE_BYTES,
};
use crate::writer::StreamingWriter;

/// Knobs for one compaction. Memory is bounded by `max_parallel_bins` output files
/// (each up to `target_file_size` compressed) plus the fetch and decode budgets.
#[derive(Debug, Clone)]
pub struct CompactOptions {
    /// Bin and output size in compressed bytes; `None` uses `delta.targetFileSize`.
    pub target_file_size: Option<usize>,
    /// Bins rewritten at the same time. Files inside one bin are read one at a time.
    pub max_parallel_bins: usize,
    pub max_buffered_bytes: usize,
    pub max_fetch_bytes: usize,
    /// Upper bound on rows per decoded batch; the byte bound usually wins first.
    pub read_batch_size: usize,
    /// Decoded bytes one batch should hold, which sets the rows read per batch.
    pub decode_batch_bytes: usize,
    /// Only these partition values are planned (`None` = every partition).
    pub partitions: Option<Vec<String>>,
    pub commit_max_retries: usize,
    pub commit_metadata: Option<HashMap<String, Value>>,
    pub limits: Arc<ProcessLimits>,
}

impl Default for CompactOptions {
    fn default() -> Self {
        Self {
            target_file_size: None,
            max_parallel_bins: 2,
            max_buffered_bytes: 64 * 1024 * 1024,
            max_fetch_bytes: 128 * 1024 * 1024,
            read_batch_size: 8192,
            decode_batch_bytes: INITIAL_DECODE_ESTIMATE_BYTES,
            partitions: None,
            commit_max_retries: 15,
            commit_metadata: None,
            limits: ProcessLimits::global().clone(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct CompactStats {
    pub files_considered: usize,
    pub partitions_compacted: usize,
    pub bins: usize,
    pub files_removed: usize,
    pub files_added: usize,
    pub bytes_removed: u64,
    pub bytes_added: u64,
    pub rows_rewritten: usize,
    pub plan_ms: u64,
    pub rewrite_ms: u64,
    pub commit_ms: u64,
    /// Version of the compaction commit, or the table version when nothing was compacted.
    pub version: i64,
}

/// One partition's files, in log order, with the value that routes rows back to it.
struct PartitionFiles {
    value: Option<String>,
    files: Vec<TargetFile>,
}

struct Bin {
    value: Option<String>,
    files: Vec<TargetFile>,
}

/// delta-rs's `plan_compaction_bins_in_stable_order`: neighbours are packed until the next
/// file would push the bin past `target`; a file at or above `target` is skipped and ends
/// the run around it; single-file bins are dropped because rewriting them changes nothing.
fn plan_bins(partition: PartitionFiles, target: u64) -> Vec<Bin> {
    let mut bins: Vec<Bin> = Vec::new();
    let mut current: Vec<TargetFile> = Vec::new();
    let mut current_size = 0u64;
    let flush = |current: &mut Vec<TargetFile>, bins: &mut Vec<Bin>| {
        if current.len() >= 2 {
            bins.push(Bin {
                value: partition.value.clone(),
                files: std::mem::take(current),
            });
        } else {
            current.clear();
        }
    };
    for f in partition.files {
        if f.size > target {
            flush(&mut current, &mut bins);
            current_size = 0;
            continue;
        }
        if !current.is_empty() && current_size + f.size > target {
            flush(&mut current, &mut bins);
            current_size = 0;
        }
        current_size += f.size;
        current.push(f);
    }
    flush(&mut current, &mut bins);
    bins
}

async fn list_partitions(
    table: &DeltaTable,
    partition_col: Option<&str>,
    only: Option<&[String]>,
) -> Result<(usize, Vec<PartitionFiles>)> {
    let views: Vec<_> = table
        .get_active_add_actions_by_partitions(&[])
        .try_collect()
        .await?;
    let considered = views.len();
    let mut order: Vec<Option<String>> = Vec::new();
    let mut by_value: HashMap<Option<String>, Vec<TargetFile>> = HashMap::new();
    for v in views {
        let remove = v.remove_action(false);
        let value = partition_col.and_then(|c| {
            remove
                .partition_values
                .as_ref()
                .and_then(|pv| pv.get(c).cloned().flatten())
        });
        if let (Some(only), Some(val)) = (only, value.as_ref()) {
            if !only.iter().any(|o| o == val) {
                continue;
            }
        }
        let entry = by_value.entry(value.clone()).or_insert_with(|| {
            order.push(value.clone());
            Vec::new()
        });
        entry.push(TargetFile {
            path: v.path().to_string(),
            size: v.size() as u64,
            stats: None,
            remove,
            metadata: None,
        });
    }
    let partitions = order
        .into_iter()
        .map(|value| {
            let files = by_value.remove(&value).unwrap_or_default();
            PartitionFiles { value, files }
        })
        .collect();
    Ok((considered, partitions))
}

struct BinOutcome {
    actions: Vec<Action>,
    files_added: usize,
    files_removed: usize,
    bytes_added: u64,
    bytes_removed: u64,
    rows: usize,
}

async fn rewrite_bin(
    table: DeltaTable,
    bin: Bin,
    table_schema: arrow_schema::SchemaRef,
    partition_col: Option<String>,
    opts: Arc<CompactOptions>,
    budgets: Budgets,
    target_file_size: usize,
) -> Result<BinOutcome> {
    let store: Arc<dyn ObjectStore> = table.object_store();
    let mut writer = StreamingWriter::for_table(&table)?
        .with_compression(Compression::ZSTD(ZstdLevel::default()));
    let mut adds = Vec::new();
    let mut removes = Vec::with_capacity(bin.files.len());
    let mut rows = 0usize;
    let mut bytes_removed = 0u64;

    // Files are read one after another so the output keeps the bin's row order, and so a
    // bin holds at most one reader's fetched row group at a time.
    for f in bin.files {
        let builder = open_builder(&store, &f).await?;
        let fetch = budgets
            .acquire_fetch(max_row_group_fetch_bytes(builder.metadata(), None))
            .await?;
        let batch_rows =
            byte_bounded_batch_rows(builder.metadata(), opts.decode_batch_bytes, opts.read_batch_size);
        let mut stream = builder.with_batch_size(batch_rows).build()?;
        let mut estimate = opts.decode_batch_bytes;
        loop {
            let mut permit = budgets.acquire_bytes(estimate).await?;
            let Some(batch) = stream.try_next().await? else {
                break;
            };
            let actual = batch.get_array_memory_size();
            budgets.top_up(&mut permit, actual).await?;
            estimate = actual.max(64 * 1024);
            rows += batch.num_rows();
            let batch = match (&partition_col, &bin.value) {
                (Some(c), Some(v)) => add_partition_column(&batch, c, v)?,
                _ => batch,
            };
            writer.write(cast_to_schema(&batch, &table_schema)?)?;
            drop(permit);
            if writer.buffer_len() >= target_file_size {
                adds.extend(writer.flush().await?);
            }
        }
        drop(stream);
        drop(fetch);
        bytes_removed += f.size;
        removes.push(Action::Remove(f.remove));
    }
    adds.extend(writer.flush().await?);

    let files_added = adds.len();
    let bytes_added = adds.iter().map(|a| a.size.max(0) as u64).sum();
    let files_removed = removes.len();
    let mut actions = removes;
    actions.extend(adds.into_iter().map(|mut a| {
        a.data_change = false;
        Action::Add(a)
    }));
    Ok(BinOutcome {
        actions,
        files_added,
        files_removed,
        bytes_added,
        bytes_removed,
        rows,
    })
}

/// Compact small files of `table` and commit the result as one OPTIMIZE commit.
/// Returns the stats and, when a commit was made, the resulting state.
pub async fn compact(
    table: &DeltaTable,
    opts: CompactOptions,
) -> Result<(CompactStats, Option<DeltaTableState>)> {
    let plan_started = Instant::now();
    let snapshot = table.snapshot()?;
    ensure_supported_table(table)?;
    let target_file_size = resolve_target_file_size(
        opts.target_file_size,
        snapshot.table_config().target_file_size().get() as usize,
    );
    let table_schema = RecordBatchWriter::for_table(table)?.arrow_schema();
    let partition_columns: Vec<String> = snapshot.metadata().partition_columns().to_vec();
    if partition_columns.len() > 1 {
        return Err(Error::Unsupported(format!(
            "deltalite supports at most one partition column, table has {partition_columns:?}"
        )));
    }
    let partition_col = partition_columns.first().cloned();

    let (considered, partitions) =
        list_partitions(table, partition_col.as_deref(), opts.partitions.as_deref()).await?;
    let mut bins: Vec<Bin> = Vec::new();
    let mut compacted_partitions = 0usize;
    for p in partitions {
        let planned = plan_bins(p, target_file_size as u64);
        if !planned.is_empty() {
            compacted_partitions += 1;
        }
        bins.extend(planned);
    }
    let mut stats = CompactStats {
        files_considered: considered,
        partitions_compacted: compacted_partitions,
        bins: bins.len(),
        plan_ms: plan_started.elapsed().as_millis() as u64,
        ..Default::default()
    };
    if bins.is_empty() {
        stats.version = snapshot.version() as i64;
        return Ok((stats, None));
    }

    let rewrite_started = Instant::now();
    let budgets = Budgets::new(
        opts.max_buffered_bytes,
        opts.max_fetch_bytes,
        opts.limits.clone(),
    );
    let opts = Arc::new(opts);
    let sem = Arc::new(Semaphore::new(opts.max_parallel_bins.max(1)));
    let mut handles = Vec::with_capacity(bins.len());
    for bin in bins {
        let local = sem
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| Error::Generic("bin semaphore closed".into()))?;
        let global = opts.limits.acquire_partition().await?;
        let fut = rewrite_bin(
            table.clone(),
            bin,
            table_schema.clone(),
            partition_col.clone(),
            opts.clone(),
            budgets.clone(),
            target_file_size,
        );
        handles.push(tokio::spawn(async move {
            let r = fut.await;
            drop(local);
            drop(global);
            r
        }));
    }
    let mut actions = Vec::new();
    for h in handles {
        let o = h
            .await
            .map_err(|e| Error::Generic(format!("compaction worker panicked: {e}")))??;
        stats.files_added += o.files_added;
        stats.files_removed += o.files_removed;
        stats.bytes_added += o.bytes_added;
        stats.bytes_removed += o.bytes_removed;
        stats.rows_rewritten += o.rows;
        actions.extend(o.actions);
    }
    stats.rewrite_ms = rewrite_started.elapsed().as_millis() as u64;

    let commit_started = Instant::now();
    let mut props = CommitProperties::default()
        .with_max_retries(opts.commit_max_retries)
        .with_create_checkpoint(false)
        .with_cleanup_expired_logs(Some(false));
    if let Some(md) = opts.commit_metadata.clone() {
        props = props.with_metadata(md);
    }
    let checkpoint_interval = snapshot.table_config().checkpoint_interval().get();
    let cleanup_enabled = snapshot.table_config().enable_expired_log_cleanup();
    let finalized = CommitBuilder::from(props)
        .with_actions(actions)
        .build(
            Some(snapshot),
            table.log_store(),
            DeltaOperation::Optimize {
                predicate: None,
                target_size: target_file_size as i64,
            },
        )
        .await?;
    stats.commit_ms = commit_started.elapsed().as_millis() as u64;
    if (finalized.version() + 1) % checkpoint_interval == 0 {
        best_effort_log_maintenance(table, finalized.version(), cleanup_enabled).await;
    }
    stats.version = i64::try_from(finalized.version())
        .map_err(|_| Error::Generic("committed version overflows i64".into()))?;
    info!(
        version = stats.version,
        bins = stats.bins,
        files_removed = stats.files_removed,
        files_added = stats.files_added,
        plan_ms = stats.plan_ms,
        rewrite_ms = stats.rewrite_ms,
        commit_ms = stats.commit_ms,
        "compaction committed"
    );
    Ok((stats, Some(finalized.snapshot)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use deltalake::kernel::Remove;

    fn file(size: u64) -> TargetFile {
        TargetFile {
            path: format!("f{size}"),
            size,
            stats: None,
            remove: Remove {
                path: String::new(),
                data_change: false,
                deletion_timestamp: None,
                extended_file_metadata: None,
                partition_values: None,
                size: None,
                tags: None,
                deletion_vector: None,
                base_row_id: None,
                default_row_commit_version: None,
            },
            metadata: None,
        }
    }

    fn sizes(bins: &[Bin]) -> Vec<Vec<u64>> {
        bins.iter()
            .map(|b| b.files.iter().map(|f| f.size).collect())
            .collect()
    }

    #[test]
    fn bins_pack_neighbours_skip_large_files_and_drop_singletons() {
        let p = PartitionFiles {
            value: None,
            files: [10, 20, 80, 30, 200, 5, 6, 7, 100]
                .into_iter()
                .map(file)
                .collect(),
        };
        // 10+20 fit, 80 would overflow; 80+... 30 overflows -> [80] alone is dropped, [30]
        // ends at the oversized 200; [5,6,7] packs; the last file is exactly the target.
        assert_eq!(
            sizes(&plan_bins(p, 100)),
            vec![vec![10, 20], vec![5, 6, 7]]
        );
    }

    #[test]
    fn one_file_per_partition_plans_nothing() {
        let p = PartitionFiles {
            value: Some("a".into()),
            files: vec![file(10)],
        };
        assert!(plan_bins(p, 100).is_empty());
    }
}
