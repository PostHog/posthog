use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use serde_json::Value;

/// Events that should never trigger person property updates because
/// there is no ordering guarantee across them with other person updates.
static NO_PERSON_UPDATE_EVENTS: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| HashSet::from(["$exception", "$$heatmap"]));

/// The result of computing property diffs from an event.
#[derive(Debug, Clone)]
pub struct PropertyUpdates {
    pub to_set: HashMap<String, Value>,
    pub to_unset: Vec<String>,
    pub has_changes: bool,
}

/// Compute property changes from event data without modifying the existing person properties.
///
/// This mirrors the TypeScript `computeEventPropertyUpdates` in `person-update.ts`,
/// but simplified for the PoC by omitting the property filtering logic
/// (FILTERED_PERSON_UPDATE_PROPERTIES).
pub fn compute_event_property_updates(
    event_name: &str,
    set_properties: &Value,
    set_once_properties: &Value,
    unset_properties: &[String],
    person_properties: &Value,
) -> PropertyUpdates {
    if NO_PERSON_UPDATE_EVENTS.contains(event_name) {
        return PropertyUpdates {
            has_changes: false,
            to_set: HashMap::new(),
            to_unset: Vec::new(),
        };
    }

    let person_props = person_properties.as_object();

    let mut has_changes = false;
    let mut to_set = HashMap::new();
    let mut to_unset = Vec::new();

    // Process $set_once: only set if the property doesn't already exist
    if let Some(set_once_map) = set_once_properties.as_object() {
        for (key, value) in set_once_map {
            let existing = person_props.and_then(|p| p.get(key));
            if existing.is_none() {
                has_changes = true;
                to_set.insert(key.clone(), value.clone());
            }
        }
    }

    // Process $set: apply all changed properties
    if let Some(set_map) = set_properties.as_object() {
        for (key, value) in set_map {
            let existing = person_props.and_then(|p| p.get(key));
            if existing != Some(value) {
                has_changes = true;
                to_set.insert(key.clone(), value.clone());
            }
        }
    }

    // Process $unset: remove properties that exist
    for key in unset_properties {
        let exists = person_props.is_some_and(|p| p.contains_key(key));
        if exists {
            has_changes = true;
            to_unset.push(key.clone());
        }
    }

    PropertyUpdates {
        has_changes,
        to_set,
        to_unset,
    }
}

/// Apply computed property updates to a person's properties map.
/// Returns the new properties value and whether any changes were actually made.
pub fn apply_property_updates(
    updates: &PropertyUpdates,
    person_properties: &Value,
) -> (Value, bool) {
    let mut props = match person_properties.as_object() {
        Some(map) => map.clone(),
        None => serde_json::Map::new(),
    };
    let mut updated = false;

    // Apply $set and $set_once
    for (key, value) in &updates.to_set {
        if props.get(key) != Some(value) {
            updated = true;
        }
        props.insert(key.clone(), value.clone());
    }

    // Apply $unset
    for key in &updates.to_unset {
        if props.remove(key).is_some() {
            updated = true;
        }
    }

    (Value::Object(props), updated)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn unsupported_events_return_no_changes() {
        for event in &["$exception", "$$heatmap"] {
            let result = compute_event_property_updates(
                event,
                &json!({"foo": "bar"}),
                &json!({}),
                &[],
                &json!({}),
            );
            assert!(!result.has_changes);
            assert!(result.to_set.is_empty());
            assert!(result.to_unset.is_empty());
        }
    }

    #[test]
    fn set_applies_new_properties() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({"email": "test@example.com", "name": "Test"}),
            &json!({}),
            &[],
            &json!({}),
        );
        assert!(result.has_changes);
        assert_eq!(result.to_set["email"], json!("test@example.com"));
        assert_eq!(result.to_set["name"], json!("Test"));
    }

    #[test]
    fn set_skips_unchanged_properties() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({"email": "test@example.com"}),
            &json!({}),
            &[],
            &json!({"email": "test@example.com"}),
        );
        assert!(!result.has_changes);
        assert!(result.to_set.is_empty());
    }

    #[test]
    fn set_once_only_sets_undefined_properties() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({}),
            &json!({"initial_referrer": "google.com", "email": "new@example.com"}),
            &[],
            &json!({"email": "existing@example.com"}),
        );
        assert!(result.has_changes);
        assert_eq!(result.to_set.len(), 1);
        assert_eq!(result.to_set["initial_referrer"], json!("google.com"));
        // Should NOT overwrite existing email
        assert!(!result.to_set.contains_key("email"));
    }

    #[test]
    fn unset_removes_existing_properties() {
        let result = compute_event_property_updates(
            "$set",
            &json!({}),
            &json!({}),
            &["email".to_string()],
            &json!({"email": "test@example.com", "name": "Test"}),
        );
        assert!(result.has_changes);
        assert_eq!(result.to_unset, vec!["email"]);
    }

    #[test]
    fn unset_ignores_missing_properties() {
        let result = compute_event_property_updates(
            "$set",
            &json!({}),
            &json!({}),
            &["nonexistent".to_string()],
            &json!({"email": "test@example.com"}),
        );
        assert!(!result.has_changes);
        assert!(result.to_unset.is_empty());
    }

    #[test]
    fn combined_set_set_once_unset() {
        let result = compute_event_property_updates(
            "$set",
            &json!({"name": "New Name"}),
            &json!({"initial_source": "organic"}),
            &["old_prop".to_string()],
            &json!({"email": "test@example.com", "old_prop": "value"}),
        );
        assert!(result.has_changes);
        assert_eq!(result.to_set["name"], json!("New Name"));
        assert_eq!(result.to_set["initial_source"], json!("organic"));
        assert_eq!(result.to_unset, vec!["old_prop"]);
    }

    #[test]
    fn apply_updates_sets_properties() {
        let updates = PropertyUpdates {
            to_set: HashMap::from([
                ("email".to_string(), json!("new@example.com")),
                ("name".to_string(), json!("New Name")),
            ]),
            to_unset: vec![],
            has_changes: true,
        };

        let (result, updated) =
            apply_property_updates(&updates, &json!({"email": "old@example.com"}));

        assert!(updated);
        assert_eq!(result["email"], json!("new@example.com"));
        assert_eq!(result["name"], json!("New Name"));
    }

    #[test]
    fn apply_updates_unsets_properties() {
        let updates = PropertyUpdates {
            to_set: HashMap::new(),
            to_unset: vec!["email".to_string()],
            has_changes: true,
        };

        let (result, updated) = apply_property_updates(
            &updates,
            &json!({"email": "test@example.com", "name": "Test"}),
        );

        assert!(updated);
        assert!(result.get("email").is_none());
        assert_eq!(result["name"], json!("Test"));
    }

    #[test]
    fn apply_updates_no_changes() {
        let updates = PropertyUpdates {
            to_set: HashMap::from([("email".to_string(), json!("same@example.com"))]),
            to_unset: vec![],
            has_changes: true,
        };

        let (result, updated) =
            apply_property_updates(&updates, &json!({"email": "same@example.com"}));

        assert!(!updated);
        assert_eq!(result["email"], json!("same@example.com"));
    }
}
