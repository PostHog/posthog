//! Parquet writer for rewritten partitions that never copies a finished file.
//!
//! delta-rs's `RecordBatchWriter` encodes into one growing `Vec<u8>` per output file,
//! copies that buffer before every `write()` (to roll back a failed write), and
//! `flush()` copies the whole buffer again (`buffer.to_vec()`) before uploading it.
//! A `target_file_size` file therefore costs the encoder's in-progress row group, a
//! `Vec` that over-allocates by up to 2x as it doubles, and a full second copy at
//! upload time: two to three times the file size.
//!
//! [`StreamingWriter`] is the same writer with a different sink. It drives the same
//! parquet `ArrowWriter` with the same `WriterProperties` over the same batches, so the
//! file bytes are identical, but the sink stores the output as fixed-size chunks and the
//! upload sends those chunks as they are (`PutPayload` over `Bytes`, no copy). The
//! encoder releases each column chunk as it serialises it, so the output never exists
//! twice. File naming, partition values, `Add` statistics (see [`crate::stats`]), the
//! size measure that drives rollover, and the upload call (`put_with_retries`, 15
//! attempts, through the multipart-aware store) all match `RecordBatchWriter`; the
//! tests below compare the two writers directly.

use std::collections::HashMap;
use std::io::Write;
use std::sync::Arc;

use arrow_array::{Array, ArrayRef, RecordBatch, UInt32Array};
use arrow_row::{RowConverter, SortField};
use arrow_schema::{Schema, SchemaRef};
use arrow_select::take::take;
use bytes::Bytes;
use delta_kernel::expressions::Scalar;
use delta_kernel::table_properties::DataSkippingNumIndexedCols;
use deltalake::kernel::scalars::ScalarExt;
use deltalake::kernel::schema::cast::{cast_record_batch, normalize_for_delta};
use deltalake::kernel::Add;
use deltalake::logstore::ObjectStoreRetryExt;
use deltalake::writer::RecordBatchWriter;
use deltalake::{DeltaTable, ObjectStore, Path};
use indexmap::IndexMap;
use object_store::PutPayload;
use parquet::arrow::ArrowWriter;
use parquet::basic::{Compression, ZstdLevel};
use parquet::file::properties::WriterProperties;
use parquet::schema::types::ColumnPath;
use uuid::Uuid;

use crate::errors::{Error, Result};
use crate::stats::create_add;

/// Size of one output chunk. Small enough that the last, partly filled chunk wastes
/// little; large enough that a 100 MiB file is ~100 `Bytes`, not thousands.
const CHUNK_BYTES: usize = 1024 * 1024;

/// Upload attempts per file, as `RecordBatchWriter::flush` uses.
const PUT_RETRIES: usize = 15;

/// `delta.dataSkippingNumIndexedCols` default (delta-rs `DEFAULT_NUM_INDEX_COLS`).
const DEFAULT_NUM_INDEX_COLS: u64 = 32;

/// `std::io::Write` sink that keeps what it receives as a list of `CHUNK_BYTES` buffers,
/// each allocated at its final size, instead of one buffer that doubles as it grows.
#[derive(Default)]
struct ChunkSink {
    full: Vec<Bytes>,
    current: Vec<u8>,
    len: usize,
}

impl ChunkSink {
    fn into_payload(mut self) -> (PutPayload, usize) {
        if !self.current.is_empty() {
            self.full
                .push(Bytes::from(std::mem::take(&mut self.current)));
        }
        (PutPayload::from_iter(self.full), self.len)
    }
}

impl Write for ChunkSink {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        let mut rest = buf;
        while !rest.is_empty() {
            if self.current.capacity() == 0 {
                self.current = Vec::with_capacity(CHUNK_BYTES);
            }
            let take = (CHUNK_BYTES - self.current.len()).min(rest.len());
            self.current.extend_from_slice(&rest[..take]);
            rest = &rest[take..];
            if self.current.len() == CHUNK_BYTES {
                self.full
                    .push(Bytes::from(std::mem::take(&mut self.current)));
            }
        }
        self.len += buf.len();
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// One output file being written for one partition value.
struct OpenFile {
    writer: ArrowWriter<ChunkSink>,
    partition_values: IndexMap<String, Scalar>,
}

impl OpenFile {
    /// Bytes the file holds so far, measured as `RecordBatchWriter::buffer_len` measures
    /// it: bytes the sink has received plus the encoder's in-progress row group.
    fn buffer_len(&self) -> usize {
        self.writer.inner().len + self.writer.in_progress_size()
    }
}

/// A partition's rows split off one batch, with the partition column removed.
struct PartitionSlice {
    partition_values: IndexMap<String, Scalar>,
    batch: RecordBatch,
}

/// Drop-in replacement for the parts of `RecordBatchWriter` deltalite uses: `write`,
/// `buffer_len` and `flush`. See the module docs.
pub(crate) struct StreamingWriter {
    store: Arc<dyn ObjectStore>,
    arrow_schema: SchemaRef,
    file_schema: SchemaRef,
    partition_columns: Vec<String>,
    writer_properties: WriterProperties,
    num_indexed_cols: DataSkippingNumIndexedCols,
    stats_columns: Option<Vec<String>>,
    open: HashMap<String, OpenFile>,
}

impl StreamingWriter {
    /// Build a writer for `table`, resolving schema, partitioning, writer properties and
    /// stats configuration exactly as `RecordBatchWriter::for_table` does.
    pub(crate) fn for_table(table: &DeltaTable) -> Result<Self> {
        // Runs delta-rs's own table checks (it refuses column-mapping tables) and gives
        // the arrow schema delta-rs would write with.
        let arrow_schema = RecordBatchWriter::for_table(table)?.arrow_schema();
        let snapshot = table.snapshot()?;
        let metadata = snapshot.metadata();
        let partition_columns: Vec<String> = metadata.partition_columns().to_vec();
        let configuration = metadata.configuration();
        let num_indexed_cols = configuration
            .get("delta.dataSkippingNumIndexedCols")
            .and_then(|v| {
                v.parse::<u64>()
                    .ok()
                    .map(DataSkippingNumIndexedCols::NumColumns)
            })
            .unwrap_or(DataSkippingNumIndexedCols::NumColumns(
                DEFAULT_NUM_INDEX_COLS,
            ));
        let stats_columns = configuration
            .get("delta.dataSkippingStatsColumns")
            .map(|v| v.split(',').map(|s| s.to_string()).collect());
        Ok(Self {
            store: table.object_store(),
            file_schema: schema_without_partitions(&arrow_schema, &partition_columns),
            arrow_schema,
            partition_columns,
            writer_properties: delta_rs_writer_properties(),
            num_indexed_cols,
            stats_columns,
            open: HashMap::new(),
        })
    }

    /// Encode with `props` instead of delta-rs's write defaults. Compaction passes
    /// [`optimize_writer_properties`], the properties delta-rs's `optimize` writes with.
    pub(crate) fn with_writer_properties(mut self, props: WriterProperties) -> Self {
        self.writer_properties = props;
        self
    }

    /// Bytes held across all open files; the rollover measure.
    pub(crate) fn buffer_len(&self) -> usize {
        self.open.values().map(OpenFile::buffer_len).sum()
    }

    /// Rows in the row groups the open files have not closed yet.
    pub(crate) fn in_progress_rows(&self) -> usize {
        self.open
            .values()
            .map(|f| f.writer.in_progress_rows())
            .sum()
    }

    /// Close the in-progress row group of every open file, keeping the files open.
    pub(crate) fn flush_row_groups(&mut self) -> Result<()> {
        for file in self.open.values_mut() {
            file.writer.flush()?;
        }
        Ok(())
    }

    /// Encode `values` into the open file of each partition it holds.
    pub(crate) fn write(&mut self, values: RecordBatch) -> Result<()> {
        let values = if values.schema() != self.arrow_schema {
            let normalized = normalize_for_delta(&values.schema());
            if normalized != values.schema() {
                cast_record_batch(&values, normalized, true, false)?
            } else {
                values
            }
        } else {
            values
        };

        for slice in self.split_by_partition(&values)? {
            let key = hive_partition_path(&slice.partition_values);
            let file = match self.open.entry(key) {
                std::collections::hash_map::Entry::Occupied(e) => e.into_mut(),
                std::collections::hash_map::Entry::Vacant(e) => e.insert(OpenFile {
                    writer: ArrowWriter::try_new(
                        ChunkSink::default(),
                        self.file_schema.clone(),
                        Some(self.writer_properties.clone()),
                    )?,
                    partition_values: slice.partition_values,
                }),
            };
            if slice.batch.schema() != self.file_schema {
                return Err(Error::SchemaMismatch(format!(
                    "Arrow RecordBatch schema does not match: RecordBatch schema: {}, {}",
                    slice.batch.schema(),
                    self.file_schema
                )));
            }
            file.writer.write(&slice.batch)?;
        }
        Ok(())
    }

    /// Finish every open file, upload it, and return one `Add` action per file.
    pub(crate) async fn flush(&mut self) -> Result<Vec<Add>> {
        let files = std::mem::take(&mut self.open);
        let mut actions = Vec::with_capacity(files.len());
        for (_, mut file) in files {
            let metadata = file.writer.finish()?;
            let sink = std::mem::take(file.writer.inner_mut());
            drop(file.writer);
            let prefix = Path::parse(hive_partition_path(&file.partition_values))
                .map_err(|e| Error::Generic(format!("bad partition path: {e}")))?;
            let path = next_data_path(&prefix, &Uuid::new_v4(), &self.writer_properties);
            let (payload, size) = sink.into_payload();
            self.store
                .put_with_retries(&path, payload, PUT_RETRIES)
                .await?;
            actions.push(create_add(
                &file.partition_values,
                path.to_string(),
                size as i64,
                &metadata,
                self.num_indexed_cols,
                &self.stats_columns,
            )?);
        }
        Ok(actions)
    }

    /// Split `values` by partition value, as delta-rs's `divide_by_partition_values`
    /// does. deltalite writes one partition per batch, so the common case is detected
    /// first and keeps the columns as they are; only a batch that really spans several
    /// partitions pays for delta-rs's sort-and-take.
    fn split_by_partition(&self, values: &RecordBatch) -> Result<Vec<PartitionSlice>> {
        if self.partition_columns.is_empty() {
            return Ok(vec![PartitionSlice {
                partition_values: IndexMap::new(),
                batch: values.clone(),
            }]);
        }
        let schema = values.schema();
        let mut partition_arrays: Vec<ArrayRef> = Vec::with_capacity(self.partition_columns.len());
        for c in &self.partition_columns {
            partition_arrays.push(values.column(schema.index_of(c)?).clone());
        }

        if values.num_rows() > 0 && arrow_ord::partition::partition(&partition_arrays)?.len() == 1 {
            let partition_values = self.partition_values_at(&partition_arrays, 0)?;
            let batch = self.project_file_columns(values, None)?;
            return Ok(vec![PartitionSlice {
                partition_values,
                batch,
            }]);
        }

        let indices = lexsort_to_indices(&partition_arrays)?;
        let sorted: Vec<ArrayRef> = partition_arrays
            .iter()
            .map(|a| take(a.as_ref(), &indices, None))
            .collect::<std::result::Result<_, _>>()?;
        let ranges = arrow_ord::partition::partition(&sorted)?;
        let mut out = Vec::new();
        for range in ranges.ranges() {
            let idx: UInt32Array = (range.start..range.end)
                .map(|i| Some(indices.value(i)))
                .collect();
            let partition_values = self.partition_values_at(&sorted, range.start)?;
            let batch = self.project_file_columns(values, Some(&idx))?;
            out.push(PartitionSlice {
                partition_values,
                batch,
            });
        }
        Ok(out)
    }

    fn partition_values_at(
        &self,
        arrays: &[ArrayRef],
        row: usize,
    ) -> Result<IndexMap<String, Scalar>> {
        let mut out = IndexMap::new();
        for (name, arr) in self.partition_columns.iter().zip(arrays) {
            let value = Scalar::from_array(arr.as_ref(), row).ok_or_else(|| {
                Error::Generic("Missing partition column: failed to parse".into())
            })?;
            out.insert(name.clone(), value);
        }
        Ok(out)
    }

    /// The non-partition columns of `values` (optionally only rows `idx`), rebuilt under
    /// the file schema the way delta-rs rebuilds them, so the result is validated
    /// against the table's nullability exactly as delta-rs validates it.
    fn project_file_columns(
        &self,
        values: &RecordBatch,
        idx: Option<&UInt32Array>,
    ) -> Result<RecordBatch> {
        let schema = values.schema();
        let mut cols: Vec<ArrayRef> = Vec::with_capacity(self.file_schema.fields().len());
        for f in self.file_schema.fields() {
            let col = values.column(schema.index_of(f.name())?);
            cols.push(match idx {
                Some(idx) => take(col.as_ref(), idx, None)?,
                None => col.clone(),
            });
        }
        Ok(RecordBatch::try_new(self.file_schema.clone(), cols)?)
    }
}

/// `default_writer_properties(Compression::SNAPPY)` from delta-rs, which every
/// `RecordBatchWriter` constructor uses.
fn delta_rs_writer_properties() -> WriterProperties {
    WriterProperties::builder()
        .set_created_by(format!("delta-rs version {}", deltalake::crate_version()))
        .set_compression(Compression::SNAPPY)
        .build()
}

/// `default_writer_properties(Compression::ZSTD(4))` from delta-rs, which `optimize`
/// uses when the caller passes no writer properties (the Python package passes none).
pub(crate) fn optimize_writer_properties() -> WriterProperties {
    WriterProperties::builder()
        .set_created_by(format!("delta-rs version {}", deltalake::crate_version()))
        .set_compression(Compression::ZSTD(ZstdLevel::try_new(4).unwrap_or_default()))
        .build()
}

fn schema_without_partitions(schema: &SchemaRef, partition_columns: &[String]) -> SchemaRef {
    Arc::new(Schema::new(
        schema
            .fields()
            .iter()
            .filter(|f| !partition_columns.contains(f.name()))
            .map(|f| f.to_owned())
            .collect::<Vec<_>>(),
    ))
}

/// delta-rs's `PartitionsExt::hive_partition_path` for `IndexMap<String, Scalar>`.
fn hive_partition_path(values: &IndexMap<String, Scalar>) -> String {
    values
        .iter()
        .map(|(k, v)| format!("{k}={}", v.serialize_encoded()))
        .collect::<Vec<_>>()
        .join("/")
}

/// delta-rs's `next_data_path` with `part_count = 0`, which is what
/// `RecordBatchWriter::flush` passes.
fn next_data_path(prefix: &Path, writer_id: &Uuid, props: &WriterProperties) -> Path {
    let ext = match props.compression(&ColumnPath::new(Vec::new())) {
        Compression::UNCOMPRESSED => "",
        Compression::SNAPPY => ".snappy",
        Compression::GZIP(_) => ".gz",
        Compression::LZO => ".lzo",
        Compression::BROTLI(_) => ".br",
        Compression::LZ4 => ".lz4",
        Compression::ZSTD(_) => ".zstd",
        Compression::LZ4_RAW => ".lz4raw",
    };
    prefix
        .clone()
        .join(format!("part-00000-{writer_id}-c000{ext}.parquet"))
}

/// delta-rs's `lexsort_to_indices` (record_batch.rs), returning errors instead of
/// unwrapping.
fn lexsort_to_indices(arrays: &[ArrayRef]) -> Result<UInt32Array> {
    let fields = arrays
        .iter()
        .map(|a| SortField::new(a.data_type().clone()))
        .collect();
    let converter = RowConverter::new(fields)?;
    let rows = converter.convert_columns(arrays)?;
    let mut sort: Vec<_> = rows.iter().enumerate().collect();
    sort.sort_unstable_by(|(_, a), (_, b)| a.cmp(b));
    Ok(UInt32Array::from_iter_values(
        sort.iter().map(|(i, _)| *i as u32),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunk_sink_preserves_bytes_and_counts_them() {
        let mut sink = ChunkSink::default();
        let data: Vec<u8> = (0..(CHUNK_BYTES * 2 + 123))
            .map(|i| (i % 251) as u8)
            .collect();
        // Uneven writes that straddle chunk boundaries.
        for piece in data.chunks(CHUNK_BYTES / 3 + 7) {
            sink.write_all(piece).unwrap();
        }
        assert_eq!(sink.len, data.len());
        let (payload, size) = sink.into_payload();
        assert_eq!(size, data.len());
        let chunks: Vec<&Bytes> = payload.iter().collect();
        assert_eq!(chunks.len(), 3);
        assert!(chunks[..2].iter().all(|c| c.len() == CHUNK_BYTES));
        let joined: Vec<u8> = chunks.iter().flat_map(|c| c.iter().copied()).collect();
        assert_eq!(joined, data);
    }

    #[test]
    fn empty_sink_is_an_empty_payload() {
        let (payload, size) = ChunkSink::default().into_payload();
        assert_eq!(size, 0);
        assert_eq!(payload.content_length(), 0);
    }

    // ---- equivalence with delta-rs's RecordBatchWriter ----------------------------

    use arrow_array::builder::{Int64Builder, ListBuilder};
    use arrow_array::{Int64Array, StringArray, StructArray};
    use arrow_schema::DataType as ArrowType;
    use delta_kernel::schema::{ArrayType, DataType, StructField};
    use deltalake::operations::create::CreateBuilder;
    use deltalake::writer::DeltaWriter;
    use object_store::ObjectStoreExt;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use serde_json::Value;

    /// Deterministic pseudo-random sequence (no `rand` dependency).
    struct Lcg(u64);

    impl Lcg {
        fn next(&mut self) -> u64 {
            self.0 = self
                .0
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            self.0 >> 11
        }
    }

    fn wide_columns() -> Vec<StructField> {
        vec![
            StructField::new("id", DataType::STRING, false),
            StructField::new("p", DataType::STRING, false),
            StructField::new("lng", DataType::LONG, true),
            StructField::new("int", DataType::INTEGER, true),
            StructField::new("sht", DataType::SHORT, true),
            StructField::new("byt", DataType::BYTE, true),
            StructField::new("dbl", DataType::DOUBLE, true),
            StructField::new("flt", DataType::FLOAT, true),
            StructField::new("bln", DataType::BOOLEAN, true),
            StructField::new("dt", DataType::DATE, true),
            StructField::new("ts", DataType::TIMESTAMP, true),
            StructField::new("bin", DataType::BINARY, true),
            StructField::new("str", DataType::STRING, true),
            StructField::new("dec_small", DataType::decimal(10, 2).unwrap(), true),
            StructField::new("dec_wide", DataType::decimal(38, 6).unwrap(), true),
            StructField::new("all_null", DataType::LONG, true),
            StructField::new(
                "arr",
                DataType::from(ArrayType::new(DataType::LONG, true)),
                true,
            ),
            StructField::new(
                "st",
                DataType::try_struct_type(vec![
                    StructField::new("a", DataType::LONG, true),
                    StructField::new("b", DataType::STRING, true),
                ])
                .unwrap(),
                true,
            ),
        ]
    }

    fn narrow_columns() -> Vec<StructField> {
        vec![
            StructField::new("id", DataType::STRING, false),
            StructField::new("p", DataType::STRING, false),
            StructField::new("lng", DataType::LONG, true),
        ]
    }

    async fn create_table(
        dir: &std::path::Path,
        columns: Vec<StructField>,
        partition_by: &[&str],
        config: &[(&str, &str)],
    ) -> DeltaTable {
        let mut b = CreateBuilder::new()
            .with_location(dir.to_str().unwrap())
            .with_columns(columns);
        if !partition_by.is_empty() {
            b = b.with_partition_columns(partition_by.iter().map(|s| s.to_string()));
        }
        if !config.is_empty() {
            b = b.with_configuration(
                config
                    .iter()
                    .map(|(k, v)| (k.to_string(), Some(v.to_string()))),
            );
        }
        b.await.expect("create table")
    }

    /// A batch for `schema` whose every row has partition value `p_of(row)`. Nullable
    /// columns carry nulls on a column-specific stride so null counts differ per column.
    fn gen_batch(
        schema: &SchemaRef,
        rows: usize,
        seed: u64,
        p_of: &dyn Fn(usize) -> String,
    ) -> RecordBatch {
        let mut rng = Lcg(seed);
        let base: Vec<i64> = (0..rows)
            .map(|_| (rng.next() % 2_000_000) as i64 - 1_000_000)
            .collect();
        let cols: Vec<ArrayRef> = schema
            .fields()
            .iter()
            .enumerate()
            .map(|(ci, f)| {
                let stride = 3 + ci;
                let null_at = |i: usize| f.is_nullable() && i.is_multiple_of(stride);
                let ints: ArrayRef = Arc::new(Int64Array::from(
                    (0..rows)
                        .map(|i| (!null_at(i)).then_some(base[i] / (ci as i64 + 1)))
                        .collect::<Vec<_>>(),
                ));
                let col: ArrayRef = match (f.name().as_str(), f.data_type()) {
                    ("id", _) => Arc::new(StringArray::from(
                        (0..rows)
                            .map(|i| format!("id-{seed}-{i}"))
                            .collect::<Vec<_>>(),
                    )),
                    ("p", _) => {
                        Arc::new(StringArray::from((0..rows).map(p_of).collect::<Vec<_>>()))
                    }
                    ("all_null", t) => arrow_array::new_null_array(t, rows),
                    (_, ArrowType::Utf8) => Arc::new(StringArray::from(
                        (0..rows)
                            .map(|i| (!null_at(i)).then(|| format!("s{}", base[i] % 977)))
                            .collect::<Vec<_>>(),
                    )),
                    (_, ArrowType::Binary) => {
                        let s = arrow_cast::cast(&ints, &ArrowType::Utf8).unwrap();
                        arrow_cast::cast(&s, &ArrowType::Binary).unwrap()
                    }
                    (_, ArrowType::Boolean) => {
                        let odd: ArrayRef = Arc::new(arrow_array::Int64Array::from(
                            (0..rows)
                                .map(|i| (!null_at(i)).then_some(base[i] & 1))
                                .collect::<Vec<_>>(),
                        ));
                        arrow_cast::cast(&odd, &ArrowType::Boolean).unwrap()
                    }
                    (_, ArrowType::Timestamp(_, _)) => {
                        let us: ArrayRef = Arc::new(Int64Array::from(
                            (0..rows)
                                .map(|i| {
                                    (!null_at(i))
                                        .then_some(1_700_000_000_000_000 + base[i] * 1_000_003)
                                })
                                .collect::<Vec<_>>(),
                        ));
                        arrow_cast::cast(&us, f.data_type()).unwrap()
                    }
                    (_, ArrowType::Date32) => {
                        let days: ArrayRef = Arc::new(arrow_array::Int32Array::from(
                            (0..rows)
                                .map(|i| (!null_at(i)).then_some((base[i] % 20_000) as i32))
                                .collect::<Vec<_>>(),
                        ));
                        arrow_cast::cast(&days, &ArrowType::Date32).unwrap()
                    }
                    (_, ArrowType::List(_)) => {
                        let mut b =
                            ListBuilder::new(Int64Builder::new()).with_field(match f.data_type() {
                                ArrowType::List(inner) => inner.clone(),
                                _ => unreachable!(),
                            });
                        for (i, v) in base.iter().enumerate() {
                            if null_at(i) {
                                b.append_null();
                            } else {
                                for k in 0..(i % 4) {
                                    b.values().append_value(v + k as i64);
                                }
                                b.append(true);
                            }
                        }
                        Arc::new(b.finish())
                    }
                    (_, ArrowType::Struct(fields)) => {
                        let a: ArrayRef = Arc::new(Int64Array::from(
                            (0..rows)
                                .map(|i| (i % 5 != 0).then_some(base[i]))
                                .collect::<Vec<_>>(),
                        ));
                        let b: ArrayRef = Arc::new(StringArray::from(
                            (0..rows)
                                .map(|i| (i % 7 != 0).then(|| format!("b{}", base[i] % 31)))
                                .collect::<Vec<_>>(),
                        ));
                        let nulls = arrow_buffer::NullBuffer::from(
                            (0..rows).map(|i| !null_at(i)).collect::<Vec<_>>(),
                        );
                        Arc::new(StructArray::new(fields.clone(), vec![a, b], Some(nulls)))
                    }
                    (_, t @ (ArrowType::Int8 | ArrowType::Int16)) => {
                        let small: ArrayRef = Arc::new(Int64Array::from(
                            (0..rows)
                                .map(|i| (!null_at(i)).then_some(base[i] % 120))
                                .collect::<Vec<_>>(),
                        ));
                        arrow_cast::cast(&small, t).unwrap()
                    }
                    (_, t) => arrow_cast::cast(&ints, t).unwrap(),
                };
                col
            })
            .collect();
        RecordBatch::try_new(schema.clone(), cols).unwrap()
    }

    /// One written file: its Add action and its bytes.
    struct Written {
        add: Add,
        bytes: Bytes,
    }

    /// Drive a writer exactly as `rewrite_partition` drives it: write, then flush
    /// whenever the buffer reaches `target`, then a final flush.
    async fn drive<W, F, B>(
        writer: &mut W,
        batches: &[RecordBatch],
        target: usize,
        mut write: F,
        buffer_len: B,
    ) -> Vec<Add>
    where
        F: AsyncFnMut(&mut W, RecordBatch),
        B: Fn(&W) -> usize,
        W: FlushAdds,
    {
        let mut adds = Vec::new();
        for b in batches {
            write(writer, b.clone()).await;
            if buffer_len(writer) >= target {
                adds.extend(writer.flush_adds().await);
            }
        }
        adds.extend(writer.flush_adds().await);
        adds
    }

    trait FlushAdds {
        async fn flush_adds(&mut self) -> Vec<Add>;
    }

    impl FlushAdds for RecordBatchWriter {
        async fn flush_adds(&mut self) -> Vec<Add> {
            self.flush().await.unwrap()
        }
    }

    impl FlushAdds for StreamingWriter {
        async fn flush_adds(&mut self) -> Vec<Add> {
            self.flush().await.unwrap()
        }
    }

    async fn read_back(table: &DeltaTable, adds: Vec<Add>) -> Vec<Written> {
        let store = table.object_store();
        let mut out = Vec::new();
        for add in adds {
            let bytes = store
                .get(&Path::parse(&add.path).unwrap())
                .await
                .unwrap()
                .bytes()
                .await
                .unwrap();
            out.push(Written { add, bytes });
        }
        // Flush order across partitions follows a HashMap; compare in a stable order.
        out.sort_by(|a, b| {
            let key = |w: &Written| {
                let mut pv: Vec<_> = w.add.partition_values.iter().collect();
                pv.sort();
                (format!("{pv:?}"), w.add.size, w.bytes.clone())
            };
            key(a).cmp(&key(b))
        });
        out
    }

    fn stats_json(add: &Add) -> Value {
        serde_json::from_str(add.stats.as_deref().expect("stats present")).unwrap()
    }

    /// Writes `batches` through both writers and asserts the outputs are the same files:
    /// byte-identical Parquet, identical sizes, partition values, stats and data
    /// layout (directory), differing only in the random file name.
    async fn assert_equivalent(
        case: &str,
        columns: Vec<StructField>,
        partition_by: &[&str],
        config: &[(&str, &str)],
        batches_of: &dyn Fn(&SchemaRef) -> Vec<RecordBatch>,
        target: usize,
    ) -> Vec<Written> {
        let dir = tempfile::tempdir().unwrap();
        let table = create_table(dir.path(), columns, partition_by, config).await;

        let mut old = RecordBatchWriter::for_table(&table).unwrap();
        let schema = old.arrow_schema();
        let batches = batches_of(&schema);
        let old_adds = drive(
            &mut old,
            &batches,
            target,
            async |w: &mut RecordBatchWriter, b| w.write(b).await.unwrap(),
            |w: &RecordBatchWriter| w.buffer_len(),
        )
        .await;

        let mut new = StreamingWriter::for_table(&table).unwrap();
        assert_eq!(new.arrow_schema, schema, "{case}: arrow schema");
        let new_adds = drive(
            &mut new,
            &batches,
            target,
            async |w: &mut StreamingWriter, b| w.write(b).unwrap(),
            |w: &StreamingWriter| w.buffer_len(),
        )
        .await;

        let old_files = read_back(&table, old_adds).await;
        let new_files = read_back(&table, new_adds).await;
        assert_eq!(
            old_files.len(),
            new_files.len(),
            "{case}: file count (rollover)"
        );
        assert!(!new_files.is_empty(), "{case}: wrote nothing");
        for (o, n) in old_files.iter().zip(&new_files) {
            assert_eq!(o.bytes, n.bytes, "{case}: parquet bytes differ");
            assert_eq!(o.add.size, n.add.size, "{case}: size");
            assert_eq!(
                n.add.size as usize,
                n.bytes.len(),
                "{case}: size is the object size"
            );
            assert_eq!(
                o.add.partition_values, n.add.partition_values,
                "{case}: partition values"
            );
            assert_eq!(stats_json(&o.add), stats_json(&n.add), "{case}: stats");
            assert_eq!(o.add.data_change, n.add.data_change, "{case}: dataChange");
            assert_eq!(o.add.tags, n.add.tags, "{case}: tags");
            assert!(n.add.deletion_vector.is_none());
            let (o_dir, o_name) = o.add.path.rsplit_once('/').unwrap_or(("", &o.add.path));
            let (n_dir, n_name) = n.add.path.rsplit_once('/').unwrap_or(("", &n.add.path));
            assert_eq!(o_dir, n_dir, "{case}: partition directory");
            let shape = |name: &str| {
                name.starts_with("part-00000-")
                    && name.ends_with("-c000.snappy.parquet")
                    && Uuid::parse_str(&name[11..47]).is_ok()
            };
            assert!(shape(o_name) && shape(n_name), "{case}: file name {n_name}");
        }
        new_files
    }

    fn single_partition_batches(n: usize, rows: usize) -> impl Fn(&SchemaRef) -> Vec<RecordBatch> {
        move |schema| {
            (0..n)
                .map(|i| gen_batch(schema, rows, 7 + i as u64, &|_| "2024-01-01T00".to_string()))
                .collect()
        }
    }

    #[tokio::test]
    async fn streaming_writer_output_matches_record_batch_writer() {
        let mixed = |schema: &SchemaRef| -> Vec<RecordBatch> {
            (0..4)
                .map(|i| {
                    gen_batch(schema, 3000, 100 + i, &|r| {
                        ["a b/c:d", "2024-01-01T01", "x%y", "ünï"][r % 4].to_string()
                    })
                })
                .collect()
        };
        type Case<'a> = (
            &'a str,
            fn() -> Vec<StructField>,
            &'a [&'a str],
            &'a [(&'a str, &'a str)],
            Box<dyn Fn(&SchemaRef) -> Vec<RecordBatch>>,
            usize,
            usize,
        );
        let cases: Vec<Case> = vec![
            (
                "unpartitioned, no rollover",
                wide_columns,
                &[],
                &[],
                Box::new(single_partition_batches(3, 2500)),
                usize::MAX,
                1,
            ),
            (
                "one partition per batch, rollover at 64 KiB",
                wide_columns,
                &["p"],
                &[],
                Box::new(single_partition_batches(12, 2000)),
                64 * 1024,
                3,
            ),
            (
                "batches spanning partitions that need percent-encoding",
                wide_columns,
                &["p"],
                &[],
                Box::new(mixed),
                usize::MAX,
                4,
            ),
            (
                "multi-partition batches with rollover",
                wide_columns,
                &["p"],
                &[],
                Box::new(mixed),
                96 * 1024,
                8,
            ),
            (
                "dataSkippingNumIndexedCols=3",
                wide_columns,
                &["p"],
                &[("delta.dataSkippingNumIndexedCols", "3")],
                Box::new(single_partition_batches(3, 1000)),
                usize::MAX,
                1,
            ),
            (
                "dataSkippingNumIndexedCols=-1 (falls back to 32, as delta-rs does)",
                wide_columns,
                &[],
                &[("delta.dataSkippingNumIndexedCols", "-1")],
                Box::new(single_partition_batches(2, 1000)),
                usize::MAX,
                1,
            ),
            (
                "dataSkippingStatsColumns",
                wide_columns,
                &["p"],
                &[("delta.dataSkippingStatsColumns", "lng,str,`ts`")],
                Box::new(single_partition_batches(3, 1000)),
                usize::MAX,
                1,
            ),
        ];
        for (case, columns, partition_by, config, batches_of, target, min_files) in cases {
            let files =
                assert_equivalent(case, columns(), partition_by, config, &*batches_of, target)
                    .await;
            assert!(
                files.len() >= min_files,
                "{case}: only {} files",
                files.len()
            );
        }
    }

    #[tokio::test]
    async fn equivalence_fixture_exercises_every_stats_type() {
        // Guards the comparison above against vacuous passes: the default-config stats
        // must actually carry min/max for each logical type the vendored code converts.
        let files = assert_equivalent(
            "stats coverage",
            wide_columns(),
            &["p"],
            &[],
            &single_partition_batches(1, 500),
            usize::MAX,
        )
        .await;
        let stats = stats_json(&files[0].add);
        for col in [
            "id",
            "lng",
            "int",
            "sht",
            "byt",
            "dbl",
            "flt",
            "bln",
            "dt",
            "ts",
            "str",
            "dec_small",
            "dec_wide",
        ] {
            assert!(
                stats["minValues"].get(col).is_some(),
                "no min for {col}: {stats}"
            );
            assert!(
                stats["maxValues"].get(col).is_some(),
                "no max for {col}: {stats}"
            );
        }
        assert!(stats["minValues"]["st"]["a"].is_number(), "{stats}");
        assert_eq!(stats["nullCount"]["all_null"], 500);
        assert!(stats["nullCount"].get("arr").is_some(), "{stats}");
        assert!(
            stats["minValues"].get("p").is_none(),
            "partition column has no stats"
        );
    }

    #[tokio::test]
    async fn streaming_writer_matches_on_multi_row_group_files() {
        // Over the 1Mi-row row-group limit, so stats aggregate across row groups.
        let files = assert_equivalent(
            "multi row group",
            narrow_columns(),
            &["p"],
            &[],
            &single_partition_batches(9, 130_000),
            usize::MAX,
        )
        .await;
        let meta = ParquetRecordBatchReaderBuilder::try_new(files[0].bytes.clone())
            .unwrap()
            .metadata()
            .clone();
        assert!(meta.num_row_groups() > 1, "fixture must span row groups");
    }

    #[tokio::test]
    async fn streaming_writer_files_read_back_as_written() {
        let dir = tempfile::tempdir().unwrap();
        let table = create_table(dir.path(), wide_columns(), &["p"], &[]).await;
        let mut w = StreamingWriter::for_table(&table).unwrap();
        let input = single_partition_batches(3, 1500)(&w.arrow_schema);
        for b in &input {
            w.write(b.clone()).unwrap();
        }
        let adds = w.flush().await.unwrap();
        assert_eq!(adds.len(), 1);
        let files = read_back(&table, adds).await;
        let read: Vec<RecordBatch> =
            ParquetRecordBatchReaderBuilder::try_new(files[0].bytes.clone())
                .unwrap()
                .build()
                .unwrap()
                .collect::<std::result::Result<_, _>>()
                .unwrap();
        let read = arrow_select::concat::concat_batches(&w.file_schema, &read).unwrap();
        let expected: Vec<RecordBatch> = input
            .iter()
            .map(|b| w.project_file_columns(b, None).unwrap())
            .collect();
        let expected = arrow_select::concat::concat_batches(&w.file_schema, &expected).unwrap();
        assert_eq!(read, expected);
        assert_eq!(stats_json(&files[0].add)["numRecords"], 4500);
        assert_eq!(
            files[0].add.partition_values.get("p"),
            Some(&Some("2024-01-01T00".to_string()))
        );
    }

    #[tokio::test]
    async fn flush_without_writes_adds_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let table = create_table(dir.path(), narrow_columns(), &["p"], &[]).await;
        let mut w = StreamingWriter::for_table(&table).unwrap();
        assert_eq!(w.buffer_len(), 0);
        assert!(w.flush().await.unwrap().is_empty());
    }
}
