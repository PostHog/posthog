use std::collections::HashSet;
use std::sync::LazyLock;

use metrics::counter;
use tracing::debug;

/// Properties that must never be trimmed, matching the Node.js ingestion
/// pipeline's `ALL_PROTECTED_PROPERTIES` in `person-property-utils.ts`.
static PROTECTED_PROPERTIES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    HashSet::from([
        // Core person properties
        "email",
        "name",
        // Event-to-person properties (mobile)
        "$app_build",
        "$app_name",
        "$app_namespace",
        "$app_version",
        // Event-to-person properties (web)
        "$browser",
        "$browser_version",
        "$device_type",
        "$current_url",
        "$pathname",
        "$os",
        "$os_name",
        "$os_version",
        "$referring_domain",
        "$referrer",
        "$screen_height",
        "$screen_width",
        "$viewport_height",
        "$viewport_width",
        "$raw_user_agent",
        // UTM and campaign tracking
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_name",
        "utm_term",
        "gclid",
        "gad_source",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "twclid",
        "li_fat_id",
        "mc_cid",
        "igshid",
        "ttclid",
        "rdt_cid",
        "irclid",
        "_kx",
        "epik",
        "qclid",
        "sccid",
        // Session and page tracking
        "$session_id",
        "$window_id",
        "$pageview_id",
        "$host",
        // Identity and device tracking
        "$user_id",
        "$device_id",
        "$anon_distinct_id",
        // Initial/first-touch properties
        "$initial_referrer",
        "$initial_referring_domain",
        "$initial_utm_source",
        "$initial_utm_medium",
        "$initial_utm_campaign",
        "$initial_utm_content",
        "$initial_utm_term",
    ])
});

/// Returns true if the property can be trimmed (is not protected).
pub fn can_trim_property(name: &str) -> bool {
    !PROTECTED_PROPERTIES.contains(name)
}

/// Trim person properties to fit within the target size by removing
/// non-protected properties in alphabetical order.
///
/// Matches the Node.js `trimPropertiesToFitSize` algorithm:
/// 1. Sort all property keys alphabetically
/// 2. For each trimmable property, delete it and recalculate size
/// 3. Stop when under target size
///
/// Returns the trimmed properties and whether any trimming occurred.
pub fn trim_properties_to_fit_size(
    properties: &serde_json::Value,
    team_id: i64,
    person_id: i64,
    target_bytes: usize,
) -> Option<serde_json::Value> {
    let map = properties.as_object()?;

    let json_str = serde_json::to_string(properties).ok()?;
    let current_size = json_str.len();

    if current_size <= target_bytes {
        return None; // Already fits, no trimming needed
    }

    let mut trimmed = map.clone();
    let mut keys: Vec<&String> = map.keys().collect();
    keys.sort();

    let mut removed_count = 0;

    for key in keys {
        if !can_trim_property(key) {
            continue;
        }

        trimmed.remove(key.as_str());
        removed_count += 1;

        let new_size = serde_json::to_string(&trimmed)
            .map(|s| s.len())
            .unwrap_or(current_size);

        if new_size <= target_bytes {
            break;
        }
    }

    let final_size = serde_json::to_string(&trimmed)
        .map(|s| s.len())
        .unwrap_or(0);

    // If trimmable keys were exhausted and the result still exceeds the
    // target, the person can't fit — typically means protected properties
    // alone are oversized. Signal this as `None` so the caller skips without
    // attempting another doomed PG write.
    if final_size > target_bytes {
        debug!(
            team_id,
            person_id,
            original_size = current_size,
            final_size,
            target_size = target_bytes,
            properties_removed = removed_count,
            final_property_count = trimmed.len(),
            "person properties still exceed target after trimming all trimmable keys; giving up"
        );
        return None;
    }

    debug!(
        team_id,
        person_id,
        original_size = current_size,
        final_size,
        target_size = target_bytes,
        properties_removed = removed_count,
        final_property_count = trimmed.len(),
        "trimmed person properties to fit size"
    );

    counter!("personhog_writer_properties_trimmed_total").increment(1);

    Some(serde_json::Value::Object(trimmed))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn protected_properties_are_not_trimmable() {
        assert!(!can_trim_property("email"));
        assert!(!can_trim_property("$browser"));
        assert!(!can_trim_property("utm_source"));
        assert!(!can_trim_property("$user_id"));
        assert!(!can_trim_property("$initial_referrer"));
    }

    #[test]
    fn custom_properties_are_trimmable() {
        assert!(can_trim_property("custom_field"));
        assert!(can_trim_property("my_property"));
        assert!(can_trim_property("some_random_key"));
    }

    #[test]
    fn trim_returns_none_when_already_fits() {
        let props = json!({"email": "test@example.com", "name": "Test"});
        assert!(trim_properties_to_fit_size(&props, 1, 1, 1024).is_none());
    }

    #[test]
    fn trim_removes_custom_properties_alphabetically() {
        // Small target so the test runs with small data.
        let target = 1024;
        let mut map = serde_json::Map::new();
        map.insert("email".to_string(), json!("test@example.com")); // protected
        map.insert("$browser".to_string(), json!("Chrome")); // protected

        // Add large custom properties that push us over the target.
        let big_value = "x".repeat(500);
        map.insert("aaa_custom".to_string(), json!(big_value.clone()));
        map.insert("bbb_custom".to_string(), json!(big_value.clone()));
        map.insert("ccc_custom".to_string(), json!(big_value));

        let props = serde_json::Value::Object(map);
        let result = trim_properties_to_fit_size(&props, 1, 1, target);

        assert!(result.is_some());
        let trimmed = result.unwrap();
        let trimmed_map = trimmed.as_object().unwrap();

        // Protected properties are preserved
        assert!(trimmed_map.contains_key("email"));
        assert!(trimmed_map.contains_key("$browser"));

        // Custom properties are removed alphabetically until under target.
        assert!(!trimmed_map.contains_key("aaa_custom"));
    }

    #[test]
    fn trim_returns_none_when_only_protected_keys_exceed_target() {
        // If protected properties alone exceed the target, trim can't fit and
        // signals failure via `None`. Caller skips straight to skipped.
        let target = 1024;
        let mut map = serde_json::Map::new();
        let big_value = "x".repeat(2_000);
        map.insert("email".to_string(), json!(big_value)); // protected, over target

        let props = serde_json::Value::Object(map);
        let result = trim_properties_to_fit_size(&props, 1, 1, target);

        assert!(result.is_none());
    }
}
