//! Reads one v4 index row from its Kafka message, as the recorder sends it, and keeps only rows that fit the columns.
//! A bad row must not reach the writer, which would fail the whole flush.

use std::borrow::Cow;

use chrono::NaiveDate;

use crate::columns::{Column, Index, LeafColumn, LeafType};
use crate::json::{self, JsString, Json};
use crate::metrics;

pub const INDEX_HEADER: &str = "ml-index";
/// The UTC day of the objects the row points at, the `dt=` partition of its file.
pub const WRITE_DAY_HEADER: &str = "ml-write-day";
/// The Kafka timestamp of the replay record the row came from.
pub const CAPTURE_TIMESTAMP_HEADER: &str = "capture-timestamp-ms";

const MAX_LOGGED_SESSION_ID_LENGTH: usize = 70;
const INT32_MIN: f64 = -2_147_483_648.0;
const INT32_MAX: f64 = 2_147_483_647.0;
/// `Number.MAX_SAFE_INTEGER`. A JSON number past it has lost precision on parse, so an INT64 column refuses it.
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

#[derive(Debug, Clone, PartialEq)]
pub enum Cell {
    Null,
    Bool(bool),
    Int32(i32),
    Int64(i64),
    Utf8(JsString<'static>),
    List(Vec<Cell>),
    Structs(Vec<Box<[Cell]>>),
}

pub type Row = Box<[Cell]>;

/// The last value of each header, decoded as UTF-8 with replacement.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Headers {
    pub index: Option<String>,
    pub write_day: Option<String>,
    pub capture_timestamp: Option<String>,
}

impl Headers {
    pub fn from_pairs<'h>(pairs: impl IntoIterator<Item = (&'h str, Option<&'h [u8]>)>) -> Self {
        let mut headers = Self::default();
        for (key, value) in pairs {
            let slot = match key {
                INDEX_HEADER => &mut headers.index,
                WRITE_DAY_HEADER => &mut headers.write_day,
                CAPTURE_TIMESTAMP_HEADER => &mut headers.capture_timestamp,
                _ => continue,
            };
            if let Some(value) = value {
                *slot = Some(String::from_utf8_lossy(value).into_owned());
            }
        }
        headers
    }

    pub fn index(&self) -> Option<Index> {
        self.index.as_deref().and_then(Index::parse)
    }

    /// The capture time, when the header is a positive safe integer as `Number()` reads it.
    pub fn captured_at_ms(&self) -> Option<i64> {
        let value = json::js_number(self.capture_timestamp.as_deref()?);
        is_safe_integer(value)
            .then_some(value)
            .filter(|ms| *ms > 0.0)
            .map(|ms| ms as i64)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rejection {
    ParseFailed,
    InvalidRow,
    UnknownIndex,
    InvalidWriteDay,
}

impl Rejection {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ParseFailed => "parse_failed",
            Self::InvalidRow => "invalid_row",
            Self::UnknownIndex => "unknown_index",
            Self::InvalidWriteDay => "invalid_write_day",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct IndexMessage {
    pub index: Index,
    pub write_day: String,
    pub row: Row,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Rejected {
    pub reason: Rejection,
    pub invalid_column: Option<String>,
    pub team_id: Option<f64>,
    pub session_id: Option<String>,
}

impl Rejected {
    fn new(reason: Rejection) -> Self {
        Self {
            reason,
            invalid_column: None,
            team_id: None,
            session_id: None,
        }
    }
}

/// A real UTC day from 0000-01-01 to 9999-12-31, written `YYYY-MM-DD`.
pub fn is_write_day(value: &str) -> bool {
    let bytes = value.as_bytes();
    let shape = bytes.len() == 10
        && bytes.iter().enumerate().all(|(index, byte)| match index {
            4 | 7 => *byte == b'-',
            _ => byte.is_ascii_digit(),
        });
    shape && {
        let field = |range: std::ops::Range<usize>| value[range].parse::<u32>().unwrap_or(0);
        i32::try_from(field(0..4))
            .ok()
            .and_then(|year| NaiveDate::from_ymd_opt(year, field(5..7), field(8..10)))
            .is_some()
    }
}

/// Reads the message, or says why it is skipped, and counts the outcome.
pub fn parse_index_message(
    headers: &Headers,
    value: Option<&[u8]>,
) -> Result<IndexMessage, Rejected> {
    let parsed = read(headers, value);
    match &parsed {
        Ok(message) => metrics::row_parsed(message.index),
        Err(rejected) => {
            if let (Some(column), Some(index)) = (&rejected.invalid_column, headers.index()) {
                metrics::invalid_column(index, column);
            }
            metrics::row_rejected(rejected.reason);
        }
    }
    parsed
}

fn read(headers: &Headers, value: Option<&[u8]>) -> Result<IndexMessage, Rejected> {
    let index = headers
        .index()
        .ok_or_else(|| Rejected::new(Rejection::UnknownIndex))?;
    let write_day = headers
        .write_day
        .as_deref()
        .filter(|day| is_write_day(day))
        .ok_or_else(|| Rejected::new(Rejection::InvalidWriteDay))?;
    let text: Cow<'_, str> = String::from_utf8_lossy(value.unwrap_or_default());
    let parsed = json::parse(&text).map_err(|_| Rejected::new(Rejection::ParseFailed))?;
    match select(&parsed, index.columns(), "") {
        Ok(row) => Ok(IndexMessage {
            index,
            write_day: write_day.to_owned(),
            row,
        }),
        Err(invalid_column) => {
            let (team_id, session_id) = identity(&parsed);
            Err(Rejected {
                reason: Rejection::InvalidRow,
                invalid_column: Some(invalid_column),
                team_id,
                session_id,
            })
        }
    }
}

fn identity(value: &Json<'_>) -> (Option<f64>, Option<String>) {
    let Json::Object(fields) = value else {
        return (None, None);
    };
    let team_id = match Json::field(fields, "team_id") {
        Some(Json::Number(team_id)) => Some(*team_id),
        _ => None,
    };
    let session_id = match Json::field(fields, "session_id") {
        Some(Json::String(session_id))
            if session_id.utf16_len() <= MAX_LOGGED_SESSION_ID_LENGTH =>
        {
            Some(String::from_utf8_lossy(&session_id.to_utf8()).into_owned())
        }
        _ => None,
    };
    (team_id, session_id)
}

fn is_safe_integer(value: f64) -> bool {
    value.fract() == 0.0 && value.abs() <= MAX_SAFE_INTEGER
}

fn encodable(leaf: LeafType, value: &Json<'_>) -> Option<Cell> {
    match (leaf, value) {
        (LeafType::Utf8, Json::String(text)) => Some(Cell::Utf8(text.clone().into_owned())),
        (LeafType::Boolean, Json::Bool(flag)) => Some(Cell::Bool(*flag)),
        (LeafType::Int32, Json::Number(n))
            if n.fract() == 0.0 && (INT32_MIN..=INT32_MAX).contains(n) =>
        {
            Some(Cell::Int32(*n as i32))
        }
        (LeafType::Int64, Json::Number(n)) if is_safe_integer(*n) => Some(Cell::Int64(*n as i64)),
        _ => None,
    }
}

/// A missing key reads as `undefined`, which every check treats as null.
fn is_null(value: Option<&Json<'_>>) -> bool {
    matches!(value, None | Some(Json::Null))
}

fn list(leaf: LeafType, value: Option<&Json<'_>>) -> Option<Vec<Cell>> {
    match value {
        Some(Json::Array(items)) => items.iter().map(|item| encodable(leaf, item)).collect(),
        _ => None,
    }
}

/// The object's fields, or the name to report for a value that is not an object: the row itself, or the repeated
/// column that holds the item.
fn object_fields<'v, 'a>(
    value: &'v Json<'a>,
    prefix: &str,
) -> Result<&'v [(JsString<'a>, Json<'a>)], String> {
    match value {
        Json::Object(fields) => Ok(fields),
        _ if prefix.is_empty() => Err("row".to_owned()),
        _ => Err(prefix[..prefix.len() - 1].to_owned()),
    }
}

fn leaf_cell(column: &LeafColumn, field: Option<&Json<'_>>) -> Option<Cell> {
    if is_null(field) {
        return column.optional.then_some(Cell::Null);
    }
    field.and_then(|value| encodable(column.leaf, value))
}

/// The selected columns of a row, or the first column whose value is missing or does not fit its type. Keys that
/// are not columns are left out.
fn select(value: &Json<'_>, columns: &[Column], prefix: &str) -> Result<Row, String> {
    let fields = object_fields(value, prefix)?;
    let mut cells = Vec::with_capacity(columns.len());
    for column in columns {
        let field = Json::field(fields, column.name());
        let invalid = || format!("{prefix}{}", column.name());
        let cell = match column {
            Column::Repeated { name, fields } => {
                let Some(Json::Array(items)) = field else {
                    return Err(invalid());
                };
                let item_prefix = format!("{prefix}{name}.");
                let rows = items
                    .iter()
                    .map(|item| select_struct(item, fields, &item_prefix))
                    .collect::<Result<Vec<_>, _>>()?;
                Cell::Structs(rows)
            }
            Column::List { leaf, .. } => Cell::List(list(*leaf, field).ok_or_else(invalid)?),
            Column::NullableList { .. } if is_null(field) => Cell::Null,
            Column::NullableList { leaf, .. } => {
                Cell::List(list(*leaf, field).ok_or_else(invalid)?)
            }
            Column::Leaf(column) => leaf_cell(column, field).ok_or_else(invalid)?,
        };
        cells.push(cell);
    }
    Ok(cells.into_boxed_slice())
}

fn select_struct(value: &Json<'_>, columns: &[LeafColumn], prefix: &str) -> Result<Row, String> {
    let fields = object_fields(value, prefix)?;
    columns
        .iter()
        .map(|column| {
            leaf_cell(column, Json::field(fields, column.name))
                .ok_or_else(|| format!("{prefix}{}", column.name))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;
    use crate::testing::block_row;

    fn headers(index: &str, write_day: &str) -> Headers {
        Headers::from_pairs([
            (INDEX_HEADER, Some(index.as_bytes())),
            (WRITE_DAY_HEADER, Some(write_day.as_bytes())),
        ])
    }

    fn rejection(index: &str, write_day: &str, value: &[u8]) -> (Rejection, Option<String>) {
        let rejected = parse_index_message(&headers(index, write_day), Some(value)).unwrap_err();
        (rejected.reason, rejected.invalid_column)
    }

    fn with(field: &str, value: Value) -> Vec<u8> {
        let mut row = block_row("s1");
        match value {
            Value::Null if field == "urls_truncated" => {
                row.as_object_mut().unwrap().remove(field);
            }
            value => row[field] = value,
        }
        serde_json::to_vec(&row).unwrap()
    }

    #[test]
    fn rejects_rows_by_the_first_column_that_does_not_fit() {
        let invalid =
            |field: &str, value: Value| rejection("blocks", "2026-10-15", &with(field, value));
        let cases = [
            ("clicks", json!(2_i64.pow(31)), "clicks"),
            (
                "moments",
                json!([{"kind": "click", "window_id": "w1", "ts_ms": 1_000, "event_index": 2_i64.pow(31)}]),
                "moments.event_index",
            ),
            ("moments", json!([{"kind": "click"}]), "moments.window_id"),
            ("moments", json!([1]), "moments"),
            ("moments_truncated", json!(1), "moments_truncated"),
            ("flush_row_count", json!(2_i64.pow(31)), "flush_row_count"),
            ("url_fingerprints", json!([7]), "url_fingerprints"),
            ("window_ids", json!(["w1", null]), "window_ids"),
            ("window_ids", json!("w1"), "window_ids"),
            (
                "surfacing_click_target_ids",
                json!([1.5]),
                "surfacing_click_target_ids",
            ),
            (
                "surfacing_visited_url_fingerprints",
                json!("x"),
                "surfacing_visited_url_fingerprints",
            ),
            ("urls_truncated", Value::Null, "urls_truncated"),
            ("first_ts_ms", json!(2_i64.pow(53)), "first_ts_ms"),
            ("team_id", json!("7"), "team_id"),
            ("session_id", Value::Null, "session_id"),
        ];
        for (field, value, column) in cases {
            assert_eq!(
                invalid(field, value.clone()),
                (Rejection::InvalidRow, Some(column.to_owned())),
                "{field} = {value}"
            );
        }
        let block = serde_json::to_vec(&block_row("s1")).unwrap();
        assert_eq!(
            rejection("images", "2026-10-15", &block),
            (Rejection::InvalidRow, Some("image_ref".to_owned()))
        );
        for (value, column) in [("[]", "row"), ("null", "row"), ("7", "row")] {
            assert_eq!(
                rejection("blocks", "2026-10-15", value.as_bytes()),
                (Rejection::InvalidRow, Some(column.to_owned()))
            );
        }
    }

    #[test]
    fn rejects_by_header_before_reading_the_value() {
        let block = serde_json::to_vec(&block_row("s1")).unwrap();
        assert_eq!(
            rejection("sessions", "2026-10-15", &block),
            (Rejection::UnknownIndex, None)
        );
        assert_eq!(
            rejection("sessions", "bad", b"{"),
            (Rejection::UnknownIndex, None)
        );
        assert_eq!(
            rejection("blocks", "2026-02-30", &block),
            (Rejection::InvalidWriteDay, None)
        );
        assert_eq!(
            rejection("blocks", "2026-10-15", b"{not json"),
            (Rejection::ParseFailed, None)
        );
        assert_eq!(
            rejection("blocks", "2026-10-15", b""),
            (Rejection::ParseFailed, None)
        );
        let missing = parse_index_message(&headers("blocks", "2026-10-15"), None).unwrap_err();
        assert_eq!(missing.reason, Rejection::ParseFailed);
    }

    #[test]
    fn reads_rows_as_json_parse_does() {
        let accepted = |text: String| {
            parse_index_message(&headers("blocks", "2026-10-15"), Some(text.as_bytes()))
        };
        let base = serde_json::to_string(&block_row("s1")).unwrap();
        let body = &base[1..base.len() - 1];
        // Integral doubles fit integer columns, the last of duplicate keys wins, and unknown keys are left out.
        let row = accepted(format!("{{{body},\"clicks\":5.0,\"team_id\":1e3,\"session_id\":\"x\",\"session_id\":\"s2\",\"extra\":[[[[1]]]]}}"))
            .unwrap()
            .row;
        let cell = |name: &str| {
            let position = Index::Blocks
                .columns()
                .iter()
                .position(|c| c.name() == name)
                .unwrap();
            row[position].clone()
        };
        assert_eq!(cell("clicks"), Cell::Int32(5));
        assert_eq!(cell("team_id"), Cell::Int64(1_000));
        assert!(matches!(cell("session_id"), Cell::Utf8(id) if id.as_bytes() == b"s2"));
        // Invalid UTF-8 reads as U+FFFD, as Buffer#toString decodes it.
        let mut raw = format!("{{{body},\"host\":\"a").into_bytes();
        raw.extend_from_slice(b"\xff\"}");
        let host = parse_index_message(&headers("blocks", "2026-10-15"), Some(&raw))
            .unwrap()
            .row;
        let position = Index::Blocks
            .columns()
            .iter()
            .position(|c| c.name() == "host")
            .unwrap();
        assert!(
            matches!(&host[position], Cell::Utf8(text) if text.as_bytes() == "a\u{fffd}".as_bytes())
        );
    }

    #[test]
    fn reads_headers_as_the_node_sink_did() {
        let headers = Headers::from_pairs([
            (INDEX_HEADER, Some(b"images".as_slice())),
            (INDEX_HEADER, Some(b"blocks".as_slice())),
            ("other", Some(b"x".as_slice())),
            (
                CAPTURE_TIMESTAMP_HEADER,
                Some(b" 1794418509351 ".as_slice()),
            ),
        ]);
        assert_eq!(headers.index(), Some(Index::Blocks));
        assert_eq!(headers.captured_at_ms(), Some(1_794_418_509_351));
        for (value, expected) in [
            ("0", None),
            ("-5", None),
            ("abc", None),
            ("12.5", None),
            ("12.0", Some(12)),
            ("0x10", Some(16)),
            ("9007199254740993", None),
        ] {
            let headers = Headers::from_pairs([(CAPTURE_TIMESTAMP_HEADER, Some(value.as_bytes()))]);
            assert_eq!(headers.captured_at_ms(), expected, "{value}");
        }
        for day in ["2026-10-15", "2024-02-29", "0000-01-01", "9999-12-31"] {
            assert!(is_write_day(day), "{day}");
        }
        for day in [
            "2026-02-29",
            "2026-13-01",
            "2026-00-10",
            "2026-01-00",
            "2026-1-01",
            " 2026-01-01",
            "2026-01-01T",
            "２026-01-01",
        ] {
            assert!(!is_write_day(day), "{day}");
        }
    }

    #[test]
    fn names_the_team_and_session_of_a_rejected_row() {
        let identity = |row: Value| {
            let rejected = parse_index_message(
                &headers("blocks", "2026-01-01"),
                Some(&serde_json::to_vec(&row).unwrap()),
            )
            .unwrap_err();
            (rejected.team_id, rejected.session_id)
        };
        assert_eq!(
            identity(json!({"team_id": 2, "session_id": "session-1"})),
            (Some(2.0), Some("session-1".to_owned()))
        );
        assert_eq!(
            identity(json!({"team_id": 2, "session_id": "s".repeat(71)})),
            (Some(2.0), None)
        );
        assert_eq!(
            identity(json!({"team_id": "2", "session_id": 1})),
            (None, None)
        );
    }
}
