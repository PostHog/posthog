use std::collections::HashMap;

use anyhow::Result;
use base64::{prelude::BASE64_STANDARD, Engine};
use chrono::serde::ts_microseconds;
use chrono::DateTime;
use chrono::TimeDelta;
use chrono::Utc;
use clickhouse::Row;
use opentelemetry_proto::tonic::{
    common::v1::{
        any_value::{self, Value},
        AnyValue, InstrumentationScope,
    },
    logs::v1::LogRecord,
    resource::v1::Resource,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};
use tracing::debug;
use uuid::Uuid;

#[derive(Row, Debug, Serialize, Deserialize)]
pub struct KafkaLogRow {
    pub uuid: String,
    pub trace_id: String,
    pub span_id: String,
    pub trace_flags: u32,
    #[serde(with = "ts_microseconds")]
    pub timestamp: DateTime<Utc>,
    #[serde(with = "ts_microseconds")]
    pub observed_timestamp: DateTime<Utc>,
    pub body: String,
    pub severity_text: String,
    pub severity_number: i32,
    pub service_name: String,
    pub resource_attributes: HashMap<String, String>,
    pub instrumentation_scope: String,
    pub event_name: String,
    pub attributes: HashMap<String, String>,
    pub bytes_uncompressed: Option<i64>,
}

/// Sum byte lengths of the row's string and map content. Fixed-width fields
/// (timestamps, trace_flags, severity_number) are excluded — only variable-length
/// payload is counted. Distinct from the Kafka header `bytes_uncompressed`, which
/// is the raw HTTP body size for the whole batch.
pub fn compute_kafka_log_row_bytes(row: &KafkaLogRow) -> i64 {
    let mut total: usize = 0;
    total = total.saturating_add(row.body.len());

    // by default exclude instrumentation_scope and event_name as they are
    // low cardinality and highly compressible, but add them if they are large
    // to prevent abuse
    if row.instrumentation_scope.len() > 50 {
        total = total.saturating_add(row.instrumentation_scope.len());
    }
    if row.event_name.len() > 50 {
        total = total.saturating_add(row.event_name.len());
    }

    for (k, v) in &row.resource_attributes {
        total = total.saturating_add(k.len()).saturating_add(v.len());
    }
    for (k, v) in &row.attributes {
        total = total.saturating_add(k.len()).saturating_add(v.len());
    }
    i64::try_from(total).unwrap_or(i64::MAX)
}

/// Sum of per-row `bytes_uncompressed` across a batch; rows without the field count as zero.
/// Feeds the `bytes_uncompressed_records` Kafka header — the records-based counterpart to the
/// payload-sized `bytes_uncompressed` header — so the two can be compared before billing
/// switches to the records-based value.
pub fn sum_kafka_log_row_bytes(rows: &[KafkaLogRow]) -> u64 {
    rows.iter()
        .map(|row| row.bytes_uncompressed.unwrap_or(0).max(0) as u64)
        .sum()
}

impl KafkaLogRow {
    /// Set `bytes_uncompressed` from the row's variable-length content. Consuming
    /// builder; the `mut self` is encapsulated and never escapes.
    pub(crate) fn with_computed_bytes(mut self) -> Self {
        self.bytes_uncompressed = Some(compute_kafka_log_row_bytes(&self));
        self
    }

    pub fn new(
        record: LogRecord,
        resource: Option<Resource>,
        scope: Option<InstrumentationScope>,
    ) -> Result<(Self, bool)> {
        // Extract body - convert any AnyValue type to JSON string
        let body = match record.body {
            Some(body) => match body.value {
                Some(any_value::Value::StringValue(s)) => s,
                Some(_) => any_value_to_json(body).to_string(),
                None => "".to_string(),
            },
            None => "".to_string(),
        };

        let mut severity_text = normalize_severity_text(record.severity_text);
        let mut severity_number = record.severity_number;

        if let Some(parsed_severity) = try_extract_severity(&body) {
            severity_text = parsed_severity;
            severity_number = convert_severity_text_to_number(&severity_text);
        }

        // severity_number takes priority if both provided
        if record.severity_number > 0 {
            severity_text = convert_severity_number_to_text(record.severity_number);
        } else {
            severity_number = convert_severity_text_to_number(&severity_text);
        }

        let resource_attributes = extract_resource_attributes(resource);

        let mut attributes: HashMap<String, String> = record
            .attributes
            .into_iter()
            .map(|kv| {
                (
                    kv.key,
                    any_value_to_string(kv.value.unwrap_or(AnyValue {
                        value: Some(Value::StringValue("".to_string())),
                    })),
                )
            })
            .collect();

        let instrumentation_scope = match scope {
            Some(s) => format!("{}@{}", s.name, s.version),
            None => "".to_string(),
        };

        let event_name = record.event_name;
        let service_name = extract_string_from_map(&resource_attributes, "service.name");

        // Trace/span IDs
        let trace_id = extract_trace_id(&record.trace_id);
        let span_id = extract_span_id(&record.span_id);

        // Trace flags
        let trace_flags = record.flags;

        let raw_timestamp = match record.time_unix_nano {
            0 => Utc::now(),
            _ => DateTime::<Utc>::from_timestamp_nanos(record.time_unix_nano.try_into()?),
        };

        let (timestamp, original_timestamp) = override_timestamp(raw_timestamp);
        let was_overridden = original_timestamp.is_some();
        if let Some(original) = original_timestamp {
            attributes.insert("$originalTimestamp".to_string(), original.to_rfc3339());
        }

        let observed_timestamp = Utc::now();

        let log_row = Self {
            uuid: Uuid::now_v7().to_string(),
            trace_id: BASE64_STANDARD.encode(trace_id),
            span_id: BASE64_STANDARD.encode(span_id),
            trace_flags,
            timestamp,
            observed_timestamp,
            body,
            severity_text,
            severity_number,
            resource_attributes,
            instrumentation_scope,
            event_name,
            service_name,
            attributes,
            bytes_uncompressed: None,
        }
        .with_computed_bytes();
        debug!("log: {:?}", log_row);

        Ok((log_row, was_overridden))
    }
}

const TIMESTAMP_OVERRIDE_HOURS: i64 = 24;

/// Override timestamps outside of 24 hours from now. Returns the final timestamp
/// and the original if it was overridden.
pub fn override_timestamp(timestamp: DateTime<Utc>) -> (DateTime<Utc>, Option<DateTime<Utc>>) {
    let now = Utc::now();
    let max_delta = TimeDelta::hours(TIMESTAMP_OVERRIDE_HOURS);

    if timestamp < now - max_delta || timestamp > now + max_delta {
        (now, Some(timestamp))
    } else {
        (timestamp, None)
    }
}

// extract a JSON value as a string. If it's a string, strip the surrounding "quotes"
fn extract_string_from_map(attributes: &HashMap<String, String>, key: &str) -> String {
    if let Some(value) = attributes.get(key) {
        if let Ok(JsonValue::String(value)) = serde_json::from_str::<JsonValue>(value) {
            value.to_string()
        } else {
            value.to_string()
        }
    } else {
        "".to_string()
    }
}

pub fn extract_trace_id(input: &[u8]) -> [u8; 16] {
    if input.len() == 16 {
        let mut bytes = [0; 16];
        bytes.copy_from_slice(input);
        bytes
    } else {
        [0; 16]
    }
}

pub fn extract_span_id(input: &[u8]) -> [u8; 8] {
    if input.len() == 8 {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(input);
        bytes
    } else {
        [0; 8]
    }
}

fn normalize_severity_text(severity_text: String) -> String {
    match severity_text.to_lowercase().as_str() {
        "critical" | "fatal" | "crit" | "alert" | "emerg" => "fatal".to_string(),
        "error" | "err" | "eror" => "error".to_string(),
        "warn" | "warning" => "warn".to_string(),
        "info" | "information" | "informational" => "info".to_string(),
        "debug" | "dbug" => "debug".to_string(),
        "trace" => "trace".to_string(),
        // don't allow arbitrary values in severity text. normalize unknown to info
        _ => "info".to_string(),
    }
}

fn convert_severity_text_to_number(severity_text: &str) -> i32 {
    match severity_text {
        "trace" => 1,
        "debug" => 5,
        "info" => 9,
        "warn" => 13,
        "error" => 17,
        "fatal" => 21,
        _ => 0,
    }
}

fn convert_severity_number_to_text(severity_number: i32) -> String {
    match severity_number {
        1 => "trace".to_string(),
        2 => "trace".to_string(),
        3 => "trace".to_string(),
        4 => "trace".to_string(),
        5 => "debug".to_string(),
        6 => "debug".to_string(),
        7 => "debug".to_string(),
        8 => "debug".to_string(),
        9 => "info".to_string(),
        10 => "info".to_string(),
        11 => "info".to_string(),
        12 => "info".to_string(),
        13 => "warn".to_string(),
        14 => "warn".to_string(),
        15 => "warn".to_string(),
        16 => "warn".to_string(),
        17 => "error".to_string(),
        18 => "error".to_string(),
        19 => "error".to_string(),
        20 => "error".to_string(),
        21 => "fatal".to_string(),
        22 => "fatal".to_string(),
        23 => "fatal".to_string(),
        24 => "fatal".to_string(),
        _ => "unknown".to_string(),
    }
}

pub fn extract_resource_attributes(resource: Option<Resource>) -> HashMap<String, String> {
    let Some(resource) = resource else {
        return HashMap::new();
    };

    resource
        .attributes
        .into_iter()
        .map(|kv| {
            (
                kv.key,
                any_value_to_string(kv.value.unwrap_or(AnyValue {
                    value: Some(Value::StringValue("".to_string())),
                })),
            )
        })
        .collect()
}

// TODO - pull this from PG
const SEVERITY_KEYS: [&str; 4] = ["level", "severity", "log.level", "config.log_level"];

fn try_extract_severity(body: &str) -> Option<String> {
    let Ok(val) = serde_json::from_str::<JsonValue>(body) else {
        return None;
    };

    for key in SEVERITY_KEYS {
        if let Some(severity) = val.get(key) {
            let Some(found) = severity.as_str() else {
                continue;
            };
            let found = found.to_lowercase();
            if convert_severity_text_to_number(&found) != 0 {
                return Some(found);
            }
        }
    }
    None
}

pub fn any_value_to_json(value: AnyValue) -> JsonValue {
    match value.value {
        Some(value_enum) => match value_enum {
            any_value::Value::StringValue(s) => json!(s),
            any_value::Value::BoolValue(b) => json!(b),
            any_value::Value::IntValue(i) => json!(i),
            any_value::Value::DoubleValue(d) => json!(d),
            any_value::Value::ArrayValue(arr) => {
                json!(arr
                    .values
                    .into_iter()
                    .map(any_value_to_json)
                    .collect::<Vec<_>>())
            }
            any_value::Value::KvlistValue(kvlist) => {
                let mut map = HashMap::new();
                for kv in kvlist.values.into_iter() {
                    if let Some(v) = kv.value {
                        map.insert(kv.key.clone(), any_value_to_json(v));
                    }
                }
                json!(map)
            }
            any_value::Value::BytesValue(b) => {
                json!(BASE64_STANDARD.encode(b))
            }
        },
        None => JsonValue::Null,
    }
}

pub fn any_value_to_string(value: AnyValue) -> String {
    any_value_to_json(value).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use apache_avro::{Codec, Reader, Schema, Writer};

    use crate::avro_schema::AVRO_SCHEMA;

    fn sample_row() -> KafkaLogRow {
        let mut resource_attributes = HashMap::new();
        resource_attributes.insert("host.name".to_string(), "localhost".to_string());
        let mut attributes = HashMap::new();
        attributes.insert("k".to_string(), "v".to_string());
        KafkaLogRow {
            uuid: "uuid-1234".to_string(),
            trace_id: "tid".to_string(),
            span_id: "sid".to_string(),
            trace_flags: 0,
            timestamp: Utc::now(),
            observed_timestamp: Utc::now(),
            body: "hello".to_string(),
            severity_text: "info".to_string(),
            severity_number: 9,
            service_name: "svc".to_string(),
            resource_attributes,
            instrumentation_scope: "scope@1".to_string(),
            event_name: "evt".to_string(),
            attributes,
            bytes_uncompressed: None,
        }
    }

    #[test]
    fn test_compute_kafka_log_row_bytes_sums_string_and_map_lengths() {
        let row = sample_row();
        // string fields: body(5)
        // maps: resource_attributes "host.name"(9)+"localhost"(9)=18; attributes "k"(1)+"v"(1)=2
        // total = 5 + 18 + 2 = 25
        assert_eq!(compute_kafka_log_row_bytes(&row), 25);
    }

    fn sample_row_bytes() -> u64 {
        sample_row()
            .with_computed_bytes()
            .bytes_uncompressed
            .unwrap() as u64
    }

    #[test]
    fn test_sum_kafka_log_row_bytes_empty_slice_is_zero() {
        assert_eq!(sum_kafka_log_row_bytes(&[]), 0);
    }

    #[test]
    fn test_sum_kafka_log_row_bytes_treats_missing_field_as_zero() {
        let with_bytes = sample_row().with_computed_bytes();
        let without_bytes = sample_row(); // bytes_uncompressed: None
        assert_eq!(
            sum_kafka_log_row_bytes(&[with_bytes, without_bytes]),
            sample_row_bytes()
        );
    }

    #[test]
    fn test_sum_kafka_log_row_bytes_sums_all_rows() {
        let rows = [
            sample_row().with_computed_bytes(),
            sample_row().with_computed_bytes(),
        ];
        assert_eq!(sum_kafka_log_row_bytes(&rows), sample_row_bytes() * 2);
    }

    #[test]
    fn test_compute_kafka_log_row_bytes_excludes_fixed_width_fields() {
        // Two rows differing only in fixed-width numeric/timestamp fields should compute
        // identical bytes_uncompressed.
        let mut a = sample_row();
        a.trace_flags = 0;
        a.severity_number = 1;
        let mut b = sample_row();
        b.trace_flags = u32::MAX;
        b.severity_number = i32::MIN;
        b.timestamp = a.timestamp + TimeDelta::days(1);
        assert_eq!(
            compute_kafka_log_row_bytes(&a),
            compute_kafka_log_row_bytes(&b),
        );
    }

    #[test]
    fn test_bytes_uncompressed_serialises_into_avro_payload() {
        // We don't deserialise back into KafkaLogRow because apache_avro's `from_value`
        // can't resolve `["null", T]` unions into non-Option struct fields (the existing
        // pattern used for body/attributes/etc.). Instead, decode to the raw Avro Value
        // and assert the new field is present with the expected long.
        use apache_avro::types::Value;

        let mut row = sample_row();
        row.bytes_uncompressed = Some(compute_kafka_log_row_bytes(&row));
        let expected = row.bytes_uncompressed.unwrap();

        let schema = Schema::parse_str(AVRO_SCHEMA).expect("schema parses");
        let mut writer = Writer::with_codec(&schema, Vec::new(), Codec::Null);
        writer.append_ser(&row).expect("append_ser ok");
        let payload = writer.into_inner().expect("flush ok");

        let reader = Reader::new(payload.as_slice()).expect("reader ok");
        let mut found_long: Option<i64> = None;
        for value in reader {
            let value = value.expect("decode ok");
            if let Value::Record(fields) = value {
                for (name, field_value) in fields {
                    if name == "bytes_uncompressed" {
                        if let Value::Union(_, inner) = field_value {
                            if let Value::Long(v) = *inner {
                                found_long = Some(v);
                            }
                        }
                    }
                }
            }
        }
        assert_eq!(found_long, Some(expected));
    }

    #[test]
    fn test_new_populates_bytes_uncompressed() {
        let log_record = LogRecord::default();
        let (row, _) = KafkaLogRow::new(log_record, None, None).expect("ok");
        assert!(row.bytes_uncompressed.is_some());
        assert_eq!(
            row.bytes_uncompressed.unwrap(),
            compute_kafka_log_row_bytes(&row),
        );
    }

    #[test]
    fn test_override_timestamp_within_range_is_unchanged() {
        let now = Utc::now();
        let one_hour_ago = now - TimeDelta::hours(1);
        let (final_ts, original) = override_timestamp(one_hour_ago);
        assert_eq!(final_ts, one_hour_ago);
        assert!(original.is_none());
    }

    #[test]
    fn test_override_timestamp_far_past_is_overridden() {
        let now = Utc::now();
        let two_days_ago = now - TimeDelta::hours(48);
        let (final_ts, original) = override_timestamp(two_days_ago);
        assert!((final_ts - now).num_seconds().abs() < 2);
        assert_eq!(original.unwrap(), two_days_ago);
    }

    #[test]
    fn test_override_timestamp_far_future_is_overridden() {
        let now = Utc::now();
        let two_days_ahead = now + TimeDelta::hours(48);
        let (final_ts, original) = override_timestamp(two_days_ahead);
        assert!((final_ts - now).num_seconds().abs() < 2);
        assert_eq!(original.unwrap(), two_days_ahead);
    }

    #[test]
    fn test_override_timestamp_at_boundary_is_not_overridden() {
        let now = Utc::now();
        let just_within = now - TimeDelta::hours(22);
        let (final_ts, original) = override_timestamp(just_within);
        assert_eq!(final_ts, just_within);
        assert!(original.is_none());
    }

    #[test]
    fn test_override_timestamp_just_past_boundary_is_overridden() {
        let now = Utc::now();
        let just_outside = now - TimeDelta::hours(24) - TimeDelta::seconds(1);
        let (final_ts, original) = override_timestamp(just_outside);
        assert!((final_ts - now).num_seconds().abs() < 2);
        assert_eq!(original.unwrap(), just_outside);
    }
}
