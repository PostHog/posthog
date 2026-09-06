//! Build HogVM globals dicts from [`CohortStreamEvent`]s for cohort bytecode evaluation.

use chrono::{DateTime, NaiveDateTime};
use metrics::counter;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::events::CohortStreamEvent;
use crate::filters::TeamId;
use crate::hogvm::analysis::{GlobalRoot, GlobalsPlan, GroupIndex};
use crate::metrics::STAGE1_GLOBALS_PARSE_ERROR;

/// A malformed `properties`/`person_properties` JSON payload.
#[derive(Debug, thiserror::Error)]
#[error("failed to parse event `{field}` as JSON: {source}")]
pub struct GlobalsError {
    pub field: &'static str,
    #[source]
    pub source: serde_json::Error,
}

/// Holds every root `plan` says the conditions can name; see [`GlobalsPlan`] for why omitting one
/// they do read raises rather than reads null.
///
/// Both parses run whatever `plan` says, which is load-bearing: two callers evaluating one event
/// against different plans must agree on whether its payloads are malformed.
pub fn build_behavioral_globals(
    event: &CohortStreamEvent,
    plan: GlobalsPlan,
) -> Result<Value, GlobalsError> {
    let properties = parse_optional_json(event.properties.as_deref(), "properties")?;
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;
    let person = object([
        ("id", text(&event.person_id)),
        ("properties", person_properties),
    ]);

    let mut roots = Roots::new(plan);
    roots.set(GlobalRoot::Event, || text(&event.event));
    roots.set(GlobalRoot::Uuid, || text(&event.uuid));
    // Reads `properties`, which the `Properties` root below moves away.
    roots.set(GlobalRoot::ElementsChain, || {
        elements_chain(event, &properties)
    });
    roots.set(GlobalRoot::ElementsChainHref, || {
        Value::String(String::new())
    });
    for root in [
        GlobalRoot::ElementsChainTexts,
        GlobalRoot::ElementsChainIds,
        GlobalRoot::ElementsChainElements,
    ] {
        roots.set(root, || Value::Array(Vec::new()));
    }
    roots.set(GlobalRoot::Timestamp, || {
        Value::String(normalize_timestamp(&event.timestamp))
    });
    roots.set(GlobalRoot::DistinctId, || text(&event.distinct_id));
    for index in GroupIndex::all() {
        roots.set(GlobalRoot::DollarGroup(index), || Value::Null);
        roots.set(GlobalRoot::Group(index), empty_group);
    }
    roots.set(GlobalRoot::Variables, || Value::Object(Map::new()));
    // Copies `person`, which the `Person` root below moves away.
    roots.set(GlobalRoot::Pdi, || {
        object([
            ("distinct_id", text(&event.distinct_id)),
            ("person_id", text(&event.person_id)),
            ("person", person.clone()),
        ])
    });
    roots.set(GlobalRoot::Person, || person);
    roots.set(GlobalRoot::Properties, || properties);
    Ok(roots.finish())
}

/// An unread root costs nothing, not even building its value, because `set` skips the closure.
struct Roots {
    plan: GlobalsPlan,
    map: Map<String, Value>,
}

impl Roots {
    fn new(plan: GlobalsPlan) -> Self {
        Self {
            plan,
            map: Map::new(),
        }
    }

    fn set(&mut self, root: GlobalRoot, value: impl FnOnce() -> Value) {
        if self.plan.reads(root) {
            self.map.insert(root.as_str().to_owned(), value());
        }
    }

    fn finish(self) -> Value {
        Value::Object(self.map)
    }
}

fn text(value: &str) -> Value {
    Value::String(value.to_owned())
}

fn object<const N: usize>(entries: [(&str, Value); N]) -> Value {
    Value::Object(
        entries
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value))
            .collect(),
    )
}

fn empty_group() -> Value {
    object([("properties", Value::Object(Map::new()))])
}

pub fn build_person_property_globals(event: &CohortStreamEvent) -> Result<Value, GlobalsError> {
    let person_properties =
        parse_optional_json(event.person_properties.as_deref(), "person_properties")?;
    Ok(person_scope_globals(
        event.team_id,
        event.person_id.as_str(),
        person_properties,
    ))
}

/// Globals for a persons-table scan row — no event exists, only the person's latest properties.
/// Funnels through the same shape core as [`build_person_property_globals`], so the seeder's
/// person-property evaluation is byte-identical to the live event path's.
pub fn build_person_scan_globals(
    team_id: TeamId,
    person_id: Uuid,
    properties: &str,
) -> Result<Value, GlobalsError> {
    // Quiet parse: a seeder scan failure must not increment the stream processor's Stage 1
    // counter — the seeder meters its own skipped rows.
    let person_properties = parse_optional_json_quiet(Some(properties), "person_properties")?;
    Ok(person_scope_globals(
        team_id.0,
        &person_id.to_string(),
        person_properties,
    ))
}

/// The one constructor of the `{"person":{"id","properties"},"project":{"id"}}` shape.
fn person_scope_globals(team_id: i32, person_id: &str, person_properties: Value) -> Value {
    json!({
        "person": { "id": person_id, "properties": person_properties },
        "project": { "id": team_id },
    })
}

/// Parse a raw JSON payload, treating `None` or empty string as `{}`, counting failures on the
/// Stage 1 metric — the live event paths' behavior.
fn parse_optional_json(raw: Option<&str>, field: &'static str) -> Result<Value, GlobalsError> {
    parse_optional_json_quiet(raw, field).inspect_err(|_| {
        counter!(STAGE1_GLOBALS_PARSE_ERROR, "field" => field).increment(1);
    })
}

/// The metric-free parse core, for callers that meter failures themselves.
fn parse_optional_json_quiet(
    raw: Option<&str>,
    field: &'static str,
) -> Result<Value, GlobalsError> {
    let Some(raw) = raw.filter(|s| !s.is_empty()) else {
        return Ok(json!({}));
    };
    serde_json::from_str(raw).map_err(|source| GlobalsError { field, source })
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
    use std::collections::BTreeSet;

    use hogvm::stl_map;

    use crate::hogvm::analysis::{Projection, ReadPath, RootSet};

    use super::*;

    /// The dict the VM must be handed for [`event`]. Nothing can re-derive it, so this constant is
    /// the record: change it only for a reason that is not "the test failed".
    const PINNED_FULL_GLOBALS: &str = r#"{"$group_0":null,"$group_1":null,"$group_2":null,"$group_3":null,"$group_4":null,"distinct_id":"d-1","elements_chain":"a:href=\"/x\"","elements_chain_elements":[],"elements_chain_href":"","elements_chain_ids":[],"elements_chain_texts":[],"event":"$pageview","group_0":{"properties":{}},"group_1":{"properties":{}},"group_2":{"properties":{}},"group_3":{"properties":{}},"group_4":{"properties":{}},"pdi":{"distinct_id":"d-1","person":{"id":"p-123","properties":{"email":"u@p.com"}},"person_id":"p-123"},"person":{"id":"p-123","properties":{"email":"u@p.com"}},"properties":{"$browser":"Chrome"},"timestamp":"2026-05-26T12:34:56.789Z","uuid":"01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee","variables":{}}"#;

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

    /// Key names alone do not pin this: a changed nesting, empty spelling, or string escaping reads
    /// differently while every `contains_key` assertion still passes.
    #[test]
    fn a_full_plan_rebuilds_the_pinned_dict_and_a_narrower_plan_drops_only_its_roots() {
        let event = event();
        let full = build_behavioral_globals(&event, GlobalsPlan::FULL).unwrap();
        assert_eq!(serde_json::to_string(&full).unwrap(), PINNED_FULL_GLOBALS);

        let reads_every_root_but_pdi = GlobalsPlan::of(&Projection::Reads(
            RootSet::ALL
                .iter()
                .filter(|root| *root != GlobalRoot::Pdi)
                .map(|root| ReadPath::new(root, Vec::new()))
                .collect::<BTreeSet<_>>(),
        ));
        let mut expected = full.as_object().unwrap().clone();
        expected.remove("pdi").expect("the full dict carries `pdi`");
        assert_eq!(
            build_behavioral_globals(&event, reads_every_root_but_pdi).unwrap(),
            Value::Object(expected),
            "dropping `pdi` from the plan changed more than the `pdi` key",
        );

        assert_eq!(
            build_behavioral_globals(&event, GlobalsPlan::NONE).unwrap(),
            json!({}),
        );
    }

    /// An omitted root raises `UnknownGlobal` unless a native shares its name, in which case
    /// `GetGlobal` falls through to `get_fn_reference` and pushes that native as a closure. Only the
    /// native table matters here; the hog STL reaches the VM through the `CallGlobal` symbol table.
    #[test]
    fn no_global_root_name_is_also_a_native_function() {
        let natives = stl_map();
        for root in RootSet::ALL.iter() {
            assert!(
                !natives.contains_key(root.as_str()),
                "the native `{}` shadows a globals root, so omitting that root would push a \
                 closure instead of raising",
                root.as_str(),
            );
        }
    }

    #[test]
    fn behavioral_globals_emit_the_full_node_key_set() {
        let globals = build_behavioral_globals(&event(), GlobalsPlan::FULL).unwrap();
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

    /// Every root a globals dict carries has to be a [`GlobalRoot`], because the analyzer treats a
    /// name outside that enum as reading nothing. A key added here without a matching variant
    /// there would be pruned from a scan while the program still reads it.
    ///
    /// This walks the dicts rather than a list of names, unlike its neighbour above, which asserts
    /// `contains_key` over 23 names and so would not notice a 24th. That difference is what the
    /// test is for, and it means there is no list here to go stale.
    #[test]
    fn every_globals_dict_key_is_a_named_root() {
        let event = event();
        // `build_person_scan_globals` is absent because
        // `scan_globals_are_byte_equal_to_event_globals_for_equal_inputs` already pins its output
        // to `build_person_property_globals`, so its key set is covered here.
        for globals in [
            build_behavioral_globals(&event, GlobalsPlan::FULL).unwrap(),
            build_person_property_globals(&event).unwrap(),
        ] {
            for key in globals.as_object().unwrap().keys() {
                assert!(
                    GlobalRoot::parse(key).is_some(),
                    "globals key `{key}` is not a GlobalRoot, so the analyzer would read a \
                     condition naming it as reading nothing"
                );
            }
        }
    }

    #[test]
    fn behavioral_globals_shape_matches_node() {
        let globals = build_behavioral_globals(&event(), GlobalsPlan::FULL).unwrap();
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
        let globals = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap();
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
        let globals = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap();
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

    /// Shape lock: the scan builder and the live event builder must produce byte-equal globals for
    /// equal inputs — the correctness anchor that keeps seeder evals equivalent to live evals.
    #[test]
    fn scan_globals_are_byte_equal_to_event_globals_for_equal_inputs() {
        let person_id = Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap();
        for properties in [r#"{"email":"u@p.com","plan":"paid"}"#, "", "{}"] {
            let mut e = event();
            e.team_id = 42;
            e.person_id = person_id.to_string();
            e.person_properties = Some(properties.to_string());
            let from_event = build_person_property_globals(&e).unwrap();
            let from_scan = build_person_scan_globals(TeamId(42), person_id, properties).unwrap();
            assert_eq!(
                serde_json::to_string(&from_scan).unwrap(),
                serde_json::to_string(&from_event).unwrap(),
            );
        }
        assert_eq!(
            build_person_scan_globals(TeamId(42), person_id, "").unwrap()["person"]["properties"],
            json!({})
        );
        assert!(build_person_scan_globals(TeamId(42), person_id, "{not json").is_err());
    }

    #[test]
    fn malformed_properties_is_an_error() {
        let mut e = event();
        e.properties = Some("{not json".to_string());
        let err = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap_err();
        assert_eq!(err.field, "properties");
    }

    #[test]
    fn malformed_person_properties_is_an_error_in_both_builders() {
        let mut e = event();
        e.person_properties = Some("nope".to_string());
        assert_eq!(
            build_behavioral_globals(&e, GlobalsPlan::FULL)
                .unwrap_err()
                .field,
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
        let globals = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap();
        assert_eq!(globals["properties"], json!([1, 2, 3]));
    }

    #[test]
    fn elements_chain_falls_back_to_properties() {
        let mut e = event();
        e.elements_chain = None;
        e.properties = Some(r#"{"$elements_chain":"from-props"}"#.to_string());
        let globals = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap();
        assert_eq!(globals["elements_chain"], json!("from-props"));

        e.properties = Some("{}".to_string());
        let globals = build_behavioral_globals(&e, GlobalsPlan::FULL).unwrap();
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
        let globals = build_behavioral_globals(&event(), GlobalsPlan::FULL).unwrap();
        assert_eq!(globals["timestamp"], json!("2026-05-26T12:34:56.789Z"));
    }
}
