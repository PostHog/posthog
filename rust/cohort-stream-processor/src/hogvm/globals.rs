//! `convertClickhouseRawEventToFilterGlobals` port (TDD §2.4, M8.c).
//!
//! Two pure builders turn a [`CohortStreamEvent`] into the HogVM globals dict the compiled
//! cohort bytecode reads. They are the faithful Rust port of the Node functions:
//! - [`build_behavioral_globals`] ⇔ `convertClickhouseRawEventToFilterGlobals`
//!   (`nodejs/src/cdp/utils/hog-function-filtering.ts:101-223`)
//! - [`build_person_property_globals`] ⇔ the inline `personGlobals` object
//!   (`nodejs/src/cdp/consumers/cdp-precalculated-filters.consumer.ts:254-262`)
//!
//! ## Why the full top-level key set (behavioral)
//!
//! The Rust VM treats a missing *top-level* global as an error (`UnknownGlobal`,
//! `rust/common/hogvm/src/vm.rs:133`) but a missing *nested* key as `null` (`vm.rs:124-128`).
//! So every top-level key Node emits must be present for any behavioral bytecode to resolve its
//! globals, even though supported cohort bytecode only ever reads `event` and `properties.*`.
//!
//! ## Node-parity divergences (all safe by construction)
//!
//! The shuffler intentionally drops group properties, `person_mode`, `created_at` and
//! `project_id` (`cohort-event-shuffler/src/event.rs:4-5`, TDD §2.2). We therefore emit Node's
//! *empty* group defaults (`$group_N = null`, `group_N = {properties: {}}`) rather than
//! reconstructing them — which matches Node exactly for events without group properties, and is
//! irrelevant for events with them because supported realtime cohorts never filter on groups,
//! `elements_chain`, or `timestamp` (a supported leaf's bytecode consumes only its `key` plus
//! `event_filters` over `properties.*` / `person.properties.*` — `posthog/cdp/filters.py`). The
//! `elements_chain_*` derived fields are likewise emitted as static `""`/`[]` (Node computes them
//! lazily and supported bytecode never reads them).
//!
//! ## Malformed payloads skip the event (not substitute `{}`)
//!
//! Node parses `properties` / `person_properties` with `JSON.parse`, which throws on malformed
//! input; the throw is caught per-message (`consumer.ts:200`) and the *whole event* is skipped —
//! no filter runs. The builders mirror this: a `Some` payload that fails to parse returns
//! [`GlobalsError`] (and increments `stage1_globals_parse_error_total{field}`) so the Stage 1
//! caller (PR 1.6) skips the event, rather than silently substituting an empty object.

use chrono::{DateTime, NaiveDateTime};
use metrics::counter;
use serde_json::{json, Value};

use crate::consumers::events::CohortStreamEvent;
use crate::observability::metrics::STAGE1_GLOBALS_PARSE_ERROR;

/// A raw `properties` / `person_properties` payload that was present but not valid JSON. The
/// Stage 1 caller treats this as a per-event skip (Node parity, `consumer.ts:200`); `field`
/// identifies which payload failed, for logging.
#[derive(Debug, thiserror::Error)]
#[error("failed to parse event `{field}` as JSON: {source}")]
pub struct GlobalsError {
    pub field: &'static str,
    #[source]
    pub source: serde_json::Error,
}

/// Build the full behavioral globals dict (Node's `convertClickhouseRawEventToFilterGlobals`).
///
/// Returns [`GlobalsError`] if `properties` or `person_properties` is present but malformed, so
/// the caller skips the event exactly as Node does.
pub fn build_behavioral_globals(event: &CohortStreamEvent) -> Result<Value, GlobalsError> {
    let properties = parse_optional_json(event.properties.as_deref(), "properties")?;
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;

    let elements_chain = elements_chain(event, &properties);
    let timestamp = normalize_timestamp(&event.timestamp);

    // `person.id` is the *person* id, never the distinct id — see TDD §2.4. Built once and
    // shared into `pdi` (clone) so both spots are identical, à la Node's single `personProperties`.
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
        // Static defaults: Node computes these lazily and supported bytecode never reads them.
        "elements_chain_href": "",
        "elements_chain_texts": [],
        "elements_chain_ids": [],
        "elements_chain_elements": [],
        "timestamp": timestamp,
        "properties": properties,
        "person": person,
        "pdi": pdi,
        "distinct_id": event.distinct_id.as_str(),
        // Group fields are dropped by the shuffler (TDD §2.2); emit Node's empty defaults.
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

/// Build the small, strict person-property globals dict (Node's inline `personGlobals`).
///
/// The Stage 1 caller (PR 1.6) invokes this only when `person_properties` is present and
/// non-empty (Node's guard, `consumer.ts:251`); a `None` payload is handled defensively as an
/// empty object. Node literally feeds `team_id` into `project.id` (`consumer.ts:260`) — matched
/// here for byte parity, not because it is conceptually a project id.
pub fn build_person_property_globals(event: &CohortStreamEvent) -> Result<Value, GlobalsError> {
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;

    Ok(json!({
        "person": { "id": event.person_id.as_str(), "properties": person_properties },
        "project": { "id": event.team_id },
    }))
}

/// Parse a raw JSON payload: `None` → `{}` (Node's `event.x ? parseJSON(x) : {}`), `Some(valid)`
/// → the parsed value passed through as-is (a non-object behaves identically to Node), and
/// `Some(invalid)` → [`GlobalsError`] plus the parse-error counter.
fn parse_optional_json(raw: Option<&str>, field: &'static str) -> Result<Value, GlobalsError> {
    let Some(raw) = raw else {
        return Ok(json!({}));
    };
    serde_json::from_str(raw).map_err(|source| {
        counter!(STAGE1_GLOBALS_PARSE_ERROR, "field" => field).increment(1);
        GlobalsError { field, source }
    })
}

/// `event.elements_chain ?? properties['$elements_chain']` (`hog-function-filtering.ts:103`).
/// Falls back to `null` (Node's `undefined`) when neither is present; the top-level key must
/// still exist so any nested access resolves to null rather than erroring.
fn elements_chain(event: &CohortStreamEvent, properties: &Value) -> Value {
    match &event.elements_chain {
        Some(chain) => Value::String(chain.clone()),
        None => properties
            .get("$elements_chain")
            .cloned()
            .unwrap_or(Value::Null),
    }
}

/// Normalize the ClickHouse-format timestamp to ISO 8601, matching Node's
/// `DateTime.fromISO(ts).isValid ? ts : clickHouseTimestampToISO(ts)` (`hog-function-filtering.ts:106`).
///
/// An already-valid RFC 3339 string passes through unchanged; otherwise the ClickHouse format
/// `"%Y-%m-%d %H:%M:%S%.f"` is parsed as UTC and re-emitted with millisecond precision and a `Z`
/// suffix — byte-identical to Luxon `.toISO()` on a UTC `DateTime` (verified: `.789000` →
/// `.789Z`, sub-millisecond digits truncated). No supported bytecode reads `timestamp`; this is
/// ported for fidelity and pinned by a fixture to forestall a latent divergence. A value that
/// matches neither shape passes through unchanged.
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

    /// A fully-populated event with both payloads present.
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
        // person.id is the person id, NOT the distinct id.
        assert_eq!(globals["person"]["id"], json!("p-123"));
        assert_eq!(
            globals["person"]["properties"],
            json!({ "email": "u@p.com" })
        );
        assert_eq!(globals["pdi"]["distinct_id"], json!("d-1"));
        assert_eq!(globals["pdi"]["person_id"], json!("p-123"));
        assert_eq!(globals["pdi"]["person"]["id"], json!("p-123"));
        assert_eq!(globals["elements_chain"], json!("a:href=\"/x\""));
        // Group + derived defaults.
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
                // team_id is fed into project.id verbatim (Node parity).
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
        // Node assigns whatever parseJSON returns; a JSON array stays an array.
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

        // Neither present → null (the key still exists).
        e.properties = Some("{}".to_string());
        let globals = build_behavioral_globals(&e).unwrap();
        assert_eq!(globals["elements_chain"], Value::Null);
    }

    #[test]
    fn clickhouse_timestamp_normalizes_to_iso_millis_z() {
        // Pinned byte-for-byte against Luxon `.toISO()`: microseconds truncate to milliseconds.
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
