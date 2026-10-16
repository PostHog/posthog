//! The v4 index files: Parquet in `rrweb-v4/index/`. Column names are the ones in `replay-data.md`.
//!
//! A flush can store its blocks and index rows and then fail before it commits its Kafka offsets. The next attempt
//! for the partition, in this process or after a restart, starts again at the same committed offset and writes the
//! same messages again. Every block index row therefore names its flush attempt (`flush_id`, `flushed_at_ms`) and the
//! Kafka data it came from (`topic`, `partition`, `start_offset` of the flush on that partition, the block's own
//! `end_offset`). The rule for readers: for each (`topic`, `partition`, `start_offset`), keep only the rows of the
//! latest flush, the one with the highest (`flushed_at_ms`, `flush_id`). The rows of every other flush with that
//! start are duplicates of messages the latest flush wrote again.

use std::sync::Arc;

use arrow_array::builder::{
    Int64Builder, ListBuilder, StringBuilder, StructBuilder, UInt32Builder,
};
use arrow_array::{
    ArrayRef, BooleanArray, Int32Array, Int64Array, RecordBatch, StringArray, UInt32Array,
    UInt64Array,
};
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

/// Where one inline image sits in a pack in `images-v4`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageIndexRow {
    pub team_id: i64,
    pub key_day: String,
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
        Field::new("key_day", DataType::Utf8, false),
        Field::new("image_ref", DataType::Utf8, false),
        Field::new("pack_s3_key", DataType::Utf8, false),
        Field::new("byte_start", DataType::UInt64, false),
        Field::new("byte_end", DataType::UInt64, false),
        Field::new("mime", DataType::Utf8, false),
        Field::new("byte_size", DataType::UInt64, false),
    ]);
    let columns: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from_iter_values(rows.iter().map(|r| r.team_id))),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.key_day),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.image_ref),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.pack_s3_key),
        )),
        Arc::new(UInt64Array::from_iter_values(
            rows.iter().map(|r| r.byte_start),
        )),
        Arc::new(UInt64Array::from_iter_values(
            rows.iter().map(|r| r.byte_end),
        )),
        Arc::new(StringArray::from_iter_values(rows.iter().map(|r| &r.mime))),
        Arc::new(UInt64Array::from_iter_values(
            rows.iter().map(|r| r.byte_size),
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
}

fn moment_fields() -> Fields {
    Fields::from(vec![
        Field::new("kind", DataType::Utf8, false),
        Field::new("window_id", DataType::Utf8, false),
        Field::new("ts_ms", DataType::Int64, false),
        Field::new("event_index", DataType::UInt32, false),
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
                .field_builder::<UInt32Builder>(3)
                .expect("event_index")
                .append_value(moment.event_index);
            entries.append(true);
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
        ($array:ident, $data_type:expr, $($field:ident),*) => {
            $( push(stringify!($field), $data_type, false, Arc::new($array::from_iter_values(rows.iter().map(|r| r.stats.$field)))); )*
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
    utf8!("key_day", |r| r.written.key_day.clone());
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
        "block_byte_start",
        DataType::UInt64,
        false,
        Arc::new(UInt64Array::from_iter_values(
            rows.iter().map(|r| r.written.byte_start),
        )),
    );
    push(
        "block_byte_end",
        DataType::UInt64,
        false,
        Arc::new(UInt64Array::from_iter_values(
            rows.iter().map(|r| r.written.byte_end),
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
    stat!(UInt64Array, DataType::UInt64, event_count, byte_size);
    optional_utf8!("snapshot_source", |r| r.snapshot_source);
    optional_utf8!("snapshot_library", |r| r.snapshot_library);
    optional_utf8!("host", |r| r.stats.host.as_deref());
    stat!(
        UInt32Array,
        DataType::UInt32,
        full_snapshots,
        events_before_first_full_snapshot,
        orphan_mutations,
        dom_nodes,
        remote_stylesheets,
        inline_stylesheets,
        iframes,
        canvases,
        videos,
        shadow_roots
    );
    stat!(Int64Array, DataType::Int64, max_gap_ms, active_ms);
    stat!(UInt64Array, DataType::UInt64, dom_text_chars);
    flag!(cold_start, node_cap_reached, touch_input);
    stat!(
        UInt32Array,
        DataType::UInt32,
        clicks,
        rage_clicks,
        dead_clicks,
        keypresses,
        scrolls,
        mouse_moves,
        touches,
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
    stat!(UInt64Array, DataType::UInt64, image_bytes);
    push(
        "viewport_width",
        DataType::UInt32,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.viewport_width)
                .collect::<UInt32Array>(),
        ),
    );
    push(
        "viewport_height",
        DataType::UInt32,
        true,
        Arc::new(
            rows.iter()
                .map(|r| r.stats.viewport_height)
                .collect::<UInt32Array>(),
        ),
    );
    let moments = moments_column(rows);
    push("moments", moments.data_type().clone(), false, moments);
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
            key_day: "2026-10-15".to_owned(),
            image_ref: "image:v4:7:2026-10-15:abc".to_owned(),
            pack_s3_key: "images/packs/dt=2026-10-15/7/1-0".to_owned(),
            byte_start: 0,
            byte_end: 99,
            mime: "image/png".to_owned(),
            byte_size: 60,
        }];
        let file = write_parquet(&image_index(&rows).unwrap()).unwrap();
        let mut reader = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(file))
            .unwrap()
            .build()
            .unwrap();
        let batch = reader.next().unwrap().unwrap();
        let names: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect();
        assert_eq!(
            names,
            [
                "team_id",
                "key_day",
                "image_ref",
                "pack_s3_key",
                "byte_start",
                "byte_end",
                "mime",
                "byte_size"
            ]
        );
        let refs = batch
            .column(2)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(refs.value(0), "image:v4:7:2026-10-15:abc");
    }
}
