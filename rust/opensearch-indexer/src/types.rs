use std::time::Instant;

use serde::{Deserialize, Deserializer, Serialize};
use uuid::Uuid;

// Lenient i32 deserializer mirroring `property-defs-rs/src/types.rs`. Some legacy producers
// stringify numeric fields; accepting both keeps the consumer poison-pill-resistant.
fn deserialize_string_or_i32<'de, D>(deserializer: D) -> Result<i32, D::Error>
where
    D: Deserializer<'de>,
{
    use serde::de;

    #[derive(Deserialize)]
    #[serde(untagged)]
    enum StringOrInt {
        String(String),
        Int(i32),
    }

    match StringOrInt::deserialize(deserializer)? {
        StringOrInt::String(s) => s
            .parse::<i32>()
            .map_err(|e| de::Error::custom(format!("Failed to parse string as i32: {e}"))),
        StringOrInt::Int(i) => Ok(i),
    }
}

/// Slim view of a `clickhouse_events_json` record. Only the fields the indexer reads;
/// `properties` stays as a raw JSON string so downstream parsers can be selective about
/// which heavy props to pull (the OpenSearch index template excludes the heaviest from
/// `_source`).
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct AiEvent {
    pub uuid: Uuid,
    #[serde(deserialize_with = "deserialize_string_or_i32")]
    pub team_id: i32,
    pub event: String,
    pub timestamp: String,
    pub properties: Option<String>,
}

/// Document body indexed into the `llm-traces` write alias. Field names and types match
/// `products/llm_analytics/opensearch/llm-traces-v0_1.template.json`.
#[derive(Clone, Debug, Serialize)]
pub struct IndexDoc {
    #[serde(rename = "@timestamp")]
    pub timestamp: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace_id: Option<String>,
    pub team_id: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tool_names: Vec<String>,
    pub is_error: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cost: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latency_ms: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,

    /// `_id` for the bulk action line. Skipped from the body; the bulk writer formats it
    /// into `{"index":{"_id":"<event_uuid>"}}` for idempotent re-indexing on consumer
    /// replay.
    #[serde(skip)]
    pub event_uuid: Uuid,

    /// Wall-clock instant when the event finished parsing. Used to observe
    /// end-to-end ingestion lag and to anchor the bulk batch's age-based flush
    /// trigger.
    #[serde(skip)]
    pub parsed_at: Instant,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn fixture_doc() -> IndexDoc {
        IndexDoc {
            timestamp: "2024-01-01T12:00:00.000Z".to_string(),
            trace_id: Some("trace-1".to_string()),
            team_id: 42,
            model: Some("gpt-4".to_string()),
            provider: None,
            tool_names: Vec::new(),
            is_error: false,
            cost: Some(0.001),
            latency_ms: Some(500),
            input: Some("Hello".to_string()),
            output: None,
            error: None,
            event_uuid: Uuid::nil(),
            parsed_at: Instant::now(),
        }
    }

    #[test]
    fn serialize_renames_timestamp_to_at_timestamp() {
        let json = serde_json::to_string(&fixture_doc()).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["@timestamp"], "2024-01-01T12:00:00.000Z");
        assert!(
            v.get("timestamp").is_none(),
            "raw `timestamp` must not appear"
        );
    }

    #[test]
    fn serialize_skips_internal_fields() {
        let json = serde_json::to_string(&fixture_doc()).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert!(
            v.get("event_uuid").is_none(),
            "event_uuid is the bulk action _id, not body"
        );
        assert!(
            v.get("parsed_at").is_none(),
            "parsed_at is internal metric state"
        );
    }

    #[test]
    fn serialize_omits_none_and_empty_optional_fields() {
        let json = serde_json::to_string(&fixture_doc()).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert!(v.get("provider").is_none(), "None Option must be skipped");
        assert!(v.get("output").is_none(), "None Option must be skipped");
        assert!(v.get("error").is_none(), "None Option must be skipped");
        assert!(v.get("tool_names").is_none(), "empty Vec must be skipped");
    }

    #[test]
    fn serialize_includes_present_fields() {
        let json = serde_json::to_string(&fixture_doc()).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["trace_id"], "trace-1");
        assert_eq!(v["team_id"], 42);
        assert_eq!(v["model"], "gpt-4");
        assert_eq!(v["is_error"], false);
        assert_eq!(v["cost"], 0.001);
        assert_eq!(v["latency_ms"], 500);
        assert_eq!(v["input"], "Hello");
    }

    #[test]
    fn serialize_includes_non_empty_tool_names() {
        let mut doc = fixture_doc();
        doc.tool_names = vec!["get_weather".to_string(), "search".to_string()];
        let json = serde_json::to_string(&doc).unwrap();
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(
            v["tool_names"],
            serde_json::json!(["get_weather", "search"])
        );
    }
}

/// Channel message between the consumer and the sink. `Skip` carries no payload —
/// it just lets the sink advance the partition offset in receive order so a
/// non-`$ai_*` event landing after an in-flight `Index(...)` can't commit ahead of
/// it.
///
/// `IndexDoc` is boxed so each channel slot is pointer-sized; otherwise mpsc
/// pre-allocates the largest variant on every slot, including the cheap `Skip`s.
#[derive(Debug)]
pub enum SinkMsg {
    Index(Box<IndexDoc>),
    Skip,
}
