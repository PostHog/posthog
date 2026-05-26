use serde_json::Value;

use crate::types::{Event, GroupIdentify, PropertyType, TupleKey};

pub const MAX_PROPERTY_KEY_LEN: usize = 400;
pub const MAX_PROPERTY_VALUE_LEN: usize = 255;

pub fn fan_out(event: &Event) -> Vec<TupleKey> {
    let mut out = Vec::new();

    if let Some(raw) = &event.properties {
        emit_from_blob(event.team_id, PropertyType::Event, raw, &mut out);
    }
    if let Some(raw) = &event.person_properties {
        emit_from_blob(event.team_id, PropertyType::Person, raw, &mut out);
    }

    out
}

pub fn fan_out_group(event: &GroupIdentify) -> Vec<TupleKey> {
    let mut out = Vec::new();
    if let Some(raw) = &event.group_properties {
        emit_from_blob(
            event.team_id,
            PropertyType::Group(event.group_type_index),
            raw,
            &mut out,
        );
    }
    out
}

fn emit_from_blob(team_id: i64, property_type: PropertyType, raw: &str, out: &mut Vec<TupleKey>) {
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
            continue;
        }

        let property_value = coerce_to_string(value);

        if key.is_empty() || key.chars().count() > MAX_PROPERTY_KEY_LEN {
            continue;
        }
        if property_value.is_empty() || property_value.chars().count() > MAX_PROPERTY_VALUE_LEN {
            continue;
        }

        out.push(TupleKey {
            team_id,
            property_type,
            property_key: key.clone(),
            property_value,
        });
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

    fn check_tuple_invariants(t: &TupleKey, expected_team: i64) {
        assert_eq!(t.team_id, expected_team);
        assert!(!t.property_key.is_empty());
        assert!(!t.property_value.is_empty());
        assert!(t.property_key.chars().count() <= MAX_PROPERTY_KEY_LEN);
        assert!(t.property_value.chars().count() <= MAX_PROPERTY_VALUE_LEN);
    }

    proptest! {
        #[test]
        fn fan_out_outputs_obey_caps_and_team(e in arb_event()) {
            for t in fan_out(&e) {
                check_tuple_invariants(&t, e.team_id);
            }
        }

        #[test]
        fn fan_out_group_outputs_obey_caps_and_team(g in arb_group_identify()) {
            for t in fan_out_group(&g) {
                check_tuple_invariants(&t, g.team_id);
            }
        }

        #[test]
        fn fan_out_is_pure(e in arb_event()) {
            prop_assert_eq!(fan_out(&e), fan_out(&e));
        }

        #[test]
        fn fan_out_group_is_pure(g in arb_group_identify()) {
            prop_assert_eq!(fan_out_group(&g), fan_out_group(&g));
        }

        #[test]
        fn fan_out_group_property_type_matches_index(g in arb_group_identify()) {
            for t in fan_out_group(&g) {
                prop_assert_eq!(t.property_type, PropertyType::Group(g.group_type_index));
            }
        }
    }

    #[test]
    fn event_property_produces_event_type_tuple() {
        let tuples = fan_out(&event(r#"{"$browser":"Chrome"}"#));
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_type, PropertyType::Event);
        assert_eq!(tuples[0].property_key, "$browser");
        assert_eq!(tuples[0].property_value, "Chrome");
    }

    #[test]
    fn json_null_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"nullable_field":null}"#));
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_string_value_is_dropped() {
        let tuples = fan_out(&event(r#"{"blank":""}"#));
        assert!(tuples.is_empty());
    }

    #[test]
    fn person_properties_emit_person_type() {
        let ev = Event {
            team_id: 2,
            properties: None,
            person_properties: Some(r#"{"email":"foo@bar.com"}"#.to_string()),
        };
        let tuples = fan_out(&ev);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_type, PropertyType::Person);
        assert_eq!(tuples[0].property_key, "email");
        assert_eq!(tuples[0].property_value, "foo@bar.com");
    }

    #[test]
    fn bool_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_bool":true}"#));
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_value, "true");
    }

    #[test]
    fn number_value_coerces_to_string() {
        let tuples = fan_out(&event(r#"{"a_number":42}"#));
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_value, "42");
    }

    #[test]
    fn unparseable_blob_emits_nothing() {
        let tuples = fan_out(&event(r#"not valid json"#));
        assert!(tuples.is_empty());
    }

    #[test]
    fn empty_object_emits_nothing() {
        let tuples = fan_out(&event("{}"));
        assert!(tuples.is_empty());
    }

    #[test]
    fn group_identify_index_0_emits_group_type() {
        let tuples = fan_out_group(&group_identify(0, r#"{"plan":"enterprise"}"#));
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_type, PropertyType::Group(0));
        assert_eq!(tuples[0].property_key, "plan");
        assert_eq!(tuples[0].property_value, "enterprise");
    }

    #[test]
    fn group_identify_emits_group_type_matching_index() {
        let tuples = fan_out_group(&group_identify(4, r#"{"region":"us-east"}"#));
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].property_type, PropertyType::Group(4));
    }

    #[test]
    fn group_identify_missing_properties_drops() {
        let g = GroupIdentify {
            team_id: 2,
            group_type_index: 0,
            group_properties: None,
        };
        assert!(fan_out_group(&g).is_empty());
    }

    #[test]
    fn group_identify_unparseable_drops() {
        let tuples = fan_out_group(&group_identify(0, "not valid json"));
        assert!(tuples.is_empty());
    }
}
