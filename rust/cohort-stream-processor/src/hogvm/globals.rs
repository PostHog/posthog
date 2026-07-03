//! Build HogVM globals dicts from [`CohortStreamEvent`]s for cohort bytecode evaluation.

use chrono::{DateTime, NaiveDateTime};
use metrics::counter;
use serde_json::{json, Value};

use crate::consumers::events::CohortStreamEvent;
use crate::observability::metrics::STAGE1_GLOBALS_PARSE_ERROR;

/// A malformed `properties`/`person_properties` JSON payload.
#[derive(Debug, thiserror::Error)]
#[error("failed to parse event `{field}` as JSON: {source}")]
pub struct GlobalsError {
    pub field: &'static str,
    #[source]
    pub source: serde_json::Error,
}

pub fn build_behavioral_globals(event: &CohortStreamEvent) -> Result<Value, GlobalsError> {
    let properties = parse_optional_json(event.properties.as_deref(), "properties")?;
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;

    let elements_chain = elements_chain(event, &properties);
    let timestamp = normalize_timestamp(&event.timestamp);

    let person = json!({ "id": event.person_id.as_str(), "properties": person_properties });
    let pdi = json!({
        "distinct_id": event.distinct_id.as_str(),
        "person_id": event.person_id.as_str(),
        "person": person.clone(),
    });

    Ok(json!({
        "event": event.event.as_str(),
        "uuid": event.uuid.as_str(),
        "elements_chain": elements_chain,
        "elements_chain_href": "",
        "elements_chain_texts": [],
        "elements_chain_ids": [],
        "elements_chain_elements": [],
        "timestamp": timestamp,
        "properties": properties,
        "person": person,
        "pdi": pdi,
        "distinct_id": event.distinct_id.as_str(),
        "$group_0": null,
        "$group_1": null,
        "$group_2": null,
        "$group_3": null,
        "$group_4": null,
        "group_0": { "properties": {} },
        "group_1": { "properties": {} },
        "group_2": { "properties": {} },
        "group_3": { "properties": {} },
        "group_4": { "properties": {} },
        "variables": {},
    }))
}

pub fn build_person_property_globals(event: &CohortStreamEvent) -> Result<Value, GlobalsError> {
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;

    Ok(json!({
        "person": { "id": event.person_id.as_str(), "properties": person_properties },
        "project": { "id": event.team_id },
    }))
}

/// Parse a raw JSON payload, treating `None` or empty string as `{}`.
fn parse_optional_json(raw: Option<&str>, field: &'static str) -> Result<Value, GlobalsError> {
    let Some(raw) = raw.filter(|s| !s.is_empty()) else {
        return Ok(json!({}));
    };
    serde_json::from_str(raw).map_err(|source| {
        counter!(STAGE1_GLOBALS_PARSE_ERROR, "field" => field).increment(1);
        GlobalsError { field, source }
    })
}

/// `event.elements_chain ?? properties['$elements_chain'] ?? null`
fn elements_chain(event: &CohortStreamEvent, properties: &Value) -> Value {
    match &event.elements_chain {
        Some(chain) => Value::String(chain.clone()),
        None => properties
            .get("$elements_chain")
            .cloned()
            .unwrap_or(Value::Null),
    }
}

/// Normalize a ClickHouse `"YYYY-MM-DD HH:MM:SS.ffffff"` timestamp to ISO 8601. RFC 3339 input
/// passes through unchanged.
fn normalize_timestamp(raw: &str) -> String {
    if DateTime::parse_from_rfc3339(raw).is_ok() {
        return raw.to_string();
    }
    NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f")
        .map(|naive| naive.format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string())
        .unwrap_or_else(|_| raw.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event() -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: 42,
            person_id: "p-123".to_string(),
            distinct_id: "d-1".to_string(),
            uuid: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            event: "$pageview".to_string(),
            timestamp: "2026-05-26 12:34:56.789000".to_string(),
            properties: Some(r#"{"$browser":"Chrome"}"#.to_string()),
            person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
            elements_chain: Some("a:href=\"/x\"".to_string()),
            source_offset: 0,
            source_partition: 0,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    #[test]
    fn behavioral_globals_emit_the_full_node_key_set() {
        let globals = build_behavioral_globals(&event()).unwrap();
        let obj = globals.as_object().unwrap();
        for key in [
            "event",
            "uuid",
            "elements_chain",
            "elements_chain_href",
            "elements_chain_texts",
            "elements_chain_ids",
            "elements_chain_elements",
            "timestamp",
            "properties",
            "person",
            "pdi",
            "distinct_id",
            "$group_0",
            "$group_1",
            "$group_2",
            "$group_3",
            "$group_4",
            "group_0",
            "group_1",
            "group_2",
            "group_3",
            "group_4",
            "variables",
        ] {
            assert!(obj.contains_key(key), "behavioral globals missing `{key}`");
        }
    }

    #[test]
    fn behavioral_globals_shape_matches_node() {
        let globals = build_behavioral_globals(&event()).unwrap();
        assert_eq!(globals["event"], json!("$pageview"));
        assert_eq!(
            globals["uuid"],
            json!("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        );
        assert_eq!(globals["distinct_id"], json!("d-1"));
        assert_eq!(globals["properties"], json!({ "$browser": "Chrome" }));
        assert_eq!(globals["person"]["id"], json!("p-123"));
        assert_eq!(
            globals["person"]["properties"],
            json!({ "email": "u@p.com" })
        );
        assert_eq!(globals["pdi"]["distinct_id"], json!("d-1"));
        assert_eq!(globals["pdi"]["person_id"], json!("p-123"));
        assert_eq!(globals["pdi"]["person"]["id"], json!("p-123"));
        assert_eq!(globals["elements_chain"], json!("a:href=\"/x\""));
        assert_eq!(globals["$group_0"], Value::Null);
        assert_eq!(globals["group_0"], json!({ "properties": {} }));
        assert_eq!(globals["elements_chain_texts"], json!([]));
        assert_eq!(globals["variables"], json!({}));
    }

    #[test]
    fn person_globals_are_the_small_strict_shape() {
        let globals = build_person_property_globals(&event()).unwrap();
        assert_eq!(
            globals,
            json!({
                "person": { "id": "p-123", "properties": { "email": "u@p.com" } },
                "project": { "id": 42 },
            })
        );
    }

    #[test]
    fn null_properties_default_to_empty_object() {
        let mut e = event();
        e.properties = None;
        e.person_properties = None;
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["properties"], json!({}));
        assert_eq!(globals["person"]["properties"], json!({}));

        let person_globals = build_person_property_globals(&e).unwrap();
        assert_eq!(person_globals["person"]["properties"], json!({}));
    }

    #[test]
    fn empty_string_payload_parses_to_empty_object() {
        assert_eq!(
            parse_optional_json(Some(""), "properties").unwrap(),
            json!({})
        );
        assert_eq!(
            parse_optional_json(Some(""), "person_properties").unwrap(),
            json!({})
        );
    }

    #[test]
    fn behavioral_globals_treat_empty_string_payloads_as_empty_objects() {
        let mut e = event();
        e.properties = Some(String::new());
        e.person_properties = Some(String::new());
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["properties"], json!({}));
        assert_eq!(globals["person"]["properties"], json!({}));
        assert_eq!(globals["pdi"]["person"]["properties"], json!({}));
    }

    #[test]
    fn person_globals_treat_empty_string_person_properties_as_empty_object() {
        let mut e = event();
        e.person_properties = Some(String::new());
        let globals = build_person_property_globals(&e).unwrap();
        assert_eq!(globals["person"]["properties"], json!({}));
    }

    #[test]
    fn malformed_properties_is_an_error() {
        let mut e = event();
        e.properties = Some("{not json".to_string());
        let err = build_behavioral_globals(&e).unwrap_err();
        assert_eq!(err.field, "properties");
    }

    #[test]
    fn malformed_person_properties_is_an_error_in_both_builders() {
        let mut e = event();
        e.person_properties = Some("nope".to_string());
        assert_eq!(
            build_behavioral_globals(&e).unwrap_err().field,
            "person_properties"
        );
        assert_eq!(
            build_person_property_globals(&e).unwrap_err().field,
            "person_properties"
        );
    }

    #[test]
    fn non_object_properties_pass_through_as_is() {
        let mut e = event();
        e.properties = Some("[1, 2, 3]".to_string());
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["properties"], json!([1, 2, 3]));
    }

    #[test]
    fn elements_chain_falls_back_to_properties() {
        let mut e = event();
        e.elements_chain = None;
        e.properties = Some(r#"{"$elements_chain":"from-props"}"#.to_string());
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["elements_chain"], json!("from-props"));

        e.properties = Some("{}".to_string());
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["elements_chain"], Value::Null);
    }

    #[test]
    fn clickhouse_timestamp_normalizes_to_iso_millis_z() {
        assert_eq!(
            normalize_timestamp("2026-05-26 12:34:56.789000"),
            "2026-05-26T12:34:56.789Z"
        );
        assert_eq!(
            normalize_timestamp("2026-01-01 00:00:00.000123"),
            "2026-01-01T00:00:00.000Z"
        );
    }

    #[test]
    fn already_iso_timestamp_passes_through_unchanged() {
        assert_eq!(
            normalize_timestamp("2026-05-26T12:34:56.789Z"),
            "2026-05-26T12:34:56.789Z"
        );
    }

    #[test]
    fn timestamp_in_built_globals_is_normalized() {
        let globals = build_behavioral_globals(&event()).unwrap();
        assert_eq!(globals["timestamp"], json!("2026-05-26T12:34:56.789Z"));
    }
}
