//! Incremental SCD2 history upsert.
//!
//! The table holds one row per version of a key. Open versions (`valid_to` null) live in
//! the `current` partition; a closed version lives in the `%Y-%m` (UTC) month partition of
//! its `valid_to`. [`history_upsert`] applies a source batch of versions in one data commit:
//!
//! 1. Rows with the same (key, order value) collapse to the one with the highest tie-break
//!    value.
//! 2. Only rows strictly newer than the key's open row are kept. A row equal to it is a
//!    re-read, an older one is a backwards row; both are dropped and counted.
//! 3. The kept rows of a key form a chain: each closes at the next kept row's
//!    `valid_from`, and the newest stays open in `current`.
//! 4. When a key keeps a row and has an open row, the open row closes at the first kept
//!    row's `valid_from` and moves to its month partition.
//!
//! Keys are null-safe: a null key part matches a null key part. A null order value or a
//! null `valid_from` is an error. Closed rows are only ever appended, so earlier closed
//! versions of a key in the same month stay. A source that keeps nothing (a re-run of the
//! same input) writes nothing and makes no commit.
//!
//! The machinery is the upsert's (see [`crate::upsert`]): the same listing, stats pruning,
//! budgets, writer and commit. Two things differ. The probe reads the order column next to
//! the keys, so a file that holds only re-read keys is not rewritten, and it reads every
//! candidate file in full, because the open order of every source key must be known
//! before the kept rows are chosen. The probe cache is not used, because its entries
//! record keys only.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

use arrow_array::cast::AsArray;
use arrow_array::{
    new_null_array, Array, ArrayRef, BooleanArray, RecordBatch, StringArray, UInt32Array,
};
use arrow_cast::{cast_with_options, CastOptions};
use arrow_ord::sort::sort_to_indices;
use arrow_row::{RowConverter, Rows, SortField};
use arrow_schema::{DataType, Field, Schema, SchemaRef, TimeUnit};
use arrow_select::concat::concat;
use arrow_select::filter::{filter, filter_record_batch};
use arrow_select::interleave::interleave_record_batch;
use arrow_select::take::{take, take_record_batch};
use chrono::{DateTime, NaiveDate, Utc};
use deltalake::kernel::{Action, Add};
use deltalake::table::config::TablePropertiesExt;
use deltalake::table::state::DeltaTableState;
use deltalake::writer::RecordBatchWriter;
use deltalake::{DeltaTable, ObjectStore};
use futures::{StreamExt, TryStreamExt};
use metrics::{counter, histogram};
use parquet::arrow::ProjectionMask;
use parquet::file::metadata::ParquetMetaData;
use serde_json::Value;
use tokio::sync::{mpsc, Semaphore};
use tracing::info;

use crate::errors::{Error, Result};
use crate::limits::{
    check_source_size, estimate_pk_set_bytes, resolve_max_source_bytes, ProcessLimits,
    SourceFootprint,
};
use crate::schema::cast_to_schema;
use crate::upsert::{
    add_partition_column, byte_bounded_batch_rows, columns_needing_relax,
    commit_partition_overwrite, ensure_supported_table, json_cmp, list_files_by_partition,
    max_row_group_fetch_bytes, min_max_json, open_builder, open_rewrite_stream,
    relax_columns_to_nullable, resolve_target_file_size, roll_writer, source_slice_rows,
    BudgetPermit, Budgets, RelaxCache, TargetFile, DEFAULT_MAX_FETCH_BYTES,
    INITIAL_PROBE_ESTIMATE_BYTES,
};
use crate::writer::StreamingWriter;

/// Seed of the [`key_buckets`] hash. Part of the API: changing it moves every key to a
/// different bucket.
pub const KEY_BUCKET_SEED: u64 = 0x6465_6c74_616c_6974;

#[derive(Clone)]
pub struct HistoryUpsertOptions {
    /// Columns that identify a key, in order. Compared null-safely.
    pub key_columns: Vec<String>,
    /// Column that orders the versions of a key. Must not be null.
    pub order_column: String,
    /// Column with the instant a version starts. Must not be null. It is the `valid_to`
    /// of the version it replaces.
    pub valid_from_column: String,
    /// Column with the instant a version ends, null while it is open. Set by the
    /// operation; the source must not carry it.
    pub valid_to_column: String,
    /// The table's only partition column (string). Set by the operation; the source must
    /// not carry it.
    pub partition_column: String,
    /// Partition value of the open versions.
    pub current_partition: String,
    /// Source column that decides between rows with the same (key, order value): the
    /// highest value wins. Must have a fixed-width type, such as an integer or a timestamp.
    /// Dropped before writing when the table has no such column.
    pub tie_break_column: String,
    pub commit_metadata: Option<HashMap<String, Value>>,
    pub probe_concurrency: usize,
    pub max_parallel_files: usize,
    pub max_buffered_bytes: usize,
    pub max_fetch_bytes: usize,
    pub read_ahead_row_groups: bool,
    pub read_batch_size: usize,
    /// `None` uses the table's `delta.targetFileSize`.
    pub target_file_size: Option<usize>,
    pub max_row_group_bytes: Option<usize>,
    /// Ceiling for the source-size guard; `None` resolves from the environment, `Some(0)`
    /// disables. See [`crate::limits::resolve_max_source_bytes`].
    pub max_source_bytes: Option<usize>,
    pub limits: Arc<ProcessLimits>,
}

impl Default for HistoryUpsertOptions {
    fn default() -> Self {
        Self {
            key_columns: Vec::new(),
            order_column: String::new(),
            valid_from_column: String::new(),
            valid_to_column: String::new(),
            partition_column: String::new(),
            current_partition: String::new(),
            tie_break_column: String::new(),
            commit_metadata: None,
            probe_concurrency: 8,
            max_parallel_files: 4,
            max_buffered_bytes: 64 * 1024 * 1024,
            max_fetch_bytes: DEFAULT_MAX_FETCH_BYTES,
            read_ahead_row_groups: false,
            read_batch_size: 8192,
            target_file_size: None,
            max_row_group_bytes: None,
            max_source_bytes: None,
            limits: ProcessLimits::global().clone(),
        }
    }
}

#[derive(Default, Debug, Clone)]
pub struct HistoryUpsertStats {
    /// The committed table version, or the version the call read when it made no commit.
    pub version: i64,
    /// Whether the call made a data commit. False when the source kept no row.
    pub committed: bool,
    pub rows_in: usize,
    /// Source rows dropped because another row had the same (key, order value) and a
    /// higher tie-break value.
    pub rows_deduped: usize,
    /// Source rows whose order value equals the key's open row.
    pub rows_reread: usize,
    /// Source rows whose order value is lower than the key's open row.
    pub rows_backwards: usize,
    /// Open versions written (one per key that kept a row).
    pub versions_opened: usize,
    /// Existing open rows closed and moved to their month partition.
    pub versions_closed: usize,
    /// Kept source rows written already closed (every kept row but the newest of a key).
    pub chain_rows_closed: usize,
    /// Open rows copied unchanged into new files of the current partition.
    pub rows_copied: usize,
    pub files_removed: usize,
    pub files_added: usize,
    /// Current-partition files left untouched.
    pub files_carried_over: usize,
    /// Current-partition files whose key and order columns the probe read.
    pub files_probed: usize,
    /// Stored bytes of the rewritten files (the probe's narrow reads are not counted).
    pub bytes_read: u64,
    pub bytes_written: u64,
    pub plan_ms: u64,
    pub probe_ms: u64,
    pub rewrite_ms: u64,
    pub commit_ms: u64,
    pub columns_relaxed: usize,
    pub open_ms: u64,
    pub initial_open_ms: u64,
    pub ingest_ms: u64,
    pub relax_ms: u64,
    pub maintenance_ms: u64,
}

/// Apply `source_batches` to the history table `table`. See the module docs.
pub async fn history_upsert(
    table: &DeltaTable,
    source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: HistoryUpsertOptions,
) -> Result<HistoryUpsertStats> {
    history_upsert_with_state(
        table,
        source_batches,
        source_schema,
        opts,
        &mut RelaxCache::default(),
    )
    .await
    .map(|(stats, _)| stats)
}

/// [`history_upsert`] that also returns the table state after the call, for a handle to
/// adopt. `None` when the table did not move.
pub async fn history_upsert_with_state(
    table: &DeltaTable,
    source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: HistoryUpsertOptions,
    relax_cache: &mut RelaxCache,
) -> Result<(HistoryUpsertStats, Option<DeltaTableState>)> {
    let started = Instant::now();
    let result = history_with_relax(table, source_batches, source_schema, opts, relax_cache).await;
    histogram!("deltalite_history_upsert_duration_seconds").record(started.elapsed().as_secs_f64());
    match &result {
        Ok((stats, _)) => {
            let outcome = if stats.committed { "ok" } else { "noop" };
            counter!("deltalite_history_upserts_total", "outcome" => outcome).increment(1);
            counter!("deltalite_history_versions_closed_total")
                .increment((stats.versions_closed + stats.chain_rows_closed) as u64);
            counter!("deltalite_history_versions_opened_total")
                .increment(stats.versions_opened as u64);
        }
        Err(e) => {
            counter!(
                "deltalite_history_upserts_total",
                "outcome" => "error",
                "error_kind" => e.kind()
            )
            .increment(1);
        }
    }
    result
}

async fn history_with_relax(
    table: &DeltaTable,
    source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: HistoryUpsertOptions,
    relax_cache: &mut RelaxCache,
) -> Result<(HistoryUpsertStats, Option<DeltaTableState>)> {
    // Before the relax, so an unsupported table or source never makes a metadata commit.
    ensure_history_table(table, &opts)?;
    validate_source(table, &source_batches, &source_schema, &opts)?;
    let relax_started = Instant::now();
    let mut relax =
        columns_needing_relax(table, &source_batches, &source_schema, relax_cache).await?;
    // The source never carries the partition column, but every written row sets it.
    relax.retain(|c| c != &opts.partition_column);
    if relax.is_empty() {
        let relax_ms = relax_started.elapsed().as_millis() as u64;
        let (mut stats, state) =
            history_inner(table, source_batches, source_schema, &opts, false).await?;
        stats.relax_ms = relax_ms;
        if stats.committed {
            if let Ok(committed) = u64::try_from(stats.version) {
                relax_cache.advance_own_commit(committed);
            }
        }
        return Ok((stats, state));
    }

    // Plan first, so a call that keeps no row makes no commit at all, not even the relax.
    let (planned, _) = history_inner(
        table,
        source_batches.clone(),
        source_schema.clone(),
        &opts,
        true,
    )
    .await?;
    if planned.versions_opened == 0 {
        return Ok((planned, None));
    }
    relax_columns_to_nullable(table, &relax).await?;
    let mut fresh = table.clone();
    fresh.update_incremental(None).await?;
    let relax_ms = relax_started.elapsed().as_millis() as u64;
    let (mut stats, state) =
        history_inner(&fresh, source_batches, source_schema, &opts, false).await?;
    stats.columns_relaxed = relax.len();
    stats.relax_ms = relax_ms;
    // A concurrent commit can still make the data a no-op after the relax landed.
    Ok((stats, state.or(fresh.state)))
}

fn validate_source(
    table: &DeltaTable,
    source_batches: &[RecordBatch],
    source_schema: &SchemaRef,
    opts: &HistoryUpsertOptions,
) -> Result<()> {
    let table_schema = RecordBatchWriter::for_table(table)?.arrow_schema();
    Columns::resolve(&table_schema, source_schema, opts)?;
    for (role, column) in [
        ("order", &opts.order_column),
        ("valid_from", &opts.valid_from_column),
    ] {
        let idx = source_schema.index_of(column)?;
        let nulls: usize = source_batches
            .iter()
            .map(|b| b.column(idx).logical_null_count())
            .sum();
        if nulls > 0 {
            return Err(Error::Generic(format!(
                "{role} column '{column}' holds {nulls} null value(s); every history row needs one"
            )));
        }
    }
    Ok(())
}

fn ensure_history_table(table: &DeltaTable, opts: &HistoryUpsertOptions) -> Result<()> {
    ensure_supported_table(table)?;
    let snapshot = table.snapshot()?;
    let partition_columns = snapshot.metadata().partition_columns();
    if partition_columns.len() != 1 || partition_columns[0] != opts.partition_column {
        return Err(Error::Unsupported(format!(
            "history_upsert needs a table partitioned by exactly '{}', table is partitioned \
             by {partition_columns:?}",
            opts.partition_column
        )));
    }
    Ok(())
}

struct Columns {
    key_idx: Vec<usize>,
    order_idx: usize,
    valid_from_idx: usize,
    valid_to_idx: usize,
    partition_idx: usize,
    tie_source_idx: usize,
    /// The tie-break column is not a table column, so it is dropped before writing.
    strip_tie: bool,
}

impl Columns {
    fn resolve(
        table_schema: &SchemaRef,
        source_schema: &SchemaRef,
        opts: &HistoryUpsertOptions,
    ) -> Result<Self> {
        if opts.key_columns.is_empty() {
            return Err(Error::Generic(
                "key_columns must not be empty for a history upsert".into(),
            ));
        }
        if is_month_name(&opts.current_partition) || opts.current_partition.is_empty() {
            return Err(Error::Generic(format!(
                "current_partition '{}' must be non-empty and must not look like a month \
                 partition (YYYY-MM)",
                opts.current_partition
            )));
        }
        let set_by_operation = [&opts.valid_to_column, &opts.partition_column];
        let table_idx = |name: &str, role: &str| {
            table_schema.index_of(name).map_err(|_| {
                Error::SchemaMismatch(format!("{role} column '{name}' not found in table schema"))
            })
        };
        let source_column = |name: &str, role: &str| -> Result<usize> {
            if set_by_operation.iter().any(|c| c.as_str() == name) {
                return Err(Error::Generic(format!(
                    "'{name}' is set by history_upsert and cannot be the {role} column"
                )));
            }
            source_schema.index_of(name).map_err(|_| {
                Error::SchemaMismatch(format!("{role} column '{name}' is missing from the source"))
            })?;
            table_idx(name, role)
        };

        let mut key_idx = Vec::with_capacity(opts.key_columns.len());
        for k in &opts.key_columns {
            key_idx.push(source_column(k, "key")?);
        }
        let order_idx = source_column(&opts.order_column, "order")?;
        let valid_from_idx = source_column(&opts.valid_from_column, "valid_from")?;
        let valid_to_idx = table_idx(&opts.valid_to_column, "valid_to")?;
        let partition_idx = table_idx(&opts.partition_column, "partition")?;

        for c in set_by_operation {
            if source_schema.index_of(c).is_ok() {
                return Err(Error::SchemaMismatch(format!(
                    "source carries column '{c}', which history_upsert sets itself"
                )));
            }
        }
        if set_by_operation.contains(&&opts.tie_break_column) {
            return Err(Error::Generic(format!(
                "tie-break column '{}' is set by history_upsert",
                opts.tie_break_column
            )));
        }
        let tie_source_idx = source_schema
            .index_of(&opts.tie_break_column)
            .map_err(|_| {
                Error::SchemaMismatch(format!(
                    "tie-break column '{}' is missing from the source",
                    opts.tie_break_column
                ))
            })?;
        // Fixed width only: the size guard counts in-memory bytes, and a dictionary or
        // view column can encode to many times that when every row is row-encoded.
        let tie_type = source_schema.field(tie_source_idx).data_type();
        if !tie_type.is_primitive() {
            return Err(Error::SchemaMismatch(format!(
                "tie-break column '{}' must have a fixed-width type such as an integer or a \
                 timestamp, source has {tie_type}",
                opts.tie_break_column
            )));
        }
        let strip_tie = table_schema.index_of(&opts.tie_break_column).is_err();

        let extra: Vec<&String> = source_schema
            .fields()
            .iter()
            .map(|f| f.name())
            .filter(|n| **n != opts.tie_break_column && table_schema.index_of(n).is_err())
            .collect();
        if !extra.is_empty() {
            return Err(Error::SchemaMismatch(format!(
                "source has columns not present in the table schema: {extra:?}. \
                 Additive schema evolution must run before history_upsert."
            )));
        }

        if !matches!(
            table_schema.field(partition_idx).data_type(),
            DataType::Utf8 | DataType::LargeUtf8 | DataType::Utf8View
        ) {
            return Err(Error::Unsupported(format!(
                "history partition column '{}' must be a string column, table has {}",
                opts.partition_column,
                table_schema.field(partition_idx).data_type()
            )));
        }
        let valid_to_type = table_schema.field(valid_to_idx).data_type();
        if !matches!(
            valid_to_type,
            DataType::Timestamp(_, _) | DataType::Date32 | DataType::Date64
        ) {
            return Err(Error::SchemaMismatch(format!(
                "valid_to column '{}' must be a date or timestamp column, table has {valid_to_type}",
                opts.valid_to_column
            )));
        }
        Ok(Self {
            key_idx,
            order_idx,
            valid_from_idx,
            valid_to_idx,
            partition_idx,
            tie_source_idx,
            strip_tie,
        })
    }
}

enum FirstKeyRange {
    NoValues,
    /// Min and max of the non-null values, comparable against Add-action stats.
    Range(Value, Value),
    Unknown,
}

/// The source, encoded and deduped. Shared read-only by every probe and reader task.
struct SourcePlan {
    /// Source batches cast to the table schema, with `valid_to` and the partition column
    /// null until the rows are written.
    batches: Vec<RecordBatch>,
    offsets: Vec<usize>,
    key_converter: RowConverter,
    order_converter: RowConverter,
    /// Order value of every source row, as order-preserving bytes.
    orders: Rows,
    /// Every source row's `valid_from`, cast to the table's `valid_to` type.
    valid_from: ArrayRef,
    /// One global row per (key, order value), sorted by key, then order value.
    deduped: Vec<u32>,
    /// Range of `deduped` that holds each key, in key order. A key's index here is its id.
    groups: Vec<(u32, u32)>,
    by_key: HashMap<Box<[u8]>, u32>,
    first_key: FirstKeyRange,
    first_key_has_null: bool,
    rows_in: usize,
}

impl SourcePlan {
    fn build(
        source_batches: Vec<RecordBatch>,
        table_schema: &SchemaRef,
        cols: &Columns,
        opts: &HistoryUpsertOptions,
    ) -> Result<Self> {
        let work_schema = nullable_schema(table_schema);
        let mut batches = Vec::with_capacity(source_batches.len());
        let mut ties = Vec::with_capacity(source_batches.len());
        let mut offsets = Vec::with_capacity(source_batches.len());
        let mut rows_in = 0usize;
        for b in source_batches {
            ties.push(b.column(cols.tie_source_idx).clone());
            let b = if cols.strip_tie {
                let keep: Vec<usize> = (0..b.num_columns())
                    .filter(|i| *i != cols.tie_source_idx)
                    .collect();
                b.project(&keep)?
            } else {
                b
            };
            offsets.push(rows_in);
            rows_in += b.num_rows();
            batches.push(cast_to_schema(&b, &work_schema)?);
        }
        if rows_in > u32::MAX as usize {
            return Err(Error::Generic(format!(
                "source has {rows_in} rows, more than a history upsert supports"
            )));
        }

        // Guard before the narrow columns are copied out, and count those copies: the
        // key, order, tie-break and `valid_from` arrays plus the key encodings.
        let column_bytes = |idx: usize| -> usize {
            batches
                .iter()
                .map(|b| b.column(idx).get_array_memory_size())
                .sum()
        };
        let tie_bytes: usize = ties.iter().map(|t| t.get_array_memory_size()).sum();
        let narrow_bytes = cols.key_idx.iter().map(|i| column_bytes(*i)).sum::<usize>() * 2
            + column_bytes(cols.order_idx)
            + column_bytes(cols.valid_from_idx)
            + tie_bytes;
        let footprint = SourceFootprint {
            source_bytes: batches
                .iter()
                .map(RecordBatch::get_array_memory_size)
                .sum::<usize>()
                + tie_bytes,
            pk_set_bytes: estimate_pk_set_bytes(narrow_bytes, rows_in)
                .saturating_add(rows_in.saturating_mul(2 * size_of::<u32>())),
        };
        check_source_size(&footprint, resolve_max_source_bytes(opts.max_source_bytes))?;

        let column = |idx: usize| -> Result<ArrayRef> {
            let parts: Vec<&dyn Array> = batches.iter().map(|b| b.column(idx).as_ref()).collect();
            if parts.is_empty() {
                return Ok(new_null_array(table_schema.field(idx).data_type(), 0));
            }
            Ok(concat(&parts)?)
        };
        let keys: Vec<ArrayRef> = cols
            .key_idx
            .iter()
            .map(|i| column(*i))
            .collect::<Result<_>>()?;
        let order = column(cols.order_idx)?;
        let tie: ArrayRef = match ties.len() {
            0 => new_null_array(&DataType::Null, 0),
            _ => concat(&ties.iter().map(|t| t.as_ref()).collect::<Vec<_>>())?,
        };

        let valid_from = column(cols.valid_from_idx)?;
        let valid_from = cast_strict(
            &valid_from,
            table_schema.field(cols.valid_to_idx).data_type(),
        )?;

        let key_converter = RowConverter::new(
            keys.iter()
                .map(|k| SortField::new(k.data_type().clone()))
                .collect(),
        )?;
        let order_converter = RowConverter::new(vec![SortField::new(order.data_type().clone())])?;
        let tie_converter = RowConverter::new(vec![SortField::new(tie.data_type().clone())])?;
        let key_rows = key_converter.convert_columns(&keys)?;
        let orders = order_converter.convert_columns(std::slice::from_ref(&order))?;
        let tie_rows = tie_converter.convert_columns(std::slice::from_ref(&tie))?;

        let first_key_has_null = keys[0].null_count() > 0;
        let first_key = if keys[0].null_count() == keys[0].len() {
            FirstKeyRange::NoValues
        } else {
            match min_max_json(keys[0].as_ref()) {
                Some((min, max)) => FirstKeyRange::Range(min, max),
                None => FirstKeyRange::Unknown,
            }
        };
        drop(keys);

        // A stable sort keeps input order among rows equal on all three, so the last
        // staged row of a (key, order value) still wins a tie on the tie-break value.
        let mut sorted: Vec<u32> = (0..rows_in as u32).collect();
        sorted.sort_by(|&a, &b| {
            let (a, b) = (a as usize, b as usize);
            key_rows
                .row(a)
                .as_ref()
                .cmp(key_rows.row(b).as_ref())
                .then_with(|| orders.row(a).as_ref().cmp(orders.row(b).as_ref()))
                .then_with(|| tie_rows.row(a).as_ref().cmp(tie_rows.row(b).as_ref()))
        });
        drop(tie_rows);

        let mut deduped = Vec::with_capacity(sorted.len());
        let mut groups = Vec::new();
        let mut by_key = HashMap::new();
        let mut i = 0usize;
        while i < sorted.len() {
            let key = key_rows.row(sorted[i] as usize);
            let mut end = i + 1;
            while end < sorted.len() && key_rows.row(sorted[end] as usize).as_ref() == key.as_ref()
            {
                end += 1;
            }
            let start = deduped.len() as u32;
            for t in i..end {
                let last_of_order = t + 1 == end
                    || orders.row(sorted[t] as usize).as_ref()
                        != orders.row(sorted[t + 1] as usize).as_ref();
                if last_of_order {
                    deduped.push(sorted[t]);
                }
            }
            by_key.insert(Box::<[u8]>::from(key.as_ref()), groups.len() as u32);
            groups.push((start, deduped.len() as u32));
            i = end;
        }

        Ok(Self {
            batches,
            offsets,
            key_converter,
            order_converter,
            orders,
            valid_from,
            deduped,
            groups,
            by_key,
            first_key,
            first_key_has_null,
            rows_in,
        })
    }

    fn order(&self, row: u32) -> &[u8] {
        self.orders.row(row as usize).data()
    }

    fn newest_order(&self, group: u32) -> &[u8] {
        let (_, end) = self.groups[group as usize];
        self.order(self.deduped[end as usize - 1])
    }

    fn locate(&self, row: u32) -> (usize, usize) {
        let row = row as usize;
        let batch = self.offsets.partition_point(|start| *start <= row) - 1;
        (batch, row - self.offsets[batch])
    }

    /// Choose the kept rows of every key against the open order values the probe found.
    fn decide(&self, open: &[Option<Box<[u8]>>]) -> Decision {
        let mut d = Decision {
            closing: vec![None; self.groups.len()],
            writes: Vec::new(),
            rows_reread: 0,
            rows_backwards: 0,
            versions_opened: 0,
            chain_rows_closed: 0,
        };
        for (group, &(start, end)) in self.groups.iter().enumerate() {
            let rows = &self.deduped[start as usize..end as usize];
            let kept_from = match &open[group] {
                None => 0,
                Some(open) => {
                    let kept_from = rows.partition_point(|r| self.order(*r) <= open.as_ref());
                    for r in &rows[..kept_from] {
                        if self.order(*r) == open.as_ref() {
                            d.rows_reread += 1;
                        } else {
                            d.rows_backwards += 1;
                        }
                    }
                    kept_from
                }
            };
            let kept = &rows[kept_from..];
            let Some(first) = kept.first() else {
                continue;
            };
            d.versions_opened += 1;
            d.chain_rows_closed += kept.len() - 1;
            if open[group].is_some() {
                d.closing[group] = Some(*first);
            }
            for (t, r) in kept.iter().enumerate() {
                d.writes.push((*r, kept.get(t + 1).copied()));
            }
        }
        d
    }
}

/// A kept source row and the next kept row of its key, whose `valid_from` closes it
/// (`None` for the newest, which stays open).
type KeptRow = (u32, Option<u32>);

struct Decision {
    /// Per key: the source row whose `valid_from` closes the key's open row.
    closing: Vec<Option<u32>>,
    /// Kept source rows in write order.
    writes: Vec<KeptRow>,
    rows_reread: usize,
    rows_backwards: usize,
    versions_opened: usize,
    chain_rows_closed: usize,
}

/// The table schema with every column nullable. Source batches are held in it until they
/// are written: the operation sets `valid_to` and the partition column later, and a
/// column the table still marks non-nullable may hold nulls until the relax commits.
/// Written batches are rebuilt in the table schema, which checks nullability again.
fn nullable_schema(table_schema: &SchemaRef) -> SchemaRef {
    let fields: Vec<Field> = table_schema
        .fields()
        .iter()
        .map(|f| f.as_ref().clone().with_nullable(true))
        .collect();
    Arc::new(Schema::new_with_metadata(
        fields,
        table_schema.metadata().clone(),
    ))
}

fn cast_strict(array: &ArrayRef, to: &DataType) -> Result<ArrayRef> {
    if array.data_type() == to {
        return Ok(array.clone());
    }
    let opts = CastOptions {
        safe: false,
        ..Default::default()
    };
    Ok(cast_with_options(array, to, &opts)?)
}

/// `%Y-%m` of each value in UTC, null for null. Must equal pyarrow's
/// `pc.strftime(values, "%Y-%m")` for UTC timestamps, which is how callers name the
/// month partitions they read.
pub fn format_months(values: &dyn Array) -> Result<StringArray> {
    let raw = |to: &DataType| arrow_cast::cast(&arrow_array::make_array(values.to_data()), to);
    let instants: Vec<Option<DateTime<Utc>>> = match values.data_type() {
        DataType::Timestamp(unit, _) => {
            let raw = raw(&DataType::Int64)?;
            let raw = raw
                .as_any()
                .downcast_ref::<arrow_array::Int64Array>()
                .ok_or_else(|| Error::Generic("timestamp did not cast to Int64".into()))?;
            raw.iter()
                .map(|v| {
                    v.map(|v| {
                        match unit {
                            TimeUnit::Second => DateTime::from_timestamp(v, 0),
                            TimeUnit::Millisecond => DateTime::from_timestamp_millis(v),
                            TimeUnit::Microsecond => DateTime::from_timestamp_micros(v),
                            TimeUnit::Nanosecond => Some(DateTime::from_timestamp_nanos(v)),
                        }
                        .ok_or_else(|| out_of_range(v))
                    })
                    .transpose()
                })
                .collect::<Result<_>>()?
        }
        DataType::Date32 => {
            let raw = raw(&DataType::Int32)?;
            let raw = raw
                .as_any()
                .downcast_ref::<arrow_array::Int32Array>()
                .ok_or_else(|| Error::Generic("date did not cast to Int32".into()))?;
            raw.iter()
                .map(|v| {
                    v.map(|days| {
                        NaiveDate::from_num_days_from_ce_opt(days.saturating_add(719_163))
                            .map(|d| d.and_time(chrono::NaiveTime::MIN).and_utc())
                            .ok_or_else(|| out_of_range(i64::from(days)))
                    })
                    .transpose()
                })
                .collect::<Result<_>>()?
        }
        DataType::Date64 => {
            let raw = raw(&DataType::Int64)?;
            let raw = raw
                .as_any()
                .downcast_ref::<arrow_array::Int64Array>()
                .ok_or_else(|| Error::Generic("date did not cast to Int64".into()))?;
            raw.iter()
                .map(|v| {
                    v.map(|ms| DateTime::from_timestamp_millis(ms).ok_or_else(|| out_of_range(ms)))
                        .transpose()
                })
                .collect::<Result<_>>()?
        }
        other => {
            return Err(Error::SchemaMismatch(format!(
                "cannot name a month partition from a {other} value"
            )))
        }
    };
    Ok(instants
        .into_iter()
        .map(|dt| dt.map(|dt| dt.format("%Y-%m").to_string()))
        .collect())
}

fn is_month_name(value: &str) -> bool {
    let b = value.as_bytes();
    b.len() == 7 && b[4] == b'-' && b[..4].iter().chain(&b[5..]).all(u8::is_ascii_digit)
}

fn out_of_range(v: i64) -> Error {
    Error::Generic(format!(
        "valid_to value {v} is outside the supported date range"
    ))
}

/// Set `valid_to` and the partition column of `batch` (in the table's column order).
/// Row `i` closes at the `valid_from` of source row `closes[i]` into that value's month;
/// a null entry leaves it open in `current`.
fn stamp_validity(
    batch: &RecordBatch,
    closes: &UInt32Array,
    plan: &SourcePlan,
    cols: &Columns,
    table_schema: &SchemaRef,
    current: &str,
) -> Result<RecordBatch> {
    let valid_to = take(plan.valid_from.as_ref(), closes, None)?;
    let months = format_months(valid_to.as_ref())?;
    let partition: StringArray = months.iter().map(|m| Some(m.unwrap_or(current))).collect();
    let partition: ArrayRef = Arc::new(partition);
    let partition = cast_strict(
        &partition,
        table_schema.field(cols.partition_idx).data_type(),
    )?;

    let mut columns = batch.columns().to_vec();
    columns[cols.valid_to_idx] = valid_to;
    columns[cols.partition_idx] = partition;
    Ok(RecordBatch::try_new(table_schema.clone(), columns)?)
}

/// Whether Add-action stats prove that `f` holds no source key. Null key parts match, so
/// a file is safe from a null source key only when its first key column has no nulls.
fn file_cannot_hold_source_key(f: &TargetFile, first_key: &str, plan: &SourcePlan) -> bool {
    let Some(stats) = &f.stats else { return false };
    let Ok(parsed) = serde_json::from_str::<Value>(stats) else {
        return false;
    };
    let records = parsed.get("numRecords").and_then(Value::as_i64);
    if records == Some(0) {
        return true;
    }
    let nulls = parsed
        .get("nullCount")
        .and_then(|n| n.get(first_key))
        .and_then(Value::as_i64);
    if plan.first_key_has_null && nulls != Some(0) {
        return false;
    }
    if records.is_some() && nulls == records {
        return true;
    }
    match &plan.first_key {
        FirstKeyRange::NoValues => true,
        FirstKeyRange::Unknown => false,
        FirstKeyRange::Range(src_min, src_max) => {
            let file_min = parsed.get("minValues").and_then(|m| m.get(first_key));
            let file_max = parsed.get("maxValues").and_then(|m| m.get(first_key));
            let (Some(file_min), Some(file_max)) = (file_min, file_max) else {
                return false;
            };
            matches!(json_cmp(file_max, src_min), Some(std::cmp::Ordering::Less))
                || matches!(
                    json_cmp(file_min, src_max),
                    Some(std::cmp::Ordering::Greater)
                )
        }
    }
}

/// The key and order columns of `batch` in the table's types. A column the batch does not
/// have reads as null, which a null key part of the source matches.
fn key_and_order_columns(
    batch: &RecordBatch,
    plan_types: &[(String, DataType)],
) -> Result<Vec<ArrayRef>> {
    plan_types
        .iter()
        .map(|(name, ty)| match batch.column_by_name(name) {
            Some(c) => cast_strict(c, ty),
            None => Ok(new_null_array(ty, batch.num_rows())),
        })
        .collect()
}

/// What the probe found in one file: the source keys it holds with their open order
/// values, and whether any of them has a newer source row.
struct FileProbe {
    file: TargetFile,
    seen: Vec<(u32, Box<[u8]>)>,
    newer: bool,
}

/// Read the key and order columns of `f` and record every open row whose key the source
/// holds. Reads the whole file: the open order of every such key is needed later.
#[allow(clippy::too_many_arguments)]
async fn probe_file(
    store: &Arc<dyn ObjectStore>,
    f: TargetFile,
    plan: &SourcePlan,
    columns: &[(String, DataType)],
    key_count: usize,
    opts: &HistoryUpsertOptions,
    budgets: &Budgets,
) -> Result<(FileProbe, Arc<ParquetMetaData>)> {
    let (builder, held_fetch) = open_builder(store, &f, budgets).await?;
    let metadata = builder.metadata().clone();
    let file_schema = builder.schema().clone();
    let mut projection: Vec<usize> = columns
        .iter()
        .filter_map(|(name, _)| file_schema.index_of(name).ok())
        .collect();
    projection.sort_unstable();
    projection.dedup();

    let mut probe = FileProbe {
        file: f,
        seen: Vec::new(),
        newer: false,
    };
    let mut note = |batch: &RecordBatch| -> Result<()> {
        let cols = key_and_order_columns(batch, columns)?;
        let keys = plan.key_converter.convert_columns(&cols[..key_count])?;
        let orders = plan.order_converter.convert_columns(&cols[key_count..])?;
        for i in 0..batch.num_rows() {
            if let Some(&group) = plan.by_key.get(keys.row(i).as_ref()) {
                let order = orders.row(i);
                probe.newer = probe.newer || plan.newest_order(group) > order.as_ref();
                probe.seen.push((group, order.as_ref().into()));
            }
        }
        Ok(())
    };

    if projection.is_empty() {
        // Every row of the file has null keys and a null order value, so one row decides it.
        if metadata.file_metadata().num_rows() > 0 {
            note(&RecordBatch::try_new_with_options(
                Arc::new(Schema::empty()),
                vec![],
                &arrow_array::RecordBatchOptions::new().with_row_count(Some(1)),
            )?)?;
        }
        return Ok((probe, metadata));
    }

    let fetch = match held_fetch {
        Some(fetch) => fetch,
        None => {
            budgets
                .acquire_fetch(max_row_group_fetch_bytes(&metadata, Some(&projection)))
                .await?
        }
    };
    let mask = ProjectionMask::roots(builder.parquet_schema(), projection);
    let batch_rows = byte_bounded_batch_rows(
        &metadata,
        INITIAL_PROBE_ESTIMATE_BYTES,
        opts.read_batch_size,
    );
    let mut stream = builder
        .with_projection(mask)
        .with_batch_size(batch_rows)
        .build()?;
    let mut estimate_bytes = INITIAL_PROBE_ESTIMATE_BYTES;
    loop {
        let mut permit = budgets.acquire_bytes(estimate_bytes).await?;
        let Some(batch) = stream.try_next().await? else {
            break;
        };
        let actual = batch.get_array_memory_size();
        budgets.top_up(&mut permit, actual).await?;
        estimate_bytes = actual.max(16 * 1024);
        note(&batch)?;
    }
    drop(stream);
    drop(fetch);
    Ok((probe, metadata))
}

/// A decoded batch on its way to the writers, split by destination. The permit is
/// released once both parts are in the write buffers.
struct WriteMessage {
    current: Option<RecordBatch>,
    closed: Option<RecordBatch>,
    _permit: BudgetPermit,
}

struct CloseOutcome {
    rows_copied: usize,
    versions_closed: usize,
    bytes_read: u64,
    remove: Action,
}

/// Stream one current-partition file to the writer, closing the open rows of keys that
/// kept a newer source row. Every batch carries its budget permits to the writer.
#[allow(clippy::too_many_arguments)]
async fn close_file(
    store: Arc<dyn ObjectStore>,
    f: TargetFile,
    plan: Arc<SourcePlan>,
    closing: Arc<Vec<Option<u32>>>,
    cols: Arc<Columns>,
    table_schema: SchemaRef,
    opts: Arc<HistoryUpsertOptions>,
    budgets: Budgets,
    tx: mpsc::UnboundedSender<WriteMessage>,
) -> Result<CloseOutcome> {
    let (mut stream, fetch) = open_rewrite_stream(
        &store,
        &f,
        &budgets,
        opts.read_ahead_row_groups,
        opts.read_batch_size,
    )
    .await?;
    let mut rows_copied = 0usize;
    let mut versions_closed = 0usize;
    let mut estimate_bytes = crate::upsert::INITIAL_DECODE_ESTIMATE_BYTES;
    loop {
        let mut permit = budgets.acquire_bytes(estimate_bytes).await?;
        let Some(batch) = stream.try_next().await? else {
            break;
        };
        let actual = batch.get_array_memory_size();
        budgets.top_up(&mut permit, actual).await?;
        estimate_bytes = actual.max(64 * 1024);

        let batch = add_partition_column(&batch, &opts.partition_column, &opts.current_partition)?;
        let batch = cast_to_schema(&batch, &table_schema)?;
        let key_cols: Vec<ArrayRef> = cols
            .key_idx
            .iter()
            .map(|i| batch.column(*i).clone())
            .collect();
        let keys = plan.key_converter.convert_columns(&key_cols)?;
        let closes: UInt32Array = (0..batch.num_rows())
            .map(|i| {
                plan.by_key
                    .get(keys.row(i).as_ref())
                    .and_then(|group| closing[*group as usize])
            })
            .collect();
        let closed = closes.len() - closes.null_count();
        versions_closed += closed;
        rows_copied += batch.num_rows() - closed;
        let message = if closed == 0 {
            WriteMessage {
                current: Some(batch),
                closed: None,
                _permit: permit,
            }
        } else {
            let is_closed: BooleanArray = (0..closes.len())
                .map(|i| Some(closes.is_valid(i)))
                .collect();
            let stays_open: BooleanArray =
                (0..closes.len()).map(|i| Some(closes.is_null(i))).collect();
            let current = filter_record_batch(&batch, &stays_open)?;
            let closed_rows = stamp_validity(
                &filter_record_batch(&batch, &is_closed)?,
                filter(&closes, &is_closed)?.as_primitive(),
                &plan,
                &cols,
                &table_schema,
                &opts.current_partition,
            )?;
            WriteMessage {
                current: (current.num_rows() > 0).then_some(current),
                closed: Some(closed_rows),
                _permit: permit,
            }
        };
        tx.send(message)
            .map_err(|_| Error::Generic("writer task ended before its readers".into()))?;
    }
    drop(stream);
    drop(fetch);
    Ok(CloseOutcome {
        rows_copied,
        versions_closed,
        bytes_read: f.size,
        remove: Action::Remove(f.remove),
    })
}

/// Most month files the closed-row writer keeps open. Each open file holds its own
/// buffers, so closes that span many months would otherwise grow memory per month.
const MAX_OPEN_MONTH_FILES: usize = 32;

/// Write closed rows one month at a time, flushing every open month file before the
/// writer would hold more than [`MAX_OPEN_MONTH_FILES`].
async fn write_closed(
    writer: &mut StreamingWriter,
    batch: &RecordBatch,
    partition_idx: usize,
    adds: &mut Vec<Add>,
    target_file_size: usize,
    max_row_group_bytes: Option<usize>,
) -> Result<()> {
    let order = sort_to_indices(batch.column(partition_idx), None, None)?;
    let sorted = take_record_batch(batch, &order)?;
    let runs = arrow_ord::partition::partition(&[sorted.column(partition_idx).clone()])?;
    for run in runs.ranges() {
        let month = sorted.slice(run.start, run.end - run.start);
        if writer.open_files() >= MAX_OPEN_MONTH_FILES && !writer.holds_partition_of(&month)? {
            adds.extend(writer.flush().await?);
        }
        writer.write(month)?;
        roll_writer(writer, adds, target_file_size, max_row_group_bytes).await?;
    }
    Ok(())
}

/// Writes chunks of kept source rows, stamped with their `valid_to` and partition.
struct SourceWriter<'a> {
    plan: &'a SourcePlan,
    cols: &'a Columns,
    table_schema: &'a SchemaRef,
    opts: &'a HistoryUpsertOptions,
    target_file_size: usize,
}

impl SourceWriter<'_> {
    fn stamped(&self, rows: &[KeptRow]) -> Result<RecordBatch> {
        // Hand interleave only the batches this chunk reads; its cost grows with the
        // number of batches it is given.
        let mut batch_slots: HashMap<usize, usize> = HashMap::new();
        let mut batch_refs: Vec<&RecordBatch> = Vec::new();
        let located: Vec<(usize, usize)> = rows
            .iter()
            .map(|(r, _)| {
                let (batch, row) = self.plan.locate(*r);
                let slot = *batch_slots.entry(batch).or_insert_with(|| {
                    batch_refs.push(&self.plan.batches[batch]);
                    batch_refs.len() - 1
                });
                (slot, row)
            })
            .collect();
        let closes: UInt32Array = rows.iter().map(|(_, next)| *next).collect();
        stamp_validity(
            &interleave_record_batch(&batch_refs, &located)?,
            &closes,
            self.plan,
            self.cols,
            self.table_schema,
            &self.opts.current_partition,
        )
    }

    /// Write newest kept rows, which all stay open in the current partition.
    async fn write_open(
        &self,
        rows: &[KeptRow],
        writer: &mut StreamingWriter,
        adds: &mut Vec<Add>,
    ) -> Result<()> {
        let selected = self.stamped(rows)?;
        let max_row_group_bytes = self.opts.max_row_group_bytes;
        let slice_rows =
            source_slice_rows(&selected, self.opts.read_batch_size, max_row_group_bytes);
        let mut offset = 0usize;
        while offset < selected.num_rows() {
            let n = (selected.num_rows() - offset).min(slice_rows);
            writer.write(selected.slice(offset, n))?;
            offset += n;
            roll_writer(writer, adds, self.target_file_size, max_row_group_bytes).await?;
        }
        Ok(())
    }
}

async fn history_inner(
    table: &DeltaTable,
    source_batches: Vec<RecordBatch>,
    source_schema: SchemaRef,
    opts: &HistoryUpsertOptions,
    plan_only: bool,
) -> Result<(HistoryUpsertStats, Option<DeltaTableState>)> {
    // Again here: after a relax the snapshot is reloaded, and a concurrent commit may have
    // enabled a feature that makes a blind rewrite unsafe.
    ensure_history_table(table, opts)?;
    let snapshot = table.snapshot()?;
    let table_schema: SchemaRef = RecordBatchWriter::for_table(table)?.arrow_schema();
    let cols = Columns::resolve(&table_schema, &source_schema, opts)?;
    let target_file_size = resolve_target_file_size(
        opts.target_file_size,
        snapshot.table_config().target_file_size().get() as usize,
    );
    let read_version = snapshot.version() as i64;

    let plan_started = Instant::now();
    let plan = SourcePlan::build(source_batches, &table_schema, &cols, opts)?;
    let mut stats = HistoryUpsertStats {
        version: read_version,
        rows_in: plan.rows_in,
        rows_deduped: plan.rows_in - plan.deduped.len(),
        ..Default::default()
    };
    if plan.groups.is_empty() {
        stats.plan_ms = plan_started.elapsed().as_millis() as u64;
        return Ok((stats, None));
    }

    let files = list_files_by_partition(
        table,
        Some(&opts.partition_column),
        &[opts.current_partition.as_str()],
    )
    .await?
    .into_iter()
    .next()
    .unwrap_or_default();
    let (candidates, pruned): (Vec<TargetFile>, Vec<TargetFile>) = files
        .into_iter()
        .partition(|f| !file_cannot_hold_source_key(f, &opts.key_columns[0], &plan));
    stats.files_carried_over = pruned.len();
    stats.plan_ms = plan_started.elapsed().as_millis() as u64;

    let budgets = Budgets::new(
        opts.max_buffered_bytes,
        opts.max_fetch_bytes,
        opts.limits.clone(),
    );
    let store: Arc<dyn ObjectStore> = table.object_store();

    // Held from the probe on, as an upsert's partition worker holds it.
    let _partition_permit = opts.limits.acquire_partition().await?;
    let probe_started = Instant::now();
    let probe_columns: Vec<(String, DataType)> = cols
        .key_idx
        .iter()
        .chain(std::iter::once(&cols.order_idx))
        .map(|i| {
            let f = table_schema.field(*i);
            (f.name().clone(), f.data_type().clone())
        })
        .collect();
    stats.files_probed = candidates.len();
    let key_count = cols.key_idx.len();
    let mut open: Vec<Option<Box<[u8]>>> = vec![None; plan.groups.len()];
    let mut probed: Vec<(TargetFile, Vec<u32>)> = Vec::new();
    {
        let results =
            futures::stream::iter(
                candidates.into_iter().map(|f| {
                    let store = store.clone();
                    let (plan, probe_columns, budgets) = (&plan, &probe_columns, &budgets);
                    async move {
                        probe_file(&store, f, plan, probe_columns, key_count, opts, budgets).await
                    }
                }),
            )
            .buffered(opts.probe_concurrency.max(1));
        futures::pin_mut!(results);
        let retained_footer_limit = opts.max_parallel_files.max(1);
        let mut retained = 0usize;
        while let Some((mut probe, metadata)) = results.try_next().await? {
            if probe.newer && retained < retained_footer_limit {
                probe.file.metadata = Some(metadata);
                retained += 1;
            }
            let mut groups = Vec::with_capacity(probe.seen.len());
            for (group, order) in probe.seen {
                let slot = &mut open[group as usize];
                if slot.as_ref().is_none_or(|o| order > *o) {
                    *slot = Some(order);
                }
                groups.push(group);
            }
            groups.sort_unstable();
            groups.dedup();
            probed.push((probe.file, groups));
        }
    }
    stats.probe_ms = probe_started.elapsed().as_millis() as u64;

    let decision = plan.decide(&open);
    stats.rows_reread = decision.rows_reread;
    stats.rows_backwards = decision.rows_backwards;
    stats.versions_opened = decision.versions_opened;
    stats.chain_rows_closed = decision.chain_rows_closed;
    if decision.writes.is_empty() || plan_only {
        // Nothing kept means nothing closes either: the table already holds this input.
        stats.files_carried_over += probed.len();
        return Ok((stats, None));
    }

    let mut rewrite = Vec::new();
    for (file, groups) in probed {
        if groups
            .iter()
            .any(|group| decision.closing[*group as usize].is_some())
        {
            rewrite.push(file);
        } else {
            stats.files_carried_over += 1;
        }
    }

    // Open rows and closed rows go through separate writers, so a flush of closed rows
    // never cuts a current-partition file short.
    let rewrite_started = Instant::now();
    let plan = Arc::new(plan);
    let closing = Arc::new(decision.closing);
    let cols = Arc::new(cols);
    let opts_arc = Arc::new(opts.clone());
    let current_writer = StreamingWriter::for_table(table)?;
    let closed_writer = StreamingWriter::for_table(table)?;
    let (tx, mut rx) = mpsc::unbounded_channel::<WriteMessage>();
    let max_row_group_bytes = opts.max_row_group_bytes;
    let partition_idx = cols.partition_idx;
    let writer_task = tokio::spawn(async move {
        let (mut current_writer, mut closed_writer) = (current_writer, closed_writer);
        let mut adds = Vec::new();
        while let Some(message) = rx.recv().await {
            if let Some(batch) = message.current {
                current_writer.write(batch)?;
                roll_writer(
                    &mut current_writer,
                    &mut adds,
                    target_file_size,
                    max_row_group_bytes,
                )
                .await?;
            }
            if let Some(batch) = message.closed {
                write_closed(
                    &mut closed_writer,
                    &batch,
                    partition_idx,
                    &mut adds,
                    target_file_size,
                    max_row_group_bytes,
                )
                .await?;
            }
        }
        Ok::<_, Error>((current_writer, closed_writer, adds))
    });

    // Same reader discipline as the upsert: per-call then process-wide file permits, and
    // readers queued behind a failed one stop instead of reading.
    let file_sem = Arc::new(Semaphore::new(opts.max_parallel_files.max(1)));
    let reader_failed = Arc::new(AtomicBool::new(false));
    let mut readers = Vec::with_capacity(rewrite.len());
    for f in rewrite {
        let sem = file_sem.clone();
        let failed = reader_failed.clone();
        let (store, plan, closing, cols) =
            (store.clone(), plan.clone(), closing.clone(), cols.clone());
        let (schema, opts, budgets, tx) = (
            table_schema.clone(),
            opts_arc.clone(),
            budgets.clone(),
            tx.clone(),
        );
        readers.push(tokio::spawn(async move {
            let _local = sem
                .acquire_owned()
                .await
                .map_err(|_| Error::Generic("file semaphore closed".into()))?;
            if failed.load(Ordering::Relaxed) {
                return Ok(None);
            }
            let outcome = async {
                let _global = opts.limits.acquire_file().await?;
                close_file(store, f, plan, closing, cols, schema, opts, budgets, tx).await
            }
            .await;
            if outcome.is_err() {
                failed.store(true, Ordering::Relaxed);
            }
            outcome.map(Some)
        }));
    }
    drop(tx);

    let mut removes: Vec<Action> = Vec::new();
    let mut reader_err: Option<Error> = None;
    for h in readers {
        match h
            .await
            .map_err(|e| Error::Generic(format!("file worker panicked: {e}")))?
        {
            Ok(Some(o)) => {
                stats.rows_copied += o.rows_copied;
                stats.versions_closed += o.versions_closed;
                stats.bytes_read += o.bytes_read;
                removes.push(o.remove);
            }
            Ok(None) => {}
            Err(e) => reader_err = reader_err.or(Some(e)),
        }
    }
    let (mut current_writer, mut closed_writer, mut adds) = writer_task
        .await
        .map_err(|e| Error::Generic(format!("writer task panicked: {e}")))??;
    if let Some(e) = reader_err {
        return Err(e);
    }

    let (opens, mut chain): (Vec<KeptRow>, Vec<KeptRow>) = decision
        .writes
        .into_iter()
        .partition(|(_, next)| next.is_none());
    let source = SourceWriter {
        plan: &plan,
        cols: &cols,
        table_schema: &table_schema,
        opts,
        target_file_size,
    };
    for chunk in opens.chunks(opts.read_batch_size.max(1)) {
        source
            .write_open(chunk, &mut current_writer, &mut adds)
            .await?;
    }
    // Sorted by month, so the closed-row writer moves through months in order instead of
    // reopening them; `write_closed` keeps the open month files under the limit.
    let next_rows: UInt32Array = chain.iter().map(|(_, next)| *next).collect();
    let months = format_months(take(plan.valid_from.as_ref(), &next_rows, None)?.as_ref())?;
    let mut by_month: Vec<usize> = (0..chain.len()).collect();
    by_month.sort_by_key(|i| months.value(*i));
    chain = by_month.iter().map(|i| chain[*i]).collect();
    for chunk in chain.chunks(opts.read_batch_size.max(1)) {
        write_closed(
            &mut closed_writer,
            &source.stamped(chunk)?,
            partition_idx,
            &mut adds,
            target_file_size,
            max_row_group_bytes,
        )
        .await?;
    }
    adds.extend(current_writer.flush().await?);
    adds.extend(closed_writer.flush().await?);
    stats.rewrite_ms = rewrite_started.elapsed().as_millis() as u64;
    stats.files_added = adds.len();
    stats.files_removed = removes.len();
    stats.bytes_written = adds.iter().map(|a| a.size.max(0) as u64).sum();

    let mut actions = removes;
    actions.extend(adds.into_iter().map(Action::Add));
    // Zero commit retries: without DataFusion, delta-rs does not check a `Write` against
    // a concurrent commit that only adds files, so a rebased commit could open a key a
    // second time. A stale commit fails as a conflict instead, and the handle re-plans.
    let committed = commit_partition_overwrite(
        table,
        snapshot,
        actions,
        std::slice::from_ref(&opts.partition_column),
        0,
        opts.commit_metadata.clone(),
    )
    .await?;
    stats.commit_ms = committed.commit_ms;
    stats.maintenance_ms = committed.maintenance_ms;
    stats.committed = true;
    stats.version = committed.version;
    info!(
        version = stats.version,
        rows_in = stats.rows_in,
        versions_opened = stats.versions_opened,
        versions_closed = stats.versions_closed,
        chain_rows_closed = stats.chain_rows_closed,
        rows_reread = stats.rows_reread,
        rows_backwards = stats.rows_backwards,
        files_added = stats.files_added,
        files_removed = stats.files_removed,
        "history upsert committed"
    );
    Ok((stats, Some(committed.state)))
}

/// A bucket in `0..n` for every row of `batches`, from the values of `key_columns`.
///
/// The key columns are cast to their types in `table`, the cast [`history_upsert`] matches
/// keys after, so source values that become one table key always share a bucket. Each key
/// is then encoded with arrow-row (null-safe, so null key parts hash alike) and hashed with
/// xxHash64 seeded with [`KEY_BUCKET_SEED`], reduced modulo `n`. The ids are the same in
/// every process that runs one deltalite build. arrow-row may change its encoding between
/// arrow releases, so do not persist the ids.
pub fn key_buckets(
    table: &DeltaTable,
    batches: &[RecordBatch],
    key_columns: &[String],
    n: u32,
) -> Result<UInt32Array> {
    if n == 0 {
        return Err(Error::Generic("key_buckets needs n >= 1".into()));
    }
    if key_columns.is_empty() {
        return Err(Error::Generic(
            "key_buckets needs at least one key column".into(),
        ));
    }
    let table_schema = RecordBatchWriter::for_table(table)?.arrow_schema();
    let key_types = key_columns
        .iter()
        .map(|k| {
            Ok(table_schema
                .field_with_name(k)
                .map_err(|_| {
                    Error::SchemaMismatch(format!("key column '{k}' not found in table schema"))
                })?
                .data_type()
                .clone())
        })
        .collect::<Result<Vec<DataType>>>()?;
    let converter = RowConverter::new(key_types.iter().cloned().map(SortField::new).collect())?;
    let mut out = Vec::with_capacity(batches.iter().map(RecordBatch::num_rows).sum());
    for batch in batches {
        let cols: Vec<ArrayRef> = key_columns
            .iter()
            .zip(&key_types)
            .map(|(k, ty)| {
                let col = batch.column_by_name(k).ok_or_else(|| {
                    Error::SchemaMismatch(format!("key column '{k}' is missing from the data"))
                })?;
                cast_strict(col, ty)
            })
            .collect::<Result<_>>()?;
        let rows = converter.convert_columns(&cols)?;
        out.extend(rows.iter().map(|row| {
            (twox_hash::XxHash64::oneshot(KEY_BUCKET_SEED, row.as_ref()) % u64::from(n)) as u32
        }));
    }
    Ok(UInt32Array::from(out))
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::Int64Array;
    use deltalake::kernel::{DataType as KernelType, StructField};
    use deltalake::operations::create::CreateBuilder;

    #[tokio::test]
    async fn the_write_checks_the_snapshot_it_writes_against() {
        let dir = tempfile::tempdir().unwrap();
        let table = CreateBuilder::new()
            .with_location(dir.path().to_str().unwrap())
            .with_columns(vec![
                StructField::new("v", KernelType::LONG, true),
                StructField::new("p", KernelType::STRING, false),
            ])
            .with_partition_columns(vec!["p".to_string()])
            .with_configuration(vec![("delta.appendOnly", Some("true"))])
            .await
            .unwrap();
        let source = Arc::new(Schema::new(vec![Field::new("v", DataType::Int64, true)]));
        let opts = HistoryUpsertOptions {
            key_columns: vec!["v".into()],
            order_column: "v".into(),
            valid_from_column: "v".into(),
            valid_to_column: "v".into(),
            partition_column: "p".into(),
            current_partition: "current".into(),
            tie_break_column: "v".into(),
            ..Default::default()
        };
        let err = history_inner(
            &table,
            vec![RecordBatch::new_empty(source.clone())],
            source,
            &opts,
            false,
        )
        .await
        .unwrap_err();
        assert!(matches!(err, Error::Unsupported(_)), "{err}");
    }

    #[tokio::test]
    async fn closed_rows_hold_at_most_the_month_file_limit_open() {
        let dir = tempfile::tempdir().unwrap();
        let table = CreateBuilder::new()
            .with_location(dir.path().to_str().unwrap())
            .with_columns(vec![
                StructField::new("v", KernelType::LONG, true),
                StructField::new("p", KernelType::STRING, false),
            ])
            .with_partition_columns(vec!["p".to_string()])
            .await
            .unwrap();
        let schema = RecordBatchWriter::for_table(&table).unwrap().arrow_schema();
        let batch = |months: &[String]| {
            RecordBatch::try_new(
                schema.clone(),
                vec![
                    Arc::new(Int64Array::from_iter_values(0..months.len() as i64)),
                    Arc::new(StringArray::from_iter_values(months.iter().rev())),
                ],
            )
            .unwrap()
        };
        let months: Vec<String> = (0..MAX_OPEN_MONTH_FILES)
            .map(|i| format!("{}-{:02}", 2000 + i / 12, i % 12 + 1))
            .collect();
        let mut writer = StreamingWriter::for_table(&table).unwrap();
        let mut adds = Vec::new();
        let mut write = async |months: &[String]| {
            write_closed(&mut writer, &batch(months), 1, &mut adds, usize::MAX, None)
                .await
                .unwrap();
            (adds.len(), writer.open_files())
        };

        assert_eq!(write(&months).await, (0, MAX_OPEN_MONTH_FILES));
        assert_eq!(
            write(&months[..1]).await,
            (0, MAX_OPEN_MONTH_FILES),
            "a month already open needs no flush"
        );
        assert_eq!(
            write(&["1999-12".to_string()]).await,
            (MAX_OPEN_MONTH_FILES, 1)
        );
    }
}
