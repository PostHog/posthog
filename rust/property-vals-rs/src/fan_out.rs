use serde_json::Value;

use crate::config::ExcludedPropertyKeys;
use crate::metrics_consts::VALUES_DROPPED;
use crate::types::{Event, PropertyType, PropertyValueMessage, TupleKey};

pub const MAX_PROPERTY_KEY_LEN: usize = 400;
pub const MAX_PROPERTY_VALUE_LEN: usize = 255;

pub fn fan_out(event: &Event, excluded: &ExcludedPropertyKeys) -> Vec<(TupleKey, u64)> {
    let mut out = Vec::new();

    if let Some(raw) = &event.properties {
        emit_from_blob(event.team_id, PropertyType::Event, raw, excluded, &mut out);
    }

    out
}

pub fn extract_tuple(msg: &PropertyValueMessage) -> Vec<(TupleKey, u64)> {
    if msg.property_key.is_empty() || msg.property_value.is_empty() {
        return Vec::new();
    }
    vec![(
        TupleKey {
            team_id: msg.team_id,
            property_type: msg.property_type,
            property_key: msg.property_key.clone(),
            property_value: msg.property_value.clone(),
        },
        msg.property_count,
    )]
}

fn emit_from_blob(
    team_id: i64,
    property_type: PropertyType,
    raw: &str,
    excluded: &ExcludedPropertyKeys,
    out: &mut Vec<(TupleKey, u64)>,
) {
    let parsed: Value = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(_) => return,
    };

    let obj = match parsed.as_object() {
        Some(o) => o,
        None => return,
    };

    for (key, value) in obj {
        if value.is_null() {
            metrics::counter!(VALUES_DROPPED, "reason" => "null_value").increment(1);
            continue;
        }

        if excluded.contains(key) {
            metrics::counter!(VALUES_DROPPED, "reason" => "excluded_key").increment(1);
            continue;
        }

        let property_value = coerce_to_string(value);

        if key.is_empty() {
            metrics::counter!(VALUES_DROPPED, "reason" => "empty_key").increment(1);
            continue;
        }
        if key.chars().count() > MAX_PROPERTY_KEY_LEN {
            metrics::counter!(VALUES_DROPPED, "reason" => "key_too_long").increment(1);
            continue;
        }
        if property_value.is_empty() {
            metrics::counter!(VALUES_DROPPED, "reason" => "empty_value").increment(1);
            continue;
        }
        if property_value.chars().count() > MAX_PROPERTY_VALUE_LEN {
            metrics::counter!(VALUES_DROPPED, "reason" => "value_too_long").increment(1);
            continue;
        }

        out.push((
            TupleKey {
                team_id,
                property_type,
                property_key: key.clone(),
                property_value,
            },
            1,
        ));
    }
}

fn coerce_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        _ => v.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use serde_json::{Map, Value};

    fn event(properties: &str) -> Event {
        Event {
            team_id: 2,
            properties: Some(properties.to_string()),
        }
    }

    fn arb_property_string() -> impl Strategy<Value = String> {
        prop_oneof!["[a-zA-Z0-9_$ -]{0,450}", r#"[\x{3042}\x{1F600}]{0,500}"#,]
    }

    fn arb_value() -> impl Strategy<Value = Value> {
        prop_oneof![
            arb_property_string().prop_map(Value::String),
            any::<bool>().prop_map(Value::Bool),
            any::<i64>().prop_map(|n| Value::Number(n.into())),
            Just(Value::Null),
        ]
    }

    prop_compose! {
        fn arb_blob()(
            pairs in prop::collection::vec((arb_property_string(), arb_value()), 0..20),
        ) -> String {
            let map: Map<String, Value> = pairs.into_iter().collect();
            serde_json::to_string(&map).unwrap()
        }
    }

    prop_compose! {
        fn arb_event()(
            team_id: i64,
            properties in prop::option::of(arb_blob()),
        ) -> Event {
            Event { team_id, properties }
        }
    }

    fn none() -> ExcludedPropertyKeys {
        ExcludedPropertyKeys::default()
    }

    fn excluded(keys: &[&str]) -> ExcludedPropertyKeys {
        keys.join(",").parse().unwrap()
    }

    fn check_tuple_invariants(t: &TupleKey, count: u64, expected_team: i64) {
        assert_eq!(t.team_id, expected_team);
        assert!(!t.property_key.is_empty());
        assert!(!t.property_value.is_empty());
        assert!(t.property_key.chars().count() <= MAX_PROPERTY_KEY_LEN);
        assert!(t.property_value.chars().count() <= MAX_PROPERTY_VALUE_LEN);
        assert_eq!(count, 1, "stage-1 fan-out always emits count=1");
    }

    proptest! {
        #[test]
        fn fan_out_outputs_obey_caps_and_team(e in arb_event()) {
            for (t, n) in fan_out(&e, &none()) {
                check_tuple_invariants(&t, n, e.team_id);
            }
        }

        #[test]
        fn fan_out_is_pure(e in arb_event()) {
            prop_assert_eq!(fan_out(&e, &none()), fan_out(&e, &none()));
        }
    }

    #[test]
    fn event_property_produces_event_type_tuple() {
        let tuples = fan_out(&event(r#"{"$browser":"Chrome"}"#), &none());
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_type, PropertyType::Event);
        assert_eq!(tuples[0].0.property_key, "$browser");
        assert_eq!(tuples[0].0.property_value, "Chrome");
        assert_eq!(tuples[0].1, 1);
    }

    #[test]
    fn json_null_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"nullable_field":null}"#), &none());
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_string_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"blank":""}"#), &none());
        assert!(tuples.is_empty());
    }

    #[test]
    fn bool_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_bool":true}"#), &none());
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_value, "true");
    }

    #[test]
    fn number_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_number":42}"#), &none());
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_value, "42");
    }

    #[test]
    fn unparseable_blob_emits_nothing() {
        let tuples = fan_out(&event(r#"not valid json"#), &none());
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_object_emits_nothing() {
        let tuples = fan_out(&event("{}"), &none());
        assert!(tuples.is_empty());
    }

    #[test]
    fn excluded_event_property_keys_are_skipped() {
        let blob =
            r#"{"$insert_id":"abc-123","$browser":"Chrome","distinct_id":"u1","$session_id":"s1"}"#;
        let exclusions = excluded(&["$insert_id", "distinct_id", "$session_id"]);
        let tuples = fan_out(&event(blob), &exclusions);
        assert_eq!(tuples.len(), 1, "only $browser should survive exclusion");
        assert_eq!(tuples[0].0.property_key, "$browser");
        assert_eq!(tuples[0].0.property_value, "Chrome");
    }

    #[test]
    fn empty_exclusion_list_is_a_noop() {
        let blob = r#"{"$browser":"Chrome","email":"a@b.com"}"#;
        let with_default = fan_out(&event(blob), &none());
        let parsed_empty: ExcludedPropertyKeys = "".parse().unwrap();
        let with_parsed_empty = fan_out(&event(blob), &parsed_empty);
        assert_eq!(with_default.len(), 2);
        assert_eq!(with_default, with_parsed_empty);
    }

    fn pv_message(
        team_id: i64,
        property_type: PropertyType,
        key: &str,
        value: &str,
        count: u64,
    ) -> PropertyValueMessage {
        PropertyValueMessage {
            team_id,
            property_type,
            property_key: key.to_string(),
            property_value: value.to_string(),
            property_count: count,
        }
    }

    #[test]
    fn extract_tuple_emits_single_tuple_with_message_count() {
        let msg = pv_message(2, PropertyType::Event, "$browser", "Chrome", 42);
        let out = extract_tuple(&msg);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].0.team_id, 2);
        assert_eq!(out[0].0.property_type, PropertyType::Event);
        assert_eq!(out[0].0.property_key, "$browser");
        assert_eq!(out[0].0.property_value, "Chrome");
        assert_eq!(out[0].1, 42, "count must round-trip from the message");
    }

    #[test]
    fn extract_tuple_carries_property_count_for_person_type() {
        let msg = pv_message(7, PropertyType::Person, "email", "a@b.com", 5);
        let out = extract_tuple(&msg);
        assert_eq!(out[0].0.property_type, PropertyType::Person);
        assert_eq!(out[0].1, 5);
    }

    #[test]
    fn extract_tuple_carries_property_count_for_group_type() {
        let msg = pv_message(7, PropertyType::Group(3), "plan", "enterprise", 11);
        let out = extract_tuple(&msg);
        assert_eq!(out[0].0.property_type, PropertyType::Group(3));
        assert_eq!(out[0].1, 11);
    }

    #[test]
    fn extract_tuple_drops_empty_key_or_value() {
        let empty_key = pv_message(2, PropertyType::Event, "", "Chrome", 1);
        assert!(extract_tuple(&empty_key).is_empty());
        let empty_value = pv_message(2, PropertyType::Event, "$browser", "", 1);
        assert!(extract_tuple(&empty_value).is_empty());
    }

    #[test]
    fn property_value_message_round_trips_producer_wire_format() {
        use crate::producer::Outgoing;
        for (pt, expected) in [
            (PropertyType::Event, "event"),
            (PropertyType::Person, "person"),
            (PropertyType::Group(0), "group_0"),
            (PropertyType::Group(7), "group_7"),
        ] {
            let outgoing = Outgoing {
                team_id: 2,
                property_type: pt,
                property_key: "$browser",
                property_value: "Chrome",
                property_count: 99,
            };
            let serialized = serde_json::to_string(&outgoing).unwrap();
            assert!(
                serialized.contains(&format!(r#""property_type":"{expected}""#)),
                "expected {expected} in {serialized}"
            );
            let parsed: PropertyValueMessage = serde_json::from_str(&serialized).unwrap();
            assert_eq!(parsed.team_id, 2);
            assert_eq!(parsed.property_type, pt);
            assert_eq!(parsed.property_key, "$browser");
            assert_eq!(parsed.property_value, "Chrome");
            assert_eq!(parsed.property_count, 99);
        }
    }
}
