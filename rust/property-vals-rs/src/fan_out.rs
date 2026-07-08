use serde_json::Value;

use crate::config::{ExcludedPropertyKeys, LengthCaps};
use crate::metrics_consts::VALUES_DROPPED;
use crate::types::{Event, GroupIdentify, PropertyType, PropertyValueMessage, TupleKey};

pub fn fan_out(
    event: &Event,
    excluded: &ExcludedPropertyKeys,
    caps: LengthCaps,
) -> Vec<(TupleKey, u64)> {
    let mut out = Vec::new();

    if let Some(raw) = &event.properties {
        emit_from_blob(
            event.team_id,
            PropertyType::Event,
            raw,
            excluded,
            caps,
            &mut out,
        );
    }
    if let Some(raw) = &event.person_properties {
        emit_from_blob(
            event.team_id,
            PropertyType::Person,
            raw,
            excluded,
            caps,
            &mut out,
        );
    }

    out
}

pub fn fan_out_group(
    event: &GroupIdentify,
    excluded: &ExcludedPropertyKeys,
    caps: LengthCaps,
) -> Vec<(TupleKey, u64)> {
    let mut out = Vec::new();
    if let Some(raw) = &event.group_properties {
        emit_from_blob(
            event.team_id,
            PropertyType::Group(event.group_type_index),
            raw,
            excluded,
            caps,
            &mut out,
        );
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
    caps: LengthCaps,
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
        if key.chars().count() > caps.max_property_key_len {
            metrics::counter!(VALUES_DROPPED, "reason" => "key_too_long").increment(1);
            continue;
        }
        if property_value.is_empty() {
            metrics::counter!(VALUES_DROPPED, "reason" => "empty_value").increment(1);
            continue;
        }
        if property_value.chars().count() > caps.max_property_value_len {
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

    const TEST_CAPS: LengthCaps = LengthCaps {
        max_property_key_len: 400,
        max_property_value_len: 255,
    };

    fn event(properties: &str) -> Event {
        Event {
            team_id: 2,
            properties: Some(properties.to_string()),
            person_properties: None,
        }
    }

    fn group_identify(group_type_index: u8, properties: &str) -> GroupIdentify {
        GroupIdentify {
            team_id: 2,
            group_type_index,
            group_properties: Some(properties.to_string()),
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
            person_properties in prop::option::of(arb_blob()),
        ) -> Event {
            Event { team_id, properties, person_properties }
        }
    }

    prop_compose! {
        fn arb_group_identify()(
            team_id: i64,
            group_type_index: u8,
            group_properties in prop::option::of(arb_blob()),
        ) -> GroupIdentify {
            GroupIdentify { team_id, group_type_index, group_properties }
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
        assert!(t.property_key.chars().count() <= TEST_CAPS.max_property_key_len);
        assert!(t.property_value.chars().count() <= TEST_CAPS.max_property_value_len);
        assert_eq!(count, 1, "stage-1 fan-out always emits count=1");
    }

    proptest! {
        #[test]
        fn fan_out_outputs_obey_caps_and_team(e in arb_event()) {
            for (t, n) in fan_out(&e, &none(), TEST_CAPS) {
                check_tuple_invariants(&t, n, e.team_id);
            }
        }

        #[test]
        fn fan_out_group_outputs_obey_caps_and_team(g in arb_group_identify()) {
            for (t, n) in fan_out_group(&g, &none(), TEST_CAPS) {
                check_tuple_invariants(&t, n, g.team_id);
            }
        }

        #[test]
        fn fan_out_is_pure(e in arb_event()) {
            prop_assert_eq!(
                fan_out(&e, &none(), TEST_CAPS),
                fan_out(&e, &none(), TEST_CAPS)
            );
        }

        #[test]
        fn fan_out_group_is_pure(g in arb_group_identify()) {
            prop_assert_eq!(fan_out_group(&g, &none(), TEST_CAPS), fan_out_group(&g, &none(), TEST_CAPS));
        }

        #[test]
        fn fan_out_group_property_type_matches_index(g in arb_group_identify()) {
            for (t, _) in fan_out_group(&g, &none(), TEST_CAPS) {
                prop_assert_eq!(t.property_type, PropertyType::Group(g.group_type_index));
            }
        }

    }

    #[test]
    fn event_property_produces_event_type_tuple() {
        let tuples = fan_out(&event(r#"{"$browser":"Chrome"}"#), &none(), TEST_CAPS);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_type, PropertyType::Event);
        assert_eq!(tuples[0].0.property_key, "$browser");
        assert_eq!(tuples[0].0.property_value, "Chrome");
        assert_eq!(tuples[0].1, 1);
    }

    #[test]
    fn json_null_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"nullable_field":null}"#), &none(), TEST_CAPS);
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_string_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"blank":""}"#), &none(), TEST_CAPS);
        assert!(tuples.is_empty());
    }

    #[test]
    fn value_length_cap_is_configurable() {
        for (value_len, cap, expected_kept) in [
            (255usize, 255usize, true),
            (256, 255, false),
            (256, 300, true),
            (301, 300, false),
        ] {
            let caps = LengthCaps {
                max_property_value_len: cap,
                ..TEST_CAPS
            };
            let blob = format!(r#"{{"k":"{}"}}"#, "a".repeat(value_len));
            let kept = !fan_out(&event(&blob), &none(), caps).is_empty();
            assert_eq!(
                kept, expected_kept,
                "{value_len}-char value at cap {cap}: expected kept={expected_kept}"
            );
        }
    }

    #[test]
    fn key_length_cap_is_configurable() {
        for (key_len, cap, expected_kept) in [
            (400usize, 400usize, true),
            (401, 400, false),
            (401, 450, true),
            (451, 450, false),
        ] {
            let caps = LengthCaps {
                max_property_key_len: cap,
                ..TEST_CAPS
            };
            let blob = format!(r#"{{"{}":"v"}}"#, "k".repeat(key_len));
            let kept = !fan_out(&event(&blob), &none(), caps).is_empty();
            assert_eq!(
                kept, expected_kept,
                "{key_len}-char key at cap {cap}: expected kept={expected_kept}"
            );
        }
    }

    #[test]
    fn person_properties_emit_person_type() {
        let ev = Event {
            team_id: 2,
            properties: None,
            person_properties: Some(r#"{"email":"foo@bar.com"}"#.to_string()),
        };
        let tuples = fan_out(&ev, &none(), TEST_CAPS);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_type, PropertyType::Person);
        assert_eq!(tuples[0].0.property_key, "email");
        assert_eq!(tuples[0].0.property_value, "foo@bar.com");
    }

    #[test]
    fn bool_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_bool":true}"#), &none(), TEST_CAPS);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_value, "true");
    }

    #[test]
    fn number_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_number":42}"#), &none(), TEST_CAPS);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_value, "42");
    }

    #[test]
    fn unparseable_blob_emits_nothing() {
        let tuples = fan_out(&event(r#"not valid json"#), &none(), TEST_CAPS);
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_object_emits_nothing() {
        let tuples = fan_out(&event("{}"), &none(), TEST_CAPS);
        assert!(tuples.is_empty());
    }

    #[test]
    fn group_identify_index_0_emits_group_type() {
        let tuples = fan_out_group(
            &group_identify(0, r#"{"plan":"enterprise"}"#),
            &none(),
            TEST_CAPS,
        );
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_type, PropertyType::Group(0));
        assert_eq!(tuples[0].0.property_key, "plan");
        assert_eq!(tuples[0].0.property_value, "enterprise");
    }

    #[test]
    fn group_identify_emits_group_type_matching_index() {
        let tuples = fan_out_group(
            &group_identify(4, r#"{"region":"us-east"}"#),
            &none(),
            TEST_CAPS,
        );
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_type, PropertyType::Group(4));
    }

    #[test]
    fn group_identify_missing_properties_drops() {
        let g = GroupIdentify {
            team_id: 2,
            group_type_index: 0,
            group_properties: None,
        };
        assert!(fan_out_group(&g, &none(), TEST_CAPS).is_empty());
    }

    #[test]
    fn group_identify_unparseable_drops() {
        let tuples = fan_out_group(&group_identify(0, "not valid json"), &none(), TEST_CAPS);
        assert!(tuples.is_empty());
    }

    #[test]
    fn excluded_event_property_keys_are_skipped() {
        let blob =
            r#"{"$insert_id":"abc-123","$browser":"Chrome","distinct_id":"u1","$session_id":"s1"}"#;
        let exclusions = excluded(&["$insert_id", "distinct_id", "$session_id"]);
        let tuples = fan_out(&event(blob), &exclusions, TEST_CAPS);
        assert_eq!(tuples.len(), 1, "only $browser should survive exclusion");
        assert_eq!(tuples[0].0.property_key, "$browser");
        assert_eq!(tuples[0].0.property_value, "Chrome");
    }

    #[test]
    fn excluded_person_property_keys_are_skipped() {
        let ev = Event {
            team_id: 2,
            properties: None,
            person_properties: Some(
                r#"{"email":"a@b.com","$session_id":"s1","plan":"enterprise"}"#.to_string(),
            ),
        };
        let tuples = fan_out(&ev, &excluded(&["$session_id"]), TEST_CAPS);
        assert_eq!(tuples.len(), 2);
        let keys: Vec<&str> = tuples
            .iter()
            .map(|(t, _)| t.property_key.as_str())
            .collect();
        assert!(keys.contains(&"email"));
        assert!(keys.contains(&"plan"));
        assert!(!keys.contains(&"$session_id"));
    }

    #[test]
    fn excluded_group_property_keys_are_skipped() {
        let g = group_identify(0, r#"{"plan":"enterprise","internal_id":"g-42"}"#);
        let tuples = fan_out_group(&g, &excluded(&["internal_id"]), TEST_CAPS);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].0.property_key, "plan");
    }

    #[test]
    fn empty_exclusion_list_is_a_noop() {
        let blob = r#"{"$browser":"Chrome","email":"a@b.com"}"#;
        let with_default = fan_out(&event(blob), &none(), TEST_CAPS);
        let parsed_empty: ExcludedPropertyKeys = "".parse().unwrap();
        let with_parsed_empty = fan_out(&event(blob), &parsed_empty, TEST_CAPS);
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
