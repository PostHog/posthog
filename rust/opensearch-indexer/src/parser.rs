use std::time::Instant;

use serde::Deserialize;
use serde_json::value::RawValue;
use serde_json::Value;
use thiserror::Error;

use crate::types::{AiEvent, IndexDoc};

const AI_EVENT_PREFIX: &str = "$ai_";

#[derive(Debug, Error)]
pub enum ParseError {
    #[error("invalid properties JSON: {0}")]
    InvalidProperties(#[from] serde_json::Error),
}

/// Parse a `clickhouse_events_json` record into an `IndexDoc`. Returns `Ok(None)` for
/// non-`$ai_*` events so the caller can advance the offset and skip the bulk channel.
pub fn parse(event: &AiEvent) -> Result<Option<IndexDoc>, ParseError> {
    if !event.event.starts_with(AI_EVENT_PREFIX) {
        return Ok(None);
    }

    let props: AiProps = match event.properties.as_deref() {
        Some(s) => serde_json::from_str(s)?,
        None => AiProps::default(),
    };

    let latency_ms = props.latency.map(|s| (s * 1000.0).round() as i64);

    let output = props
        .output_choices
        .as_deref()
        .map(render_text)
        .or_else(|| props.output_legacy.as_deref().map(render_text));

    Ok(Some(IndexDoc {
        timestamp: normalize_timestamp(&event.timestamp),
        trace_id: props.trace_id,
        team_id: event.team_id,
        model: props.model,
        provider: props.provider,
        tool_names: extract_tool_names(props.tools.as_deref()),
        is_error: props.is_error,
        cost: props.cost,
        latency_ms,
        input: props.input.as_deref().map(render_text),
        output,
        error: props.error.as_deref().map(render_text),
        event_uuid: event.uuid,
        parsed_at: Instant::now(),
    }))
}

/// Single-pass deserialization target for `$ai_*` event properties. Heavy / polymorphic
/// fields stay as `Box<RawValue>` so we ship the original JSON text to OpenSearch
/// without re-serializing.
#[derive(Default, Deserialize)]
struct AiProps {
    #[serde(rename = "$ai_trace_id", default)]
    trace_id: Option<String>,
    #[serde(rename = "$ai_model", default)]
    model: Option<String>,
    #[serde(rename = "$ai_provider", default)]
    provider: Option<String>,
    #[serde(rename = "$ai_total_cost_usd", default)]
    cost: Option<f64>,
    #[serde(rename = "$ai_latency", default)]
    latency: Option<f64>,
    #[serde(rename = "$ai_is_error", default)]
    is_error: bool,

    #[serde(rename = "$ai_input", default)]
    input: Option<Box<RawValue>>,
    #[serde(rename = "$ai_output", default)]
    output_legacy: Option<Box<RawValue>>,
    #[serde(rename = "$ai_output_choices", default)]
    output_choices: Option<Box<RawValue>>,
    #[serde(rename = "$ai_error", default)]
    error: Option<Box<RawValue>>,

    #[serde(rename = "$ai_tools", default)]
    tools: Option<Vec<Value>>,
}

/// Render a polymorphic JSON value: unwrap JSON-string literals (so `"Hi"` ships as
/// `Hi`, not `"Hi"`), pass any other shape through as the original JSON text. Skips
/// the parse-and-reserialize round trip the bulk writer would otherwise pay on
/// nested arrays / objects.
fn render_text(raw: &RawValue) -> String {
    let s = raw.get();
    if s.starts_with('"') {
        if let Ok(unwrapped) = serde_json::from_str::<String>(s) {
            return unwrapped;
        }
    }
    s.to_string()
}

fn extract_tool_names(tools: Option<&[Value]>) -> Vec<String> {
    let Some(arr) = tools else {
        return Vec::new();
    };
    arr.iter()
        .filter_map(|item| match item {
            Value::String(s) => Some(s.clone()),
            Value::Object(m) => m
                .get("name")
                .and_then(Value::as_str)
                .map(str::to_string)
                .or_else(|| {
                    m.get("function")
                        .and_then(|f| f.get("name"))
                        .and_then(Value::as_str)
                        .map(str::to_string)
                }),
            _ => None,
        })
        .collect()
}

// OpenSearch's default date parser expects ISO-8601; ClickHouse DateTime64 emits
// `YYYY-MM-DD HH:MM:SS.ffffff` without a `T` or timezone. Patch both up so the
// `@timestamp` field round-trips into a `date`-typed mapping.
fn normalize_timestamp(ts: &str) -> String {
    let mut out = ts.replace(' ', "T");
    let has_tz = if let Some(t_pos) = out.find('T') {
        let after_t = &out[t_pos + 1..];
        after_t.contains('Z') || after_t.contains('+') || after_t.contains('-')
    } else {
        false
    };
    if !has_tz {
        out.push('Z');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    fn ai_event(event: &str, properties: Option<&str>) -> AiEvent {
        AiEvent {
            uuid: Uuid::nil(),
            team_id: 42,
            event: event.to_string(),
            timestamp: "2024-01-01 12:00:00.000000".to_string(),
            properties: properties.map(str::to_string),
        }
    }

    #[test]
    fn non_ai_events_are_skipped() {
        let evt = ai_event("$pageview", Some("{}"));
        assert!(parse(&evt).unwrap().is_none());
    }

    #[test]
    fn ai_generation_extracts_canonical_fields() {
        let props = serde_json::json!({
            "$ai_trace_id": "trace-1",
            "$ai_model": "gpt-4",
            "$ai_provider": "openai",
            "$ai_input": "Hello",
            "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi"}}],
            "$ai_total_cost_usd": 0.001,
            "$ai_latency": 0.5,
            "$ai_is_error": false,
        })
        .to_string();

        let evt = ai_event("$ai_generation", Some(&props));
        let doc = parse(&evt).unwrap().expect("matched $ai_*");

        assert_eq!(doc.trace_id.as_deref(), Some("trace-1"));
        assert_eq!(doc.team_id, 42);
        assert_eq!(doc.model.as_deref(), Some("gpt-4"));
        assert_eq!(doc.provider.as_deref(), Some("openai"));
        assert_eq!(doc.cost, Some(0.001));
        assert_eq!(doc.latency_ms, Some(500));
        assert!(!doc.is_error);
        assert_eq!(doc.input.as_deref(), Some("Hello"));
        assert!(doc.output.as_deref().unwrap().contains("Hi"));
        assert_eq!(doc.timestamp, "2024-01-01T12:00:00.000000Z");
        assert!(doc.tool_names.is_empty());
    }

    #[test]
    fn missing_properties_yields_minimal_doc() {
        let evt = ai_event("$ai_generation", None);
        let doc = parse(&evt).unwrap().expect("matched $ai_*");
        assert_eq!(doc.team_id, 42);
        assert!(doc.trace_id.is_none());
        assert!(!doc.is_error);
    }

    #[test]
    fn malformed_properties_returns_invalid_properties_error() {
        let evt = ai_event("$ai_generation", Some("{not json"));
        match parse(&evt) {
            Err(ParseError::InvalidProperties(_)) => {}
            other => panic!("expected InvalidProperties, got {other:?}"),
        }
    }

    #[test]
    fn output_falls_back_from_choices_to_legacy_field() {
        let props = serde_json::json!({"$ai_output": "legacy"}).to_string();
        let evt = ai_event("$ai_generation", Some(&props));
        let doc = parse(&evt).unwrap().unwrap();
        assert_eq!(doc.output.as_deref(), Some("legacy"));
    }

    #[test]
    fn tool_names_extract_from_function_calls() {
        let props = serde_json::json!({
            "$ai_tools": [
                {"type": "function", "function": {"name": "get_weather"}},
                {"name": "search"},
                "raw_string_tool",
            ]
        })
        .to_string();
        let evt = ai_event("$ai_generation", Some(&props));
        let doc = parse(&evt).unwrap().unwrap();
        assert_eq!(doc.tool_names, vec!["get_weather", "search", "raw_string_tool"]);
    }

    #[test]
    fn iso_timestamp_passes_through() {
        let mut evt = ai_event("$ai_generation", Some("{}"));
        evt.timestamp = "2024-01-01T12:00:00.000Z".to_string();
        let doc = parse(&evt).unwrap().unwrap();
        assert_eq!(doc.timestamp, "2024-01-01T12:00:00.000Z");
    }

    #[test]
    fn tz_offset_timestamp_passes_through() {
        let mut evt = ai_event("$ai_generation", Some("{}"));
        evt.timestamp = "2024-01-01T12:00:00+00:00".to_string();
        let doc = parse(&evt).unwrap().unwrap();
        assert_eq!(doc.timestamp, "2024-01-01T12:00:00+00:00");
    }

    #[test]
    fn input_unwraps_string_value() {
        let props = serde_json::json!({"$ai_input": "Hello"}).to_string();
        let evt = ai_event("$ai_generation", Some(&props));
        let doc = parse(&evt).unwrap().unwrap();
        // Important: TextOrJson::Text path returns the unescaped string, not the JSON
        // form `"\"Hello\""`. The bulk writer relies on this for OS `text` mappings.
        assert_eq!(doc.input.as_deref(), Some("Hello"));
    }

    #[test]
    fn input_preserves_nested_array_as_json() {
        let props = serde_json::json!({
            "$ai_input": [{"role": "user", "content": "Hi"}]
        })
        .to_string();
        let evt = ai_event("$ai_generation", Some(&props));
        let doc = parse(&evt).unwrap().unwrap();
        let raw = doc.input.expect("input present");
        // Round-trips back to the original structure.
        let parsed: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(parsed[0]["role"], "user");
        assert_eq!(parsed[0]["content"], "Hi");
    }
}
