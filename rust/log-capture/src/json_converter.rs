use serde::{Deserialize, Serialize};
use serde_json::{Value as JsonValue};
use std::collections::HashMap;
use hex;

use crate::log_record::LogRow;
use opentelemetry_proto::tonic::{
    common::v1::{
        any_value::Value,
        AnyValue, InstrumentationScope, KeyValue,
    },
    logs::v1::LogRecord,
    resource::v1::Resource,
};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct JsonLogEntry {
    pub attributes: HashMap<String, JsonValue>,
    pub message: String,
    pub resources: HashMap<String, String>,
    pub severity_number: Option<i32>,
    pub severity_text: Option<String>,
    pub span_id: Option<String>,
    pub timestamp: u64,
    pub trace_flags: Option<u32>,
    pub trace_id: Option<String>,
}

pub fn convert_custom_log_to_log_row(
    team_id: i32,
    log_entry: JsonLogEntry,
) -> Result<LogRow, Box<dyn std::error::Error>> {
    // Convert trace_id and span_id from hex strings to bytes
    let trace_id = log_entry.trace_id
        .as_ref()
        .and_then(|s| parse_hex_to_bytes_16(s))
        .unwrap_or([0; 16])
        .to_vec();

    let span_id = log_entry.span_id
        .as_ref()
        .and_then(|s| parse_hex_to_bytes_8(s))
        .unwrap_or([0; 8])
        .to_vec();

    // Convert attributes to OTLP KeyValue format
    let mut otlp_attributes = Vec::new();
    for (key, value) in log_entry.attributes {
        let value_str = match value {
            JsonValue::String(s) => s,
            JsonValue::Number(n) => n.to_string(),
            JsonValue::Bool(b) => b.to_string(),
            _ => value.to_string(),
        };

        otlp_attributes.push(KeyValue {
            key,
            value: Some(AnyValue {
                value: Some(Value::StringValue(value_str)),
            }),
        });
    }

    // Convert resources to OTLP Resource format
    let mut resource_attributes = Vec::new();
    for (key, value) in log_entry.resources {
        resource_attributes.push(KeyValue {
            key,
            value: Some(AnyValue {
                value: Some(Value::StringValue(value)),
            }),
        });
    }

    let resource = if !resource_attributes.is_empty() {
        Some(Resource {
            attributes: resource_attributes,
            dropped_attributes_count: 0,
        })
    } else {
        None
    };

    // Create instrumentation scope
    let scope = Some(InstrumentationScope {
        name: "json-logs".to_string(),
        version: "1.0".to_string(),
        attributes: Vec::new(),
        dropped_attributes_count: 0,
    });

    // Create the log body as an AnyValue (just the message, not JSON)
    let log_body = Some(AnyValue {
        value: Some(Value::StringValue(log_entry.message.clone())),
    });

    // Create OTLP LogRecord
    let otlp_log_record = LogRecord {
        time_unix_nano: log_entry.timestamp,
        observed_time_unix_nano: log_entry.timestamp,
        severity_number: log_entry.severity_number.unwrap_or(0),
        severity_text: log_entry.severity_text.unwrap_or_default().to_lowercase(),
        body: log_body,
        attributes: otlp_attributes,
        dropped_attributes_count: 0,
        flags: log_entry.trace_flags.unwrap_or(0),
        trace_id,
        span_id,
        event_name: String::new(), // Add the missing field
    };

    // Use the existing LogRow::new method
    LogRow::new(team_id, otlp_log_record, resource, scope)
        .map_err(|e| e.into())
}

fn parse_hex_to_bytes_16(hex_str: &str) -> Option<[u8; 16]> {
    let bytes = hex::decode(hex_str).ok()?;
    if bytes.len() == 16 {
        let mut array = [0u8; 16];
        array.copy_from_slice(&bytes);
        Some(array)
    } else {
        None
    }
}

fn parse_hex_to_bytes_8(hex_str: &str) -> Option<[u8; 8]> {
    let bytes = hex::decode(hex_str).ok()?;
    if bytes.len() == 8 {
        let mut array = [0u8; 8];
        array.copy_from_slice(&bytes);
        Some(array)
    } else {
        None
    }
}