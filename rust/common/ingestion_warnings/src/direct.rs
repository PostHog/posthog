//! The direct-to-topic warning transport, for services that know `team_id`
//! and produce straight to the ingestion warnings topic (personhog leader
//! and writer today). Capture cannot use this — it only knows tokens — and
//! goes through the `$$client_ingestion_warning` event envelope in
//! `serializer.rs` instead, with the Node consumer resolving the team and
//! stamping classifications.
//!
//! The payload matches the Node pipeline's `serializeIngestionWarning`
//! exactly: a ClickHouse-format timestamp, and the registry-declared
//! `category`/`severity` inside `details` — the v2 warnings table
//! materializes columns from those exact keys, defaulting to
//! unknown/warning when absent.

use chrono::Utc;
use serde_json::{Map, Value};

use crate::registry::WarningType;

/// Build the wire payload for one warning. `extra_details` carries the
/// caller's context (camelCase keys such as `personId`, `teamId`,
/// `message`); the builder stamps the classification over it so a stray
/// key can never override the registry's.
pub fn build_direct_warning_payload(
    team_id: i64,
    warning: WarningType,
    source: &str,
    mut extra_details: Map<String, Value>,
) -> Value {
    extra_details.insert("category".to_string(), Value::from(warning.category()));
    extra_details.insert("severity".to_string(), Value::from(warning.severity()));
    let details = Value::Object(extra_details);
    serde_json::json!({
        "team_id": team_id,
        "type": warning.as_str(),
        "source": source,
        "details": details.to_string(),
        "timestamp": Utc::now().format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn payloads_carry_registry_types_and_classifications() {
        for warning in WarningType::ALL {
            let mut details = Map::new();
            details.insert("personId".to_string(), Value::from("uuid-ish"));
            let payload = build_direct_warning_payload(7, warning, "personhog-test", details);

            assert_eq!(payload["team_id"], 7);
            assert_eq!(payload["type"], warning.as_str());
            assert_eq!(payload["source"], "personhog-test");
            let details: Value =
                serde_json::from_str(payload["details"].as_str().unwrap()).unwrap();
            assert_eq!(details["category"], warning.category());
            assert_eq!(details["severity"], warning.severity());
            assert_eq!(details["personId"], "uuid-ish");
            let timestamp = payload["timestamp"].as_str().unwrap();
            assert_eq!(timestamp.len(), 23);
            assert_eq!(timestamp.as_bytes()[10], b' ');
        }
    }

    #[test]
    fn classification_cannot_be_overridden_by_caller_details() {
        let mut details = Map::new();
        details.insert("category".to_string(), Value::from("spoofed"));
        let payload = build_direct_warning_payload(
            1,
            WarningType::PersonPropertiesSizeViolation,
            "s",
            details,
        );
        let details: Value = serde_json::from_str(payload["details"].as_str().unwrap()).unwrap();
        assert_eq!(details["category"], "size");
    }
}
