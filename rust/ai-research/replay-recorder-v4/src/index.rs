//! The v4 index rows. The recorder sends each row as one JSON message to the index topic, and the Parquet sink writes
//! them to `rrweb-v4/index/`. The JSON keys are the Parquet column names in `replay-data.md`. Integer values fit the
//! signed column types parquetjs writes, and an INT64 value stays in the range a JavaScript number holds exactly,
//! which the sink checks: a value past either range saturates.
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

use replay_core_v4::inspect::session::Moment;
use replay_core_v4::inspect::stats::BlockStats;
use serde::ser::{SerializeMap, Serializer};
use serde::Serialize;

/// `Number.MAX_SAFE_INTEGER`. The sink refuses a row with an integer past it, and that row's flush is then never whole.
const MAX_SAFE_INTEGER: i64 = (1 << 53) - 1;

fn int64(value: u64) -> i64 {
    i64::try_from(value).map_or(MAX_SAFE_INTEGER, safe)
}

fn safe(value: i64) -> i64 {
    value.clamp(-MAX_SAFE_INTEGER, MAX_SAFE_INTEGER)
}

fn serialize_safe<S: Serializer>(value: &i64, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i64(safe(*value))
}

fn int32(value: u32) -> i32 {
    i32::try_from(value).unwrap_or(i32::MAX)
}

fn serialize_int64<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i64(int64(*value))
}

fn serialize_int32<S: Serializer>(value: &u32, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(int32(*value))
}

fn serialize_stats<S: Serializer>(stats: &&BlockStats, serializer: S) -> Result<S::Ok, S::Error> {
    // Destructured in full, so a new stats field does not compile until it has a column type here.
    let BlockStats {
        first_ts_ms,
        last_ts_ms,
        event_count,
        byte_size,
        host,
        full_snapshots,
        events_before_first_full_snapshot,
        orphan_mutations,
        max_gap_ms,
        dom_nodes,
        dom_text_chars,
        remote_stylesheets,
        inline_stylesheets,
        iframes,
        canvases,
        videos,
        shadow_roots,
        cold_start,
        node_cap_reached,
        active_ms,
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
        viewport_width,
        viewport_height,
        viewport_ts_ms,
        touch_input,
        images_extracted,
        image_bytes,
        images_inline,
        image_urls,
        written_jsonl_bytes,
        max_written_event_bytes,
        decode_failures,
        moments_truncated,
        mouse_interactions,
        touch_moves,
        url_fingerprints,
        window_ids,
    } = *stats;
    let mut map = serializer.serialize_map(None)?;
    macro_rules! columns {
        ($convert:expr => $($field:ident),*) => {
            $( map.serialize_entry(stringify!($field), &$convert($field))?; )*
        };
    }
    columns!(|v: &Option<i64>| v.map(safe) => first_ts_ms, last_ts_ms, viewport_ts_ms);
    columns!(|v: &i64| safe(*v) => max_gap_ms, active_ms);
    columns!(
        |v: &u64| int64(*v) =>
        event_count,
        byte_size,
        dom_text_chars,
        image_bytes,
        written_jsonl_bytes,
        max_written_event_bytes
    );
    columns!(|v: &bool| *v => cold_start, node_cap_reached, moments_truncated, touch_input);
    columns!(|v: &Vec<String>| v.clone() => url_fingerprints, window_ids);
    columns!(|v: &Option<u32>| v.map(int32) => viewport_width, viewport_height);
    columns!(
        |v: &u32| int32(*v) =>
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
        shadow_roots,
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
    map.serialize_entry("host", host)?;
    map.end()
}

fn serialize_moments<S: Serializer>(moments: &&[Moment], serializer: S) -> Result<S::Ok, S::Error> {
    #[derive(Serialize)]
    struct Entry<'a> {
        kind: &'a str,
        window_id: &'a str,
        ts_ms: i64,
        event_index: i32,
    }
    serializer.collect_seq(moments.iter().map(|moment| Entry {
        kind: moment.kind,
        window_id: &moment.window_id,
        ts_ms: safe(moment.ts_ms),
        event_index: int32(moment.event_index),
    }))
}

/// Where one inline image sits in a pack in `images-v4`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ImageIndexRow {
    #[serde(serialize_with = "serialize_safe")]
    pub team_id: i64,
    pub key_month: String,
    pub image_ref: String,
    pub pack_s3_key: String,
    /// Inclusive byte range of the sealed image in the pack.
    #[serde(serialize_with = "serialize_int64")]
    pub byte_start: u64,
    #[serde(serialize_with = "serialize_int64")]
    pub byte_end: u64,
    pub mime: String,
    #[serde(serialize_with = "serialize_int64")]
    pub byte_size: u64,
}

/// One block's index row: where it is, what the inspector found, and its sealed URLs.
#[derive(Debug, Serialize)]
pub struct BlockIndexRow<'a> {
    #[serde(serialize_with = "serialize_safe")]
    pub team_id: i64,
    pub session_id: &'a str,
    pub key_month: &'a str,
    pub block_s3_key: &'a str,
    pub topic: &'static str,
    pub partition: i32,
    #[serde(serialize_with = "serialize_safe")]
    pub start_offset: i64,
    #[serde(serialize_with = "serialize_safe")]
    pub end_offset: i64,
    /// The last offset the flush covers on the partition, a message that gave no row included.
    #[serde(serialize_with = "serialize_safe")]
    pub flush_end_offset: i64,
    /// The block rows this flush writes for the partition, and this row's place among them. With `flush_id`,
    /// `topic` and `partition`, the place names the row across retries of the same publish.
    #[serde(serialize_with = "serialize_int32")]
    pub flush_row_count: u32,
    #[serde(serialize_with = "serialize_int32")]
    pub flush_row_index: u32,
    pub flush_id: &'a str,
    #[serde(serialize_with = "serialize_safe")]
    pub flushed_at_ms: i64,
    /// Inclusive byte range of the sealed frame in the block object.
    #[serde(serialize_with = "serialize_int64")]
    pub block_byte_start: u64,
    #[serde(serialize_with = "serialize_int64")]
    pub block_byte_end: u64,
    #[serde(flatten, serialize_with = "serialize_stats")]
    pub stats: &'a BlockStats,
    pub snapshot_source: Option<&'a str>,
    pub snapshot_library: Option<&'a str>,
    #[serde(serialize_with = "serialize_moments")]
    pub moments: &'a [Moment],
    /// The block's visited URLs as a v4 JSON envelope under the session key.
    pub urls: Option<String>,
    /// Some visited URLs are not in `urls`: the block had more, or longer, than an index row keeps.
    pub urls_truncated: bool,
    /// Goes in the `capture-timestamp-ms` header, not in the row.
    #[serde(skip)]
    pub captured_at_ms: Option<i64>,
}

/// The index a row belongs to, as the `ml-index` header names it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Index {
    Blocks,
    Images,
}

impl Index {
    pub fn as_str(self) -> &'static str {
        match self {
            Index::Blocks => "blocks",
            Index::Images => "images",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IndexMessage {
    pub index: Index,
    /// The session ID of a block row, the image reference of an image row.
    pub key: String,
    pub payload: Vec<u8>,
    pub captured_at_ms: Option<i64>,
}

impl IndexMessage {
    pub fn block(row: &BlockIndexRow<'_>) -> serde_json::Result<Self> {
        Ok(Self {
            index: Index::Blocks,
            key: row.session_id.to_owned(),
            payload: serde_json::to_vec(row)?,
            captured_at_ms: row.captured_at_ms,
        })
    }

    pub fn image(row: &ImageIndexRow, captured_at_ms: Option<i64>) -> serde_json::Result<Self> {
        Ok(Self {
            index: Index::Images,
            key: row.image_ref.clone(),
            payload: serde_json::to_vec(row)?,
            captured_at_ms,
        })
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;

    /// The columns of the Parquet files the recorder wrote before the sink took them over, in file order, with their
    /// parquetjs type and whether they are optional. The sink writes the same files, so a renamed field or a changed
    /// type here breaks every reader.
    const BLOCK_COLUMNS: &[(&str, &str, bool)] = &[
        ("team_id", "INT64", false),
        ("session_id", "UTF8", false),
        ("key_month", "UTF8", false),
        ("block_s3_key", "UTF8", false),
        ("topic", "UTF8", false),
        ("partition", "INT32", false),
        ("start_offset", "INT64", false),
        ("end_offset", "INT64", false),
        ("flush_end_offset", "INT64", false),
        ("flush_row_count", "INT32", false),
        ("flush_row_index", "INT32", false),
        ("flush_id", "UTF8", false),
        ("flushed_at_ms", "INT64", false),
        ("block_byte_start", "INT64", false),
        ("block_byte_end", "INT64", false),
        ("first_ts_ms", "INT64", true),
        ("last_ts_ms", "INT64", true),
        ("event_count", "INT64", false),
        ("byte_size", "INT64", false),
        ("snapshot_source", "UTF8", true),
        ("snapshot_library", "UTF8", true),
        ("host", "UTF8", true),
        ("full_snapshots", "INT32", false),
        ("events_before_first_full_snapshot", "INT32", false),
        ("orphan_mutations", "INT32", false),
        ("decode_failures", "INT32", false),
        ("dom_nodes", "INT32", false),
        ("remote_stylesheets", "INT32", false),
        ("inline_stylesheets", "INT32", false),
        ("iframes", "INT32", false),
        ("canvases", "INT32", false),
        ("videos", "INT32", false),
        ("shadow_roots", "INT32", false),
        ("max_gap_ms", "INT64", false),
        ("active_ms", "INT64", false),
        ("dom_text_chars", "INT64", false),
        ("cold_start", "BOOLEAN", false),
        ("node_cap_reached", "BOOLEAN", false),
        ("moments_truncated", "BOOLEAN", false),
        ("touch_input", "BOOLEAN", false),
        ("clicks", "INT32", false),
        ("mouse_interactions", "INT32", false),
        ("rage_clicks", "INT32", false),
        ("dead_clicks", "INT32", false),
        ("keypresses", "INT32", false),
        ("scrolls", "INT32", false),
        ("mouse_moves", "INT32", false),
        ("touches", "INT32", false),
        ("touch_moves", "INT32", false),
        ("selections", "INT32", false),
        ("media_events", "INT32", false),
        ("viewport_resizes", "INT32", false),
        ("navigations", "INT32", false),
        ("console_errors", "INT32", false),
        ("console_warnings", "INT32", false),
        ("network_requests", "INT32", false),
        ("network_failures", "INT32", false),
        ("images_extracted", "INT32", false),
        ("images_inline", "INT32", false),
        ("image_urls", "INT32", false),
        ("image_bytes", "INT64", false),
        ("written_jsonl_bytes", "INT64", false),
        ("max_written_event_bytes", "INT64", false),
        ("viewport_width", "INT32", true),
        ("viewport_height", "INT32", true),
        ("viewport_ts_ms", "INT64", true),
        ("moments", "MOMENTS", false),
        ("url_fingerprints", "LIST<UTF8>", false),
        ("window_ids", "LIST<UTF8>", false),
        ("urls", "UTF8", true),
        ("urls_truncated", "BOOLEAN", false),
    ];

    const IMAGE_COLUMNS: &[(&str, &str, bool)] = &[
        ("team_id", "INT64", false),
        ("key_month", "UTF8", false),
        ("image_ref", "UTF8", false),
        ("pack_s3_key", "UTF8", false),
        ("byte_start", "INT64", false),
        ("byte_end", "INT64", false),
        ("mime", "UTF8", false),
        ("byte_size", "INT64", false),
    ];

    fn fits(value: &Value, column_type: &str) -> bool {
        match column_type {
            "UTF8" => value.is_string(),
            "BOOLEAN" => value.is_boolean(),
            "INT64" => value.as_i64().is_some_and(|n| n.abs() <= MAX_SAFE_INTEGER),
            "INT32" => value.as_i64().is_some_and(|n| i32::try_from(n).is_ok()),
            "LIST<UTF8>" => value
                .as_array()
                .is_some_and(|items| items.iter().all(|item| fits(item, "UTF8"))),
            "MOMENTS" => value.as_array().is_some_and(|moments| {
                moments.iter().all(|moment| {
                    let moment = moment.as_object().unwrap();
                    moment.len() == 4
                        && fits(&moment["kind"], "UTF8")
                        && fits(&moment["window_id"], "UTF8")
                        && fits(&moment["ts_ms"], "INT64")
                        && fits(&moment["event_index"], "INT32")
                })
            }),
            other => panic!("no column type {other}"),
        }
    }

    /// Parses a row and checks it has exactly the columns, each value of its column's type.
    fn assert_columns(payload: &[u8], columns: &[(&str, &str, bool)]) -> Value {
        let value: Value = serde_json::from_slice(payload).unwrap();
        let row = value.as_object().unwrap();
        let mut keys: Vec<&str> = row.keys().map(String::as_str).collect();
        keys.sort_unstable();
        let mut names: Vec<&str> = columns.iter().map(|(name, _, _)| *name).collect();
        names.sort_unstable();
        assert_eq!(keys, names);
        for (name, column_type, optional) in columns {
            let cell = &row[*name];
            assert!(
                (*optional && cell.is_null()) || fits(cell, column_type),
                "{name} = {cell} is not {column_type}"
            );
        }
        value
    }

    #[test]
    fn rows_have_exactly_the_parquet_columns_and_types() {
        let stats = BlockStats {
            // 2^53, and a 1e100 timestamp read as an integer: past what JavaScript holds exactly.
            first_ts_ms: Some(1 << 53),
            max_gap_ms: i64::MIN,
            event_count: u64::MAX,
            clicks: u32::MAX,
            viewport_width: Some(u32::MAX),
            written_jsonl_bytes: u64::MAX,
            url_fingerprints: vec!["b08517cee3ff5ecc".to_owned()],
            window_ids: vec!["w1".to_owned(), "w2".to_owned()],
            ..BlockStats::default()
        };
        let moments = [Moment {
            kind: "full_snapshot",
            window_id: "w1".into(),
            ts_ms: 1e100 as i64,
            event_index: u32::MAX,
        }];
        let block = BlockIndexRow {
            team_id: 7,
            session_id: "s",
            key_month: "2026-09",
            block_s3_key: "blocks/dt=2026-10-15/1-0",
            topic: "main",
            partition: 2,
            start_offset: 100,
            end_offset: 105,
            flush_end_offset: 107,
            flush_row_count: u32::MAX,
            flush_row_index: 0,
            flush_id: "0000000000000001",
            flushed_at_ms: 1_000,
            block_byte_start: 0,
            block_byte_end: u64::MAX,
            stats: &stats,
            snapshot_source: Some("web"),
            snapshot_library: None,
            moments: &moments,
            urls: None,
            urls_truncated: false,
            captured_at_ms: Some(5),
        };
        let message = IndexMessage::block(&block).unwrap();
        let value = assert_columns(&message.payload, BLOCK_COLUMNS);
        assert_eq!(
            [
                &value["first_ts_ms"],
                &value["max_gap_ms"],
                &value["last_ts_ms"],
                &value["cold_start"],
                &value["snapshot_library"],
                &value["event_count"],
                &value["block_byte_end"],
                &value["clicks"],
                &value["viewport_width"],
                &value["written_jsonl_bytes"],
                &value["flush_row_count"],
                &value["url_fingerprints"],
                &value["window_ids"],
            ],
            [
                &json!(MAX_SAFE_INTEGER),
                &json!(-MAX_SAFE_INTEGER),
                &Value::Null,
                &json!(false),
                &Value::Null,
                &json!(MAX_SAFE_INTEGER),
                &json!(MAX_SAFE_INTEGER),
                &json!(i32::MAX),
                &json!(i32::MAX),
                &json!(MAX_SAFE_INTEGER),
                &json!(i32::MAX),
                &json!(["b08517cee3ff5ecc"]),
                &json!(["w1", "w2"]),
            ]
        );
        assert_eq!(
            value["moments"],
            json!([{"kind": "full_snapshot", "window_id": "w1", "ts_ms": MAX_SAFE_INTEGER, "event_index": i32::MAX}])
        );

        let image = ImageIndexRow {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            image_ref: "image:v4:7:2026-10:abc".to_owned(),
            pack_s3_key: "images/packs/dt=2026-10-15/7/1-0".to_owned(),
            byte_start: 0,
            byte_end: 99,
            mime: "image/png".to_owned(),
            byte_size: u64::MAX,
        };
        let message = IndexMessage::image(&image, None).unwrap();
        let value = assert_columns(&message.payload, IMAGE_COLUMNS);
        assert_eq!(value["byte_size"], json!(MAX_SAFE_INTEGER));
    }
}
