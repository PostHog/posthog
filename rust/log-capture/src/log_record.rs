use std::collections::HashMap;

use anyhow::Result;
use base64::{prelude::BASE64_STANDARD, Engine};
use clickhouse::Row;
use opentelemetry_proto::tonic::{
    common::v1::{any_value, AnyValue, InstrumentationScope, KeyValue},
    logs::v1::LogRecord,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};

#[derive(Row, Debug, Serialize, Deserialize)]
pub struct LogRow {
    team_id: i32,
    trace_id: [u8; 16],
    span_id: [u8; 8],
    trace_flags: u8,
    timestamp: u64,
    body: String,
    _attributes: String,
    severity_text: String,
    severity_number: i32,
    _resource: String,
    instrumentation_scope: String,
    event_name: String,
}

impl LogRow {
    pub fn new(
        team_id: i32,
        record: LogRecord,
        resource_str: String,
        scope: Option<InstrumentationScope>,
    ) -> Result<Self> {
        // Extract body
        let body = match record.body {
            Some(body) => match body.value {
                Some(value) => match value {
                    opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue(s) => {
                        s.clone()
                    }
                    _ => format!("{:?}", value),
                },
                None => "".to_string(),
            },
            None => "".to_string(),
        };

        let mut severity_text = normalize_severity_text(record.severity_text);
        let mut severity_number = record.severity_number;

        // severity_number takes priority if both provided
        if record.severity_number > 0 {
            severity_text = convert_severity_number_to_text(record.severity_number);
        } else {
            severity_number = convert_severity_text_to_number(&severity_text);
        }

        // Attributes as JSON
        let attributes = attributes_to_json(record.attributes);

        // Get scope name or empty string
        let instrumentation_scope = match scope {
            Some(s) => format!("{}@{}", s.name, s.version),
            None => "".to_string(),
        };

        // Extract event name if present
        let event_name = extract_event_name(&attributes);

        // Trace/span IDs
        let trace_id = extract_trace_id(&record.trace_id);
        let span_id = extract_span_id(&record.span_id);

        // Trace flags
        let trace_flags = record.flags as u8;
        let _attributes = json!(attributes).to_string();

        Ok(Self {
            // uuid: Uuid::now_v7(),
            team_id,
            trace_id,
            span_id,
            trace_flags,
            timestamp: record.time_unix_nano,
            body,
            _attributes,
            severity_text,
            severity_number,
            _resource: resource_str,
            instrumentation_scope,
            event_name,
        })
    }
}

fn extract_event_name(attributes: &HashMap<String, JsonValue>) -> String {
    for (key, val) in attributes.iter() {
        if key == "event.name" {
            if let JsonValue::String(s) = val {
                return s.clone();
            }
        }
    }
    "".to_string()
}

fn extract_trace_id(input: &[u8]) -> [u8; 16] {
    if input.len() == 16 {
        let mut bytes = [0; 16];
        bytes.copy_from_slice(input);
        bytes
    } else {
        [0; 16]
    }
}

fn extract_span_id(input: &[u8]) -> [u8; 8] {
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
        "" => "info".to_string(),
        _ => severity_text,
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

fn attributes_to_json(attributes: Vec<KeyValue>) -> HashMap<String, JsonValue> {
    let mut map = HashMap::new();

    for attr in attributes.into_iter() {
        if let Some(value) = attr.value {
            let json_value = any_value_to_json(value);
            map.insert(attr.key, json_value);
        }
    }

    map
}

fn any_value_to_json(value: AnyValue) -> JsonValue {
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
