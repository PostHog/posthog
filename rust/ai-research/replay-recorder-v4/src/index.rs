//! The v4 index files: Parquet in `rrweb-v4/index/`. Column names are the ones in `replay-data.md`.
//!
//! Integer columns are signed, the types parquetjs writes, so a parquetjs writer can produce the same files.
//!
//! A flush can store its blocks and index rows and then fail before it commits its Kafka offsets. The next attempt
//! for the partition, in this process or after a restart, starts again at the same committed offset and writes the
//! same messages again. Every block index row therefore names its flush attempt (`flush_id`, `flushed_at_ms`) and the
//! Kafka data it came from (`topic`, `partition`, `start_offset` of the flush on that partition, the block's own
//! `end_offset`). A retry can cover a different range than the attempts it replaces, so the rule for readers works on
//! ranges: per (`topic`, `partition`), a flush covers its `start_offset` to its highest `end_offset`. Walk the flushes
//! from the highest (`flushed_at_ms`, `flush_id`) and keep a flush only if its range overlaps no flush already kept.
//!
//! The rows of a flush can also arrive in part. Per (`flush_id`, `topic`, `partition`), every row holds the same
//! `flush_end_offset`, the last offset the flush covers there, and `flush_row_count`, the rows it writes there. The
//! flush is whole when that many distinct `flush_row_index` values are present. Check this before any filter on
//! sessions or teams.

use std::sync::Arc;

use arrow_array::builder::{Int32Builder, Int64Builder, ListBuilder, StringBuilder, StructBuilder};
use arrow_array::{ArrayRef, BooleanArray, Int32Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{ArrowError, DataType, Field, Fields, Schema};
use replay_core_v4::inspect::session::Moment;
use replay_core_v4::inspect::stats::BlockStats;

use crate::batch::Origin;
use crate::write::{FlushAttempt, Written};
use parquet::arrow::ArrowWriter;
use parquet::basic::Compression;
use parquet::errors::ParquetError;
use parquet::file::properties::WriterProperties;

#[derive(Debug, thiserror::Error)]
pub enum IndexError {
    #[error(transparent)]
    Arrow(#[from] ArrowError),
    #[error(transparent)]
    Parquet(#[from] ParquetError),
}

/// Writes one Parquet file, snappy-compressed as the v3 catalog is.
pub fn write_parquet(batch: &RecordBatch) -> Result<Vec<u8>, IndexError> {
    let properties = WriterProperties::builder()
        .set_compression(Compression::SNAPPY)
        .build();
    let mut out = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut out, batch.schema(), Some(properties))?;
    writer.write(batch)?;
    writer.close()?;
    Ok(out)
}

/// A count or size as its signed column. Real values fit, and a larger one saturates.
fn int64(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

/// A count as its signed column. Real values fit, and a larger one saturates.
fn int32(value: u32) -> i32 {
    i32::try_from(value).unwrap_or(i32::MAX)
}

/// Where one inline image sits in a pack in `images-v4`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageIndexRow {
    pub team_id: i64,
    pub key_month: String,
    pub image_ref: String,
    pub pack_s3_key: String,
    /// Inclusive byte range of the sealed image in the pack.
    pub byte_start: u64,
    pub byte_end: u64,
    pub mime: String,
    pub byte_size: u64,
}

pub fn image_index(rows: &[ImageIndexRow]) -> Result<RecordBatch, IndexError> {
    let schema = Schema::new(vec![
        Field::new("team_id", DataType::Int64, false),
        Field::new("key_month", DataType::Utf8, false),
        Field::new("image_ref", DataType::Utf8, false),
        Field::new("pack_s3_key", DataType::Utf8, false),
        Field::new("byte_start", DataType::Int64, false),
        Field::new("byte_end", DataType::Int64, false),
        Field::new("mime", DataType::Utf8, false),
        Field::new("byte_size", DataType::Int64, false),
    ]);
    let columns: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from_iter_values(rows.iter().map(|r| r.team_id))),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.key_month),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.image_ref),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.pack_s3_key),
        )),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_start)),
        )),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_end)),
        )),
        Arc::new(StringArray::from_iter_values(rows.iter().map(|r| &r.mime))),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_size)),
        )),
    ];
    Ok(RecordBatch::try_new(Arc::new(schema), columns)?)
}

/// One block's index row: where it is, what the inspector found, and its sealed URLs.
pub struct BlockIndexRow<'a> {
    pub written: &'a Written,
    pub origin: &'a Origin,
    pub attempt: &'a FlushAttempt,
    pub stats: &'a BlockStats,
    pub moments: &'a [Moment],
    pub snapshot_source: Option<&'a str>,
    pub snapshot_library: Option<&'a str>,
    /// The block's visited URLs as a v4 JSON envelope under the session key.
    pub urls: Option<String>,
    /// The block rows this flush writes for the row's partition, and the row's place among them. With `flush_id`,
    /// `topic` and `partition`, the place names the row across retries of the same publish.
    pub flush_row_count: u32,
    pub flush_row_index: u32,
}

fn moment_fields() -> Fields {
    Fields::from(vec![
        Field::new("kind", DataType::Utf8, false),
        Field::new("window_id", DataType::Utf8, false),
        Field::new("ts_ms", DataType::Int64, false),
        Field::new("event_index", DataType::Int32, false),
    ])
}

fn moments_column(rows: &[BlockIndexRow<'_>]) -> ArrayRef {
    let fields = moment_fields();
    let mut builder = ListBuilder::new(StructBuilder::from_fields(fields.clone(), rows.len()))
        .with_field(Field::new("item", DataType::Struct(fields), false));
    for row in rows {
        let entries = builder.values();
        for moment in row.moments {
            entries
                .field_builder::<StringBuilder>(0)
                .expect("kind")
                .append_value(moment.kind);
            entries
                .field_builder::<StringBuilder>(1)
                .expect("window_id")
                .append_value(&moment.window_id);
            entries
                .field_builder::<Int64Builder>(2)
                .expect("ts_ms")
                .append_value(moment.ts_ms);
            entries
                .field_builder::<Int32Builder>(3)
                .expect("event_index")
                .append_value(int32(moment.event_index));
            entries.append(true);
        }
        builder.append(true);
    }
    Arc::new(builder.finish())
}

/// A list of strings per row, with no null lists or items.
fn strings_column(rows: &[BlockIndexRow<'_>], values: fn(&BlockStats) -> &[String]) -> ArrayRef {
    let mut builder = ListBuilder::new(StringBuilder::new()).with_field(Field::new(
        "item",
        DataType::Utf8,
        false,
    ));
    for row in rows {
        for value in values(row.stats) {
            builder.values().append_value(value);
        }
        builder.append(true);
    }
    Arc::new(builder.finish())
}

pub fn block_index(rows: &[BlockIndexRow<'_>]) -> Result<RecordBatch, IndexError> {
    let mut fields = Vec::new();
    let mut columns: Vec<ArrayRef> = Vec::new();
    let mut push = |name: &str, data_type: DataType, nullable: bool, column: ArrayRef| {
        fields.push(Field::new(name, data_type, nullable));
        columns.push(column);
    };
    macro_rules! utf8 {
        ($name:literal, $value:expr) => {
            push(
                $name,
                DataType::Utf8,
                false,
                Arc::new(StringArray::from_iter_values(rows.iter().map($value))),
            )
        };
    }
    macro_rules! optional_utf8 {
        ($name:literal, $value:expr) => {
            push(
                $name,
                DataType::Utf8,
                true,
                Arc::new(rows.iter().map($value).collect::<StringArray>()),
            )
        };
    }
    macro_rules! stat {
        ($array:ident, $data_type:expr, $convert:expr, $($field:ident),*) => {
            $( push(stringify!($field), $data_type, false, Arc::new($array::from_iter_values(rows.iter().map(|r| $convert(r.stats.$field))))); )*
        };
    }
    macro_rules! flag {
        ($($field:ident),*) => {
            $( push(stringify!($field), DataType::Boolean, false, Arc::new(rows.iter().map(|r| Some(r.stats.$field)).collect::<BooleanArray>())); )*
        };
    }

    push(
        "team_id",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| r.written.session.team_id),
        )),
    );
    utf8!("session_id", |r| r.written.session.session_id.clone());
    utf8!("key_month", |r| r.written.key_month.clone());
    utf8!("block_s3_key", |r| r.written.object_key.clone());
    utf8!("topic", |r| r.origin.tp.topic);
    push(
        "partition",
        DataType::Int32,
        false,
        Arc::new(Int32Array::from_iter_values(
            rows.iter().map(|r| r.origin.tp.partition),
        )),
    );
    push(
        "start_offset",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| r.origin.start_offset),
        )),
    );
    push(
        "end_offset",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| r.origin.end_offset),
        )),
    );
    utf8!("flush_id", |r| r.attempt.flush_id.clone());
    push(
        "flushed_at_ms",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| r.attempt.flushed_at_ms),
        )),
    );
    push(
        "flush_end_offset",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| r.origin.flush_end_offset),
        )),
    );
    push(
        "flush_row_count",
        DataType::Int32,
        false,
        Arc::new(Int32Array::from_iter_values(
            rows.iter().map(|r| int32(r.flush_row_count)),
        )),
    );
    push(
        "flush_row_index",
        DataType::Int32,
        false,
        Arc::new(Int32Array::from_iter_values(
            rows.iter().map(|r| int32(r.flush_row_index)),
        )),
    );
    push(
        "block_byte_start",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.written.byte_start)),
        )),
    );
    push(
        "block_byte_end",
        DataType::Int64,
        false,
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.written.byte_end)),
        )),
    );
    push(
        "first_ts_ms",
        DataType::Int64,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.first_ts_ms)
                .collect::<Int64Array>(),
        ),
    );
    push(
        "last_ts_ms",
        DataType::Int64,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.last_ts_ms)
                .collect::<Int64Array>(),
        ),
    );
    stat!(Int64Array, DataType::Int64, int64, event_count, byte_size);
    optional_utf8!("snapshot_source", |r| r.snapshot_source);
    optional_utf8!("snapshot_library", |r| r.snapshot_library);
    optional_utf8!("host", |r| r.stats.host.as_deref());
    stat!(
        Int32Array,
        DataType::Int32,
        int32,
        full_snapshots,
        events_before_first_full_snapshot,
        orphan_mutations,
        decode_failures,
        dom_nodes,
        remote_stylesheets,
        inline_stylesheets,
        iframes,
        canvases,
        videos,
        shadow_roots
    );
    stat!(
        Int64Array,
        DataType::Int64,
        i64::from,
        max_gap_ms,
        active_ms
    );
    stat!(Int64Array, DataType::Int64, int64, dom_text_chars);
    flag!(cold_start, node_cap_reached, moments_truncated, touch_input);
    stat!(
        Int32Array,
        DataType::Int32,
        int32,
        clicks,
        mouse_interactions,
        rage_clicks,
        dead_clicks,
        keypresses,
        scrolls,
        mouse_moves,
        touches,
        touch_moves,
        selections,
        media_events,
        viewport_resizes,
        navigations,
        console_errors,
        console_warnings,
        network_requests,
        network_failures,
        images_extracted,
        images_inline,
        image_urls
    );
    stat!(
        Int64Array,
        DataType::Int64,
        int64,
        image_bytes,
        written_jsonl_bytes,
        max_written_event_bytes
    );
    push(
        "viewport_width",
        DataType::Int32,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.viewport_width.map(int32))
                .collect::<Int32Array>(),
        ),
    );
    push(
        "viewport_height",
        DataType::Int32,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.viewport_height.map(int32))
                .collect::<Int32Array>(),
        ),
    );
    push(
        "viewport_ts_ms",
        DataType::Int64,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.viewport_ts_ms)
                .collect::<Int64Array>(),
        ),
    );
    let moments = moments_column(rows);
    push("moments", moments.data_type().clone(), false, moments);
    let fingerprints = strings_column(rows, |s| &s.url_fingerprints);
    push(
        "url_fingerprints",
        fingerprints.data_type().clone(),
        false,
        fingerprints,
    );
    let windows = strings_column(rows, |s| &s.window_ids);
    push("window_ids", windows.data_type().clone(), false, windows);
    optional_utf8!("urls", |r| r.urls.as_deref());
    Ok(RecordBatch::try_new(
        Arc::new(Schema::new(fields)),
        columns,
    )?)
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

    use super::*;

    #[test]
    fn image_index_reads_back_with_the_documented_columns() {
        let rows = vec![ImageIndexRow {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            image_ref: "image:v4:7:2026-10:abc".to_owned(),
            pack_s3_key: "images/packs/dt=2026-10-15/7/1-0".to_owned(),
            byte_start: 0,
            byte_end: 99,
            mime: "image/png".to_owned(),
            byte_size: u64::MAX,
        }];
        let file = write_parquet(&image_index(&rows).unwrap()).unwrap();
        let mut reader = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(file))
            .unwrap()
            .build()
            .unwrap();
        let batch = reader.next().unwrap().unwrap();
        let columns: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| (f.name().clone(), f.data_type().clone(), f.is_nullable()))
            .collect();
        let column = |name: &str, data_type| (name.to_owned(), data_type, false);
        assert_eq!(
            columns,
            [
                column("team_id", DataType::Int64),
                column("key_month", DataType::Utf8),
                column("image_ref", DataType::Utf8),
                column("pack_s3_key", DataType::Utf8),
                column("byte_start", DataType::Int64),
                column("byte_end", DataType::Int64),
                column("mime", DataType::Utf8),
                column("byte_size", DataType::Int64),
            ]
        );
        let sizes = batch
            .column(7)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        assert_eq!(sizes.value(0), i64::MAX);
        let refs = batch
            .column(2)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(refs.value(0), "image:v4:7:2026-10:abc");
    }
}
