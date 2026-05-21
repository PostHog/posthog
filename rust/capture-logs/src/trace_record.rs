use std::collections::HashMap;

use anyhow::Result;
use base64::{prelude::BASE64_STANDARD, Engine};
use chrono::serde::ts_microseconds;
use chrono::DateTime;
use chrono::Utc;
use clickhouse::Row;
use opentelemetry_proto::tonic::{
    common::v1::{AnyValue, InstrumentationScope},
    resource::v1::Resource,
    trace::v1::Span,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use tracing::debug;
use uuid::Uuid;

use crate::log_record::{
    any_value_to_string, extract_resource_attributes, extract_span_id, extract_trace_id,
    override_timestamp,
};

#[derive(Row, Debug, Serialize, Deserialize)]
pub struct KafkaTraceRow {
    pub uuid: String,
    pub trace_id: String,
    pub span_id: String,
    pub parent_span_id: String,
    pub trace_state: String,
    pub name: String,
    pub kind: i32,
    pub flags: i32,
    #[serde(with = "ts_microseconds")]
    pub timestamp: DateTime<Utc>,
    #[serde(with = "ts_microseconds")]
    pub end_time: DateTime<Utc>,
    #[serde(with = "ts_microseconds")]
    pub observed_timestamp: DateTime<Utc>,
    pub service_name: String,
    pub resource_attributes: HashMap<String, String>,
    pub instrumentation_scope: String,
    pub attributes: HashMap<String, String>,
    pub dropped_attributes_count: i32,
    pub events: Vec<String>,
    pub dropped_events_count: i32,
    pub links: Vec<String>,
    pub dropped_links_count: i32,
    pub status_code: i32,
    pub status_message: String,
    pub bytes_uncompressed: Option<i64>,
}

/// Sum byte lengths of the row's string, map, and array content. Fixed-width
/// fields (timestamps, kind, flags, status_code, dropped_*_count) are excluded —
/// only variable-length payload is counted. Distinct from the Kafka header
/// `bytes_uncompressed`, which is the raw HTTP body size for the whole batch.
pub fn compute_kafka_trace_row_bytes(row: &KafkaTraceRow) -> i64 {
    let mut total: usize = 0;
    total = total.saturating_add(row.uuid.len());
    total = total.saturating_add(row.trace_id.len());
    total = total.saturating_add(row.span_id.len());
    total = total.saturating_add(row.parent_span_id.len());
    total = total.saturating_add(row.trace_state.len());
    total = total.saturating_add(row.name.len());
    total = total.saturating_add(row.service_name.len());
    total = total.saturating_add(row.instrumentation_scope.len());
    total = total.saturating_add(row.status_message.len());
    for (k, v) in &row.resource_attributes {
        total = total.saturating_add(k.len()).saturating_add(v.len());
    }
    for (k, v) in &row.attributes {
        total = total.saturating_add(k.len()).saturating_add(v.len());
    }
    for event in &row.events {
        total = total.saturating_add(event.len());
    }
    for link in &row.links {
        total = total.saturating_add(link.len());
    }
    i64::try_from(total).unwrap_or(i64::MAX)
}

impl KafkaTraceRow {
    /// Set `bytes_uncompressed` from the row's variable-length content. Consuming
    /// builder; the `mut self` is encapsulated and never escapes.
    fn with_computed_bytes(mut self) -> Self {
        self.bytes_uncompressed = Some(compute_kafka_trace_row_bytes(&self));
        self
    }

    pub fn new(
        span: Span,
        resource: Option<Resource>,
        scope: Option<InstrumentationScope>,
    ) -> Result<(Self, bool)> {
        let trace_id = BASE64_STANDARD.encode(extract_trace_id(&span.trace_id));
        let span_id = BASE64_STANDARD.encode(extract_span_id(&span.span_id));
        let parent_span_id = BASE64_STANDARD.encode(extract_span_id(&span.parent_span_id));

        let resource_attributes = extract_resource_attributes(resource);
        let service_name = extract_string_from_resource(&resource_attributes, "service.name");

        let mut attributes: HashMap<String, String> = span
            .attributes
            .into_iter()
            .map(|kv| {
                (
                    kv.key,
                    any_value_to_string(kv.value.unwrap_or(AnyValue {
                        value: Some(
                            opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue(
                                "".to_string(),
                            ),
                        ),
                    })),
                )
            })
            .collect();

        let instrumentation_scope = match scope {
            Some(s) => format!("{}@{}", s.name, s.version),
            None => "".to_string(),
        };

        let raw_timestamp = match span.start_time_unix_nano {
            0 => Utc::now(),
            _ => DateTime::<Utc>::from_timestamp_nanos(span.start_time_unix_nano.try_into()?),
        };
        let (timestamp, original_timestamp) = override_timestamp(raw_timestamp);
        let was_overridden = original_timestamp.is_some();
        if let Some(original) = original_timestamp {
            attributes.insert("$originalTimestamp".to_string(), original.to_rfc3339());
        }

        let end_time = match span.end_time_unix_nano {
            0 => timestamp,
            _ => DateTime::<Utc>::from_timestamp_nanos(span.end_time_unix_nano.try_into()?),
        };

        let events: Vec<String> = span
            .events
            .into_iter()
            .map(|event| {
                let attrs: HashMap<String, String> = event
                    .attributes
                    .into_iter()
                    .map(|kv| {
                        (
                            kv.key,
                            any_value_to_string(kv.value.unwrap_or(AnyValue {
                                value: Some(opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue("".to_string())),
                            })),
                        )
                    })
                    .collect();
                json!({
                    "time_unix_nano": event.time_unix_nano,
                    "name": event.name,
                    "attributes": attrs,
                    "dropped_attributes_count": event.dropped_attributes_count,
                })
                .to_string()
            })
            .collect();

        let links: Vec<String> = span
            .links
            .into_iter()
            .map(|link| {
                let attrs: HashMap<String, String> = link
                    .attributes
                    .into_iter()
                    .map(|kv| {
                        (
                            kv.key,
                            any_value_to_string(kv.value.unwrap_or(AnyValue {
                                value: Some(opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue("".to_string())),
                            })),
                        )
                    })
                    .collect();
                json!({
                    "trace_id": BASE64_STANDARD.encode(extract_trace_id(&link.trace_id)),
                    "span_id": BASE64_STANDARD.encode(extract_span_id(&link.span_id)),
                    "trace_state": link.trace_state,
                    "attributes": attrs,
                    "dropped_attributes_count": link.dropped_attributes_count,
                    "flags": link.flags,
                })
                .to_string()
            })
            .collect();

        let status_code = span.status.as_ref().map(|s| s.code).unwrap_or(0);
        let status_message = span
            .status
            .as_ref()
            .map(|s| s.message.clone())
            .unwrap_or_default();

        let row = Self {
            uuid: Uuid::now_v7().to_string(),
            trace_id,
            span_id,
            parent_span_id,
            trace_state: span.trace_state,
            name: span.name,
            kind: span.kind,
            flags: span.flags as i32,
            timestamp,
            end_time,
            observed_timestamp: Utc::now(),
            service_name,
            resource_attributes,
            instrumentation_scope,
            attributes,
            dropped_attributes_count: span.dropped_attributes_count as i32,
            events,
            dropped_events_count: span.dropped_events_count as i32,
            links,
            dropped_links_count: span.dropped_links_count as i32,
            status_code,
            status_message,
            bytes_uncompressed: None,
        }
        .with_computed_bytes();
        debug!("trace span: {:?}", row);

        Ok((row, was_overridden))
    }
}

fn extract_string_from_resource(attributes: &HashMap<String, String>, key: &str) -> String {
    if let Some(value) = attributes.get(key) {
        if let Ok(serde_json::Value::String(value)) =
            serde_json::from_str::<serde_json::Value>(value)
        {
            value.to_string()
        } else {
            value.to_string()
        }
    } else {
        "".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use apache_avro::{Codec, Reader, Schema, Writer};
    use chrono::{TimeDelta, Utc};
    use opentelemetry_proto::tonic::{
        common::v1::{any_value, AnyValue, KeyValue},
        trace::v1::{span::Event, span::Link, Span, Status},
    };

    use crate::traces_avro_schema::TRACES_AVRO_SCHEMA;

    fn make_span() -> Span {
        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        Span {
            trace_id: vec![1u8; 16],
            span_id: vec![2u8; 8],
            parent_span_id: vec![3u8; 8],
            trace_state: "vendor=foo".to_string(),
            name: "test.operation".to_string(),
            kind: 2, // SERVER
            flags: 1,
            start_time_unix_nano: now_nanos - 1_000_000_000,
            end_time_unix_nano: now_nanos,
            attributes: vec![KeyValue {
                key: "http.method".to_string(),
                value: Some(AnyValue {
                    value: Some(any_value::Value::StringValue("GET".to_string())),
                }),
            }],
            dropped_attributes_count: 0,
            events: vec![],
            dropped_events_count: 0,
            links: vec![],
            dropped_links_count: 0,
            status: Some(Status {
                message: "".to_string(),
                code: 1, // OK
            }),
        }
    }

    #[test]
    fn test_compute_kafka_trace_row_bytes_sums_string_map_and_array_lengths() {
        let mut resource_attributes = HashMap::new();
        resource_attributes.insert("host.name".to_string(), "localhost".to_string());
        let mut attributes = HashMap::new();
        attributes.insert("a".to_string(), "b".to_string());
        let row = KafkaTraceRow {
            uuid: "uuid-1".to_string(),
            trace_id: "tid".to_string(),
            span_id: "sid".to_string(),
            parent_span_id: "psid".to_string(),
            trace_state: "ts".to_string(),
            name: "op".to_string(),
            kind: 0,
            flags: 0,
            timestamp: Utc::now(),
            end_time: Utc::now(),
            observed_timestamp: Utc::now(),
            service_name: "svc".to_string(),
            resource_attributes,
            instrumentation_scope: "scope".to_string(),
            attributes,
            dropped_attributes_count: 0,
            events: vec!["{}".to_string()],
            dropped_events_count: 0,
            links: vec!["{}".to_string()],
            dropped_links_count: 0,
            status_code: 0,
            status_message: "ok".to_string(),
            bytes_uncompressed: None,
        };
        // strings: uuid(6) + tid(3) + sid(3) + psid(4) + ts(2) + op(2) + svc(3) + scope(5) + ok(2) = 30
        // resource_attributes: host.name(9)+localhost(9)=18; attributes a(1)+b(1)=2
        // events 1 entry of "{}"(2); links 1 entry of "{}"(2) = 4
        // total = 30 + 18 + 2 + 4 = 54
        assert_eq!(compute_kafka_trace_row_bytes(&row), 54);
    }

    #[test]
    fn test_bytes_uncompressed_serialises_into_avro_payload() {
        // Decode to raw Avro Value rather than struct: apache_avro's `from_value` can't
        // resolve `["null", T]` unions into the existing non-Option fields on KafkaTraceRow.
        use apache_avro::types::Value;

        let (row, _) = KafkaTraceRow::new(make_span(), None, None).expect("ok");
        let expected = row.bytes_uncompressed.expect("populated");

        let schema = Schema::parse_str(TRACES_AVRO_SCHEMA).expect("schema parses");
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
        let (row, _) = KafkaTraceRow::new(make_span(), None, None).expect("ok");
        assert!(row.bytes_uncompressed.is_some());
        assert_eq!(
            row.bytes_uncompressed.unwrap(),
            compute_kafka_trace_row_bytes(&row),
        );
    }

    #[test]
    fn test_basic_span_conversion() {
        let span = make_span();
        let (row, was_overridden) = KafkaTraceRow::new(span, None, None).unwrap();

        assert!(!was_overridden);
        assert!(!row.uuid.is_empty());
        assert_eq!(row.trace_id, BASE64_STANDARD.encode([1u8; 16]));
        assert_eq!(row.span_id, BASE64_STANDARD.encode([2u8; 8]));
        assert_eq!(row.parent_span_id, BASE64_STANDARD.encode([3u8; 8]));
        assert_eq!(row.trace_state, "vendor=foo");
        assert_eq!(row.name, "test.operation");
        assert_eq!(row.kind, 2);
        assert_eq!(row.flags, 1);
        assert_eq!(row.status_code, 1);
        assert_eq!(
            row.attributes.get("http.method").map(|s| s.as_str()),
            Some("\"GET\"")
        );
    }

    #[test]
    fn test_empty_span_produces_valid_row() {
        let span = Span::default();
        let (row, was_overridden) = KafkaTraceRow::new(span, None, None).unwrap();

        // Zero timestamp defaults to now, which is within range — no override
        assert!(!was_overridden);
        assert!(!row.uuid.is_empty());
        assert_eq!(row.name, "");
        assert_eq!(row.kind, 0);
        assert_eq!(row.status_code, 0);
        assert!(row.events.is_empty());
        assert!(row.links.is_empty());
    }

    #[test]
    fn test_timestamp_override_far_past() {
        let far_past_nanos = (Utc::now() - TimeDelta::hours(48))
            .timestamp_nanos_opt()
            .unwrap() as u64;
        let span = Span {
            start_time_unix_nano: far_past_nanos,
            end_time_unix_nano: far_past_nanos + 1_000_000,
            ..Default::default()
        };
        let (row, was_overridden) = KafkaTraceRow::new(span, None, None).unwrap();

        assert!(was_overridden);
        assert!(row.attributes.contains_key("$originalTimestamp"));
    }

    #[test]
    fn test_timestamp_within_range_not_overridden() {
        let recent_nanos = (Utc::now() - TimeDelta::hours(1))
            .timestamp_nanos_opt()
            .unwrap() as u64;
        let span = Span {
            start_time_unix_nano: recent_nanos,
            end_time_unix_nano: recent_nanos + 1_000_000,
            ..Default::default()
        };
        let (row, was_overridden) = KafkaTraceRow::new(span, None, None).unwrap();

        assert!(!was_overridden);
        assert!(!row.attributes.contains_key("$originalTimestamp"));
    }

    #[test]
    fn test_events_serialized_as_array_of_json_strings() {
        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            events: vec![
                Event {
                    time_unix_nano: now_nanos - 500_000,
                    name: "db.query".to_string(),
                    attributes: vec![KeyValue {
                        key: "db.statement".to_string(),
                        value: Some(AnyValue {
                            value: Some(any_value::Value::StringValue("SELECT 1".to_string())),
                        }),
                    }],
                    dropped_attributes_count: 0,
                },
                Event {
                    time_unix_nano: now_nanos - 100_000,
                    name: "exception".to_string(),
                    attributes: vec![],
                    dropped_attributes_count: 0,
                },
            ],
            ..Default::default()
        };
        let (row, _) = KafkaTraceRow::new(span, None, None).unwrap();

        assert_eq!(row.events.len(), 2);
        // Each element must be valid JSON
        let e0: serde_json::Value = serde_json::from_str(&row.events[0]).unwrap();
        assert_eq!(e0["name"], "db.query");
        let e1: serde_json::Value = serde_json::from_str(&row.events[1]).unwrap();
        assert_eq!(e1["name"], "exception");
    }

    #[test]
    fn test_links_serialized_as_array_of_json_strings() {
        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            links: vec![Link {
                trace_id: vec![9u8; 16],
                span_id: vec![8u8; 8],
                trace_state: "linked=true".to_string(),
                attributes: vec![],
                dropped_attributes_count: 0,
                flags: 0,
            }],
            ..Default::default()
        };
        let (row, _) = KafkaTraceRow::new(span, None, None).unwrap();

        assert_eq!(row.links.len(), 1);
        let l0: serde_json::Value = serde_json::from_str(&row.links[0]).unwrap();
        assert_eq!(l0["trace_id"], BASE64_STANDARD.encode([9u8; 16]));
        assert_eq!(l0["span_id"], BASE64_STANDARD.encode([8u8; 8]));
        assert_eq!(l0["trace_state"], "linked=true");
    }

    #[test]
    fn test_status_code_extraction() {
        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            status: Some(Status {
                message: "internal error".to_string(),
                code: 2, // ERROR
            }),
            ..Default::default()
        };
        let (row, _) = KafkaTraceRow::new(span, None, None).unwrap();
        assert_eq!(row.status_code, 2);
    }

    #[test]
    fn test_parent_span_id_encoding() {
        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let parent = vec![0xAB, 0xCD, 0xEF, 0x01, 0x23, 0x45, 0x67, 0x89];
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            parent_span_id: parent.clone(),
            ..Default::default()
        };
        let (row, _) = KafkaTraceRow::new(span, None, None).unwrap();
        assert_eq!(row.parent_span_id, BASE64_STANDARD.encode(&parent));
    }

    #[test]
    fn test_resource_service_name_extracted() {
        use opentelemetry_proto::tonic::{
            common::v1::{any_value, AnyValue, KeyValue},
            resource::v1::Resource,
        };

        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            ..Default::default()
        };
        let resource = Resource {
            attributes: vec![KeyValue {
                key: "service.name".to_string(),
                value: Some(AnyValue {
                    value: Some(any_value::Value::StringValue("my-service".to_string())),
                }),
            }],
            dropped_attributes_count: 0,
        };
        let (row, _) = KafkaTraceRow::new(span, Some(resource), None).unwrap();
        assert_eq!(row.service_name, "my-service");
    }

    #[test]
    fn test_instrumentation_scope_name_version() {
        use opentelemetry_proto::tonic::common::v1::InstrumentationScope;

        let now_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let span = Span {
            start_time_unix_nano: now_nanos - 1_000_000,
            end_time_unix_nano: now_nanos,
            ..Default::default()
        };
        let scope = InstrumentationScope {
            name: "opentelemetry-rust".to_string(),
            version: "0.22.0".to_string(),
            ..Default::default()
        };
        let (row, _) = KafkaTraceRow::new(span, None, Some(scope)).unwrap();
        assert_eq!(row.instrumentation_scope, "opentelemetry-rust@0.22.0");
    }
}
