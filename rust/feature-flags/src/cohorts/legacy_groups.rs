//! Converts a cohort's deprecated `groups` definition into the `filters` shape the
//! evaluator understands.
//!
//! `groups` predates `filters` and is still the only audience definition a large number of
//! dynamic cohorts have. Everything else in the product reads it through
//! `Cohort.properties` in products/cohorts/backend/models/cohort.py, which converts
//! `groups` to the same property tree `filters` holds. This module is the Rust half of
//! that conversion, so a cohort condition on a flag matches the same people the cohort's
//! own member list contains.

use serde_json::{json, Map, Value};

/// The `type` of a leaf that no supported `PropertyType` covers, so the evaluator treats
/// it as an unsupported filter: it contributes no cohort dependency and is a non-match.
///
/// A group that names neither properties nor an event is unconvertible. Python turns it
/// into an empty AND group, which matches every person in ClickHouse, so mirroring Python
/// exactly here would turn an unreadable definition into "everyone" during flag
/// evaluation. A non-match is the safe reading of a definition we cannot resolve.
const UNSUPPORTED_LEAF_TYPE: &str = "unsupported_legacy_cohort_group";

/// Builds the `filters` tree a legacy `groups` definition stands for, or `None` when
/// `groups` holds no definition to convert.
///
/// Groups combine with OR, and the properties inside one group combine with AND, which is
/// what `Cohort.properties` produces on the Python side.
pub fn filters_from_legacy_groups(groups: &Value) -> Option<Value> {
    let groups = groups.as_array()?;
    if groups.is_empty() {
        return None;
    }

    let values: Vec<Value> = groups.iter().map(group_to_filter_node).collect();
    Some(json!({"properties": {"type": "OR", "values": values}}))
}

fn group_to_filter_node(group: &Value) -> Value {
    let Some(group) = group.as_object() else {
        return unsupported_leaf();
    };

    match group.get("properties") {
        Some(Value::Array(properties)) if !properties.is_empty() => {
            let values: Vec<Value> = properties.iter().map(person_typed_property).collect();
            json!({"type": "AND", "values": values})
        }
        // A property group that already carries its own AND/OR structure, which the
        // evaluator reads as-is. Both keys are required, the same test `_parse_data` in
        // posthog/models/filters/mixins/property.py applies before it parses a group.
        Some(Value::Object(properties))
            if properties.contains_key("type") && properties.contains_key("values") =>
        {
            Value::Object(properties.clone())
        }
        // The oldest shape on record: a plain `{"key": "value"}` map of implicit
        // person-property equality checks. An object carrying `type` or `values` is
        // excluded, because Python reads a partial group like `{"type": "OR"}` as an event
        // property named `type` rather than a person property. This evaluator cannot
        // resolve event properties, so such a group falls through to a non-match instead
        // of comparing a person's own `type` property against the group's structure.
        Some(Value::Object(properties))
            if !properties.is_empty()
                && !properties.contains_key("type")
                && !properties.contains_key("values") =>
        {
            let values: Vec<Value> = properties
                .iter()
                .map(|(key, value)| json!({"key": key, "value": value, "type": "person"}))
                .collect();
            json!({"type": "AND", "values": values})
        }
        _ => event_group_to_filter_node(group),
    }
}

/// A group that counts an action or an event over a time window. The evaluator has no
/// event history, so this becomes an unsupported leaf, the same non-match a `behavioral`
/// leaf inside `filters` produces.
fn event_group_to_filter_node(group: &Map<String, Value>) -> Value {
    let key = group.get("action_id").or_else(|| group.get("event_id"));
    match key {
        Some(key) if !key.is_null() => json!({"type": "behavioral", "key": key}),
        _ => unsupported_leaf(),
    }
}

/// Applies the same type correction `Cohort.properties` does: a legacy property with no
/// `type`, or the `event` type that old cohort writes stored by mistake, is a person
/// property.
fn person_typed_property(property: &Value) -> Value {
    let Some(property) = property.as_object() else {
        return property.clone();
    };

    let needs_person_type = match property.get("type") {
        None | Some(Value::Null) => true,
        Some(Value::String(prop_type)) => prop_type == "event",
        Some(_) => false,
    };

    if !needs_person_type {
        return Value::Object(property.clone());
    }

    let mut property = property.clone();
    property.insert("type".to_string(), json!("person"));
    Value::Object(property)
}

fn unsupported_leaf() -> Value {
    json!({"type": UNSUPPORTED_LEAF_TYPE})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_no_filters_to_convert() {
        for groups in [json!([]), json!({}), json!(null)] {
            assert_eq!(filters_from_legacy_groups(&groups), None, "groups={groups}");
        }
    }

    #[test]
    fn test_property_list_group_becomes_an_and_group() {
        let groups = json!([{
            "properties": [
                {"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"},
                {"key": "plan", "value": "pro", "operator": "exact"}
            ]
        }]);

        assert_eq!(
            filters_from_legacy_groups(&groups).unwrap(),
            json!({"properties": {"type": "OR", "values": [{
                "type": "AND",
                "values": [
                    {"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"},
                    // No `type` in storage means a person property.
                    {"key": "plan", "value": "pro", "operator": "exact", "type": "person"}
                ]
            }]}})
        );
    }

    #[test]
    fn test_event_typed_property_is_read_as_a_person_property() {
        let groups =
            json!([{"properties": [{"key": "email", "value": "a@example.com", "type": "event"}]}]);

        assert_eq!(
            filters_from_legacy_groups(&groups).unwrap(),
            json!({"properties": {"type": "OR", "values": [{
                "type": "AND",
                "values": [{"key": "email", "value": "a@example.com", "type": "person"}]
            }]}})
        );
    }

    #[test]
    fn test_key_value_map_group_becomes_person_property_leaves() {
        let groups = json!([{"properties": {"plan": "pro"}}]);

        assert_eq!(
            filters_from_legacy_groups(&groups).unwrap(),
            json!({"properties": {"type": "OR", "values": [{
                "type": "AND",
                "values": [{"key": "plan", "value": "pro", "type": "person"}]
            }]}})
        );
    }

    #[test]
    fn test_nested_property_group_is_kept_as_written() {
        let nested = json!({
            "type": "OR",
            "values": [{"key": "plan", "value": "pro", "type": "person", "operator": "exact"}]
        });
        let groups = json!([{"properties": nested}]);

        assert_eq!(
            filters_from_legacy_groups(&groups).unwrap(),
            json!({"properties": {"type": "OR", "values": [nested]}})
        );
    }

    #[test]
    fn test_event_and_unconvertible_groups_become_unsupported_leaves() {
        // The last two groups are partial structural groups. Python reads each as an event
        // property named after the key it carries, which this evaluator cannot resolve, so
        // neither may become a person property compared against the group's structure.
        let groups = json!([
            {"action_id": 7, "days": 30, "count": 1},
            {"event_id": "$pageview", "days": 7},
            {"name": "a group that defines no audience"},
            {"properties": {"type": "OR"}},
            {"properties": {"values": [{"key": "plan", "value": "pro", "type": "person"}]}}
        ]);

        assert_eq!(
            filters_from_legacy_groups(&groups).unwrap(),
            json!({"properties": {"type": "OR", "values": [
                {"type": "behavioral", "key": 7},
                {"type": "behavioral", "key": "$pageview"},
                {"type": UNSUPPORTED_LEAF_TYPE},
                {"type": UNSUPPORTED_LEAF_TYPE},
                {"type": UNSUPPORTED_LEAF_TYPE}
            ]}})
        );
    }
}
