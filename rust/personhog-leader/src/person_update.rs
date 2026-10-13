use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use serde_json::Value;

/// Events that should never trigger person property updates because
/// there is no ordering guarantee across them with other person updates.
static NO_PERSON_UPDATE_EVENTS: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| HashSet::from(["$exception", "$$heatmap"]));

/// Properties that change too often to be worth a person update on their
/// own. Copied from FILTERED_PERSON_UPDATE_PROPERTIES in
/// nodejs/src/common/persons/person-property-utils.ts, which links back;
/// the two lists must stay identical while both backends run.
static FILTERED_PERSON_UPDATE_PROPERTIES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    HashSet::from([
        "$current_url",
        "$pathname",
        "$referring_domain",
        "$referrer",
        "$screen_height",
        "$screen_width",
        "$viewport_height",
        "$viewport_width",
        "$browser",
        "$browser_version",
        "$device_type",
        "$raw_user_agent",
        "$os",
        "$os_name",
        "$os_version",
        "$geoip_postal_code",
        "$geoip_time_zone",
        "$geoip_latitude",
        "$geoip_longitude",
        "$geoip_accuracy_radius",
        "$geoip_subdivision_1_code",
        "$geoip_subdivision_1_name",
        "$geoip_subdivision_2_code",
        "$geoip_subdivision_2_name",
        "$geoip_subdivision_3_code",
        "$geoip_subdivision_3_name",
        "$geoip_city_confidence",
        "$geoip_country_confidence",
        "$geoip_postal_code_confidence",
        "$geoip_subdivision_1_confidence",
        "$geoip_subdivision_2_confidence",
    ])
});

/// The result of computing property diffs from an event.
#[derive(Debug, Clone)]
pub struct PropertyUpdates {
    pub to_set: HashMap<String, Value>,
    pub to_unset: Vec<String>,
    pub has_changes: bool,
    /// Whether any change warrants a write on its own: a new `$set` key,
    /// an unset, a non-filtered value change, or anything under force.
    /// False with `has_changes` true is the filtered-only shape.
    pub has_non_filtered_changes: bool,
}

/// Compute property changes from event data without modifying the existing person properties.
///
/// Mirrors the TypeScript `refineEventOps`, filtered-property promotion
/// included: the classification must be byte-identical across backends
/// or shadow comparison reads the drift as divergence.
pub fn compute_event_property_updates(
    event_name: &str,
    set_properties: &Value,
    set_once_properties: &Value,
    unset_properties: &[String],
    person_properties: &Value,
    force_update: bool,
) -> PropertyUpdates {
    if NO_PERSON_UPDATE_EVENTS.contains(event_name) {
        return PropertyUpdates {
            has_changes: false,
            to_set: HashMap::new(),
            to_unset: Vec::new(),
            has_non_filtered_changes: false,
        };
    }
    let promotes = |key: &str| force_update || !FILTERED_PERSON_UPDATE_PROPERTIES.contains(key);

    let person_props = person_properties.as_object();

    let mut has_changes = false;
    let mut has_non_filtered_changes = false;
    let mut to_set = HashMap::new();
    let mut to_unset = Vec::new();

    // $set_once fills absent keys; a new filtered key does not promote
    // on its own, as in the TS reference.
    if let Some(set_once_map) = set_once_properties.as_object() {
        for (key, value) in set_once_map {
            let existing = person_props.and_then(|p| p.get(key));
            if existing.is_none() {
                has_changes = true;
                if promotes(key) {
                    has_non_filtered_changes = true;
                }
                to_set.insert(key.clone(), value.clone());
            }
        }
    }

    // $set, two passes: if any changed key promotes (a new key always
    // does, filtered or not), every changed key rides along.
    let mut set_changes: Vec<(&String, &Value)> = Vec::new();
    let mut any_set_promotes = false;
    if let Some(set_map) = set_properties.as_object() {
        for (key, value) in set_map {
            let existing = person_props.and_then(|p| p.get(key));
            if existing != Some(value) {
                if existing.is_none() || promotes(key) {
                    any_set_promotes = true;
                }
                set_changes.push((key, value));
            }
        }
    }
    for (key, value) in set_changes {
        has_changes = true;
        if any_set_promotes {
            has_non_filtered_changes = true;
        }
        to_set.insert(key.clone(), value.clone());
    }

    // An unset of a present key always warrants the write.
    for key in unset_properties {
        let exists = person_props.is_some_and(|p| p.contains_key(key));
        if exists {
            has_changes = true;
            has_non_filtered_changes = true;
            to_unset.push(key.clone());
        }
    }

    PropertyUpdates {
        has_changes,
        to_set,
        to_unset,
        has_non_filtered_changes,
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
                false,
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
            false,
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
            false,
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
            false,
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
            false,
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
            false,
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
            false,
        );
        assert!(result.has_changes);
        assert_eq!(result.to_set["name"], json!("New Name"));
        assert_eq!(result.to_set["initial_source"], json!("organic"));
        assert_eq!(result.to_unset, vec!["old_prop"]);
    }

    #[test]
    fn set_wins_over_set_once_for_the_same_key() {
        let result = compute_event_property_updates(
            "$set",
            &json!({"plan": "pro"}),
            &json!({"plan": "free"}),
            &[],
            &json!({}),
            false,
        );
        assert!(result.has_changes);
        assert_eq!(
            result.to_set["plan"],
            json!("pro"),
            "the request contract: when a key appears in both set and set_once, set wins"
        );
    }

    #[test]
    fn filtered_only_changes_do_not_warrant_a_write() {
        // All changes filtered: the caller answers updated=false and discards.
        let result = compute_event_property_updates(
            "$pageview",
            &json!({"$current_url": "https://example.com/b", "$browser": "Firefox"}),
            &json!({}),
            &[],
            &json!({"$current_url": "https://example.com/a", "$browser": "Chrome"}),
            false,
        );
        assert!(result.has_changes);
        assert!(!result.has_non_filtered_changes);
    }

    #[test]
    fn one_real_change_promotes_the_filtered_values_with_it() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({"plan": "pro", "$current_url": "https://example.com/b"}),
            &json!({}),
            &[],
            &json!({"plan": "free", "$current_url": "https://example.com/a"}),
            false,
        );
        assert!(result.has_non_filtered_changes);
        assert_eq!(
            result.to_set["$current_url"],
            json!("https://example.com/b")
        );
    }

    #[test]
    fn a_new_set_key_promotes_even_when_filtered() {
        // A never-seen key is worth writing even when filtered, $set only.
        let result = compute_event_property_updates(
            "$pageview",
            &json!({"$browser": "Chrome"}),
            &json!({}),
            &[],
            &json!({}),
            false,
        );
        assert!(result.has_non_filtered_changes);
    }

    #[test]
    fn a_new_set_once_filtered_key_fills_without_promoting() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({}),
            &json!({"$browser": "Chrome"}),
            &[],
            &json!({}),
            false,
        );
        assert!(result.has_changes);
        assert!(!result.has_non_filtered_changes);
        assert_eq!(result.to_set["$browser"], json!("Chrome"));
    }

    #[test]
    fn an_unset_of_a_filtered_key_always_promotes() {
        let result = compute_event_property_updates(
            "$pageview",
            &json!({}),
            &json!({}),
            &["$browser".to_string()],
            &json!({"$browser": "Chrome"}),
            false,
        );
        assert!(result.has_non_filtered_changes);
    }

    #[test]
    fn force_promotes_filtered_only_changes() {
        let result = compute_event_property_updates(
            "$identify",
            &json!({"$current_url": "https://example.com/b"}),
            &json!({}),
            &[],
            &json!({"$current_url": "https://example.com/a"}),
            true,
        );
        assert!(result.has_non_filtered_changes);
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
            has_non_filtered_changes: true,
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
            has_non_filtered_changes: true,
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
            has_non_filtered_changes: true,
        };

        let (result, updated) =
            apply_property_updates(&updates, &json!({"email": "same@example.com"}));

        assert!(!updated);
        assert_eq!(result["email"], json!("same@example.com"));
    }
}
