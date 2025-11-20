use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde_json::Value;
use uuid::Uuid;

/// Creates a PostHog $identify event that links a user_id to a device_id
/// This is used when we first encounter a user_id + device_id combination from Amplitude
pub fn create_identify_event(
    team_id: i32,
    token: &str,
    user_id: &str,
    device_id: &str,
    event_uuid: Uuid,
    timestamp: chrono::DateTime<chrono::Utc>,
) -> Result<InternallyCapturedEvent, Error> {
    // Validate and trim inputs
    let user_id = user_id.trim();
    let device_id = device_id.trim();

    if user_id.is_empty() {
        return Err(Error::msg("user_id cannot be empty"));
    }
    if device_id.is_empty() {
        return Err(Error::msg("device_id cannot be empty"));
    }

    // Create properties for the identify event
    let mut properties = serde_json::Map::new();

    // Merge the device_id into the user_id person
    properties.insert(
        "$anon_distinct_id".to_string(),
        Value::String(device_id.to_string()),
    );

    // Add Amplitude-specific metadata
    properties.insert(
        "$amplitude_user_id".to_string(),
        Value::String(user_id.to_string()),
    );
    properties.insert(
        "$amplitude_device_id".to_string(),
        Value::String(device_id.to_string()),
    );

    // Mark this as a historical migration event
    properties.insert("historical_migration".to_string(), Value::Bool(true));
    properties.insert(
        "analytics_source".to_string(),
        Value::String("amplitude".to_string()),
    );

    // Create the raw event
    let raw_event = RawEvent {
        token: Some(token.to_string()),
        distinct_id: Some(Value::String(user_id.to_string())),
        uuid: Some(event_uuid),
        event: "$identify".to_string(),
        properties: properties.into_iter().collect(),
        timestamp: Some(timestamp.to_rfc3339()),
        set: None,
        set_once: None,
        offset: None,
    };

    // Create the captured event
    let captured_event = CapturedEvent {
        uuid: event_uuid,
        distinct_id: user_id.to_string(),
        ip: "127.0.0.1".to_string(), // Default IP for identify events
        data: serde_json::to_string(&raw_event)?,
        now: Utc::now().to_rfc3339(),
        sent_at: None,
        token: token.to_string(),
        event: "$identify".to_string(),
        timestamp,
        is_cookieless_mode: false,
        historical_migration: true,
    };

    Ok(InternallyCapturedEvent {
        team_id,
        inner: captured_event,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    #[test]
    fn test_create_identify_event() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();

        let timestamp = Utc::now();
        let result =
            create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp)
                .unwrap();

        assert_eq!(result.team_id, team_id);
        assert_eq!(result.inner.token, token);
        assert_eq!(result.inner.distinct_id, user_id);
        assert_eq!(result.inner.uuid, event_uuid);

        // Parse the data to verify structure
        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.event, "$identify");
        assert_eq!(data.distinct_id, Some(Value::String(user_id.to_string())));
        assert_eq!(data.token, Some(token.to_string()));

        // Check properties
        let props = data.properties;
        assert_eq!(
            props.get("$amplitude_user_id"),
            Some(&Value::String(user_id.to_string()))
        );
        assert_eq!(
            props.get("$amplitude_device_id"),
            Some(&Value::String(device_id.to_string()))
        );
        assert_eq!(props.get("historical_migration"), Some(&Value::Bool(true)));
        assert_eq!(
            props.get("analytics_source"),
            Some(&Value::String("amplitude".to_string()))
        );
        assert_eq!(
            props.get("$anon_distinct_id"),
            Some(&Value::String(device_id.to_string()))
        );
    }

    #[test]
    fn test_identify_event_structure() {
        let team_id = 456;
        let token = "another_token";
        let user_id = "test_user";
        let device_id = "test_device";
        let event_uuid = Uuid::now_v7();

        let timestamp = Utc::now();
        let result =
            create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp)
                .unwrap();

        // Verify the event has all required fields
        assert!(!result.inner.data.is_empty());
        assert!(!result.inner.distinct_id.is_empty());
        assert!(!result.inner.now.is_empty());
        assert!(!result.inner.ip.is_empty());

        // Parse and verify JSON structure
        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert!(data.timestamp.is_some());
        assert!(data.uuid.is_some());
        assert!(data.properties.contains_key("$amplitude_user_id"));
        assert!(data.properties.contains_key("$amplitude_device_id"));
        assert!(data.properties.contains_key("$anon_distinct_id"));
    }

    #[test]
    fn test_identify_event_with_special_characters() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user@domain.com";
        let device_id = "device:123:abc";
        let event_uuid = Uuid::now_v7();

        let timestamp = Utc::now();
        let result =
            create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp)
                .unwrap();

        // Verify basic structure
        assert_eq!(result.team_id, team_id);
        assert_eq!(result.inner.token, token);

        // Parse and verify special characters are preserved
        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.event, "$identify");

        let props = &data.properties;
        assert_eq!(
            props.get("$amplitude_user_id"),
            Some(&Value::String(user_id.to_string()))
        );
        assert_eq!(
            props.get("$amplitude_device_id"),
            Some(&Value::String(device_id.to_string()))
        );
        assert_eq!(
            props.get("$anon_distinct_id"),
            Some(&Value::String(device_id.to_string()))
        );
    }

    #[test]
    fn test_identify_event_validation() {
        let team_id = 123;
        let token = "test_token";
        let event_uuid = Uuid::now_v7();

        // Test with empty strings (should fail)
        let timestamp = Utc::now();
        let result = create_identify_event(team_id, token, "", "", event_uuid, timestamp);
        assert!(result.is_err(), "Should reject empty user_id");
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("user_id cannot be empty"));

        // Test with whitespace-only strings (should fail)
        let result =
            create_identify_event(team_id, token, "   ", "device123", event_uuid, timestamp);
        assert!(result.is_err(), "Should reject whitespace-only user_id");
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("user_id cannot be empty"));

        let result = create_identify_event(team_id, token, "user123", "   ", event_uuid, timestamp);
        assert!(result.is_err(), "Should reject whitespace-only device_id");
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("device_id cannot be empty"));

        // Test with very long strings (should succeed)
        let long_user_id = "a".repeat(1000);
        let long_device_id = "b".repeat(1000);
        let result = create_identify_event(
            team_id,
            token,
            &long_user_id,
            &long_device_id,
            event_uuid,
            timestamp,
        );
        assert!(result.is_ok(), "Should handle very long strings");

        // Test with unicode characters (should succeed)
        let unicode_user_id = "用户123测试";
        let unicode_device_id = "设备测试456";
        let result = create_identify_event(
            team_id,
            token,
            unicode_user_id,
            unicode_device_id,
            event_uuid,
            timestamp,
        );
        assert!(result.is_ok(), "Should handle unicode characters");

        let data: RawEvent = serde_json::from_str(&result.unwrap().inner.data).unwrap();
        let props = &data.properties;
        assert_eq!(
            props.get("$amplitude_user_id"),
            Some(&Value::String(unicode_user_id.to_string()))
        );
        assert_eq!(
            props.get("$amplitude_device_id"),
            Some(&Value::String(unicode_device_id.to_string()))
        );
    }

    #[test]
    fn test_identify_event_json_structure() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();

        let timestamp = Utc::now();
        let result =
            create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp)
                .unwrap();
        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();

        // Verify exact JSON structure
        assert_eq!(data.event, "$identify");
        assert_eq!(data.token, Some(token.to_string()));
        assert_eq!(data.distinct_id, Some(Value::String(user_id.to_string())));
        assert_eq!(data.uuid, Some(event_uuid));

        // Verify set and set_once are None (not used for identify events)
        assert!(data.set.is_none());
        assert!(data.set_once.is_none());

        // Verify offset is None
        assert!(data.offset.is_none());

        // Verify timestamp is set
        assert!(data.timestamp.is_some());

        // Verify properties structure
        let props = &data.properties;
        assert!(props.contains_key("$amplitude_user_id"));
        assert!(props.contains_key("$amplitude_device_id"));
        assert!(props.contains_key("$anon_distinct_id"));
        assert!(props.contains_key("historical_migration"));
        assert!(props.contains_key("analytics_source"));
    }

    #[test]
    fn test_identify_event_uuid_generation() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid1 = Uuid::now_v7();
        let event_uuid2 = Uuid::now_v7();

        let timestamp = Utc::now();
        let result1 =
            create_identify_event(team_id, token, user_id, device_id, event_uuid1, timestamp)
                .unwrap();
        let result2 =
            create_identify_event(team_id, token, user_id, device_id, event_uuid2, timestamp)
                .unwrap();

        // UUIDs should be preserved
        assert_eq!(result1.inner.uuid, event_uuid1);
        assert_eq!(result2.inner.uuid, event_uuid2);
        assert_ne!(event_uuid1, event_uuid2); // Different UUIDs

        // Verify UUIDs in the parsed data
        let data1: RawEvent = serde_json::from_str(&result1.inner.data).unwrap();
        let data2: RawEvent = serde_json::from_str(&result2.inner.data).unwrap();

        assert_eq!(data1.uuid, Some(event_uuid1));
        assert_eq!(data2.uuid, Some(event_uuid2));
    }

    #[test]
    fn test_identify_event_captured_event_structure() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();

        let timestamp = Utc::now();
        let result =
            create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp)
                .unwrap();

        // Verify CapturedEvent structure
        assert_eq!(result.inner.uuid, event_uuid);
        assert_eq!(result.inner.distinct_id, user_id);
        assert_eq!(result.inner.token, token);
        assert_eq!(result.inner.ip, "127.0.0.1"); // Default IP for identify events
        assert!(!result.inner.data.is_empty());
        assert!(result.inner.now.contains("T")); // ISO 8601 timestamp format
        assert!(result.inner.sent_at.is_none()); // Should be None for historical imports
        assert!(!result.inner.is_cookieless_mode); // Should be false

        // Verify team_id is set correctly
        assert_eq!(result.team_id, team_id);
    }

    #[test]
    fn test_identify_event_preserves_timestamp() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();

        let specific_timestamp = chrono::DateTime::parse_from_rfc3339("2023-10-15T14:30:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let result = create_identify_event(
            team_id,
            token,
            user_id,
            device_id,
            event_uuid,
            specific_timestamp,
        )
        .unwrap();

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(data.timestamp, Some(specific_timestamp.to_rfc3339()));

        let now = Utc::now();
        assert_ne!(data.timestamp, Some(now.to_rfc3339()));
    }

    #[test]
    fn test_identify_event_has_historical_migration_and_current_now_timestamp() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();
        let before_test = Utc::now();

        let specific_timestamp = chrono::DateTime::parse_from_rfc3339("2023-10-15T14:30:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let result = create_identify_event(
            team_id,
            token,
            user_id,
            device_id,
            event_uuid,
            specific_timestamp,
        )
        .unwrap();

        let after_test = Utc::now();

        assert!(
            result.inner.historical_migration,
            "historical_migration field must be true for identify events"
        );

        assert!(
            !result.inner.now.is_empty(),
            "now field must be set for events"
        );

        let now_timestamp = chrono::DateTime::parse_from_rfc3339(&result.inner.now)
            .expect("now should be valid RFC3339 timestamp")
            .with_timezone(&Utc);
        assert!(
            now_timestamp >= before_test && now_timestamp <= after_test,
            "now timestamp should be current (between test start and end)"
        );

        let serialized = serde_json::to_value(&result.inner).unwrap();
        assert_eq!(
            serialized["historical_migration"],
            json!(true),
            "historical_migration must be in serialized output"
        );
        assert!(
            serialized["now"].is_string(),
            "now must be a string in serialized output"
        );
    }

    #[test]
    fn test_identify_event_with_edge_case_ids() {
        let team_id = 123;
        let token = "test_token";
        let event_uuid = Uuid::now_v7();

        // Test with edge cases that should fail
        let failing_cases = vec![
            ("", "device123"),  // Empty user_id
            ("user123", ""),    // Empty device_id
            (" ", "device123"), // Whitespace-only user_id
            ("user123", " "),   // Whitespace-only device_id
        ];

        let timestamp = Utc::now();
        for (user_id, device_id) in failing_cases {
            let result =
                create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp);
            assert!(
                result.is_err(),
                "Should reject invalid case: user_id='{user_id}', device_id='{device_id}'"
            );
        }

        // Test with edge cases that should succeed
        let valid_cases = vec![
            ("null", "device123"),               // "null" string is valid
            ("user123", "undefined"),            // "undefined" string is valid
            ("123", "456"),                      // Numeric strings are valid
            ("user@domain.co.uk", "device#123"), // Multiple special chars are valid
            ("\tuser123\t", "device456"),        // Leading/trailing whitespace is trimmed and valid
            ("user456", "\tdevice789\t"),        // Leading/trailing whitespace is trimmed and valid
        ];

        for (user_id, device_id) in valid_cases {
            let result =
                create_identify_event(team_id, token, user_id, device_id, event_uuid, timestamp);
            assert!(
                result.is_ok(),
                "Should accept valid case: user_id='{user_id}', device_id='{device_id}'"
            );

            let event = result.unwrap();
            let data: RawEvent = serde_json::from_str(&event.inner.data).unwrap();

            // For trimmed cases, verify the trimmed values are used
            let expected_user_id = user_id.trim();
            let expected_device_id = device_id.trim();

            // Verify the trimmed values are preserved in properties
            assert_eq!(
                data.properties.get("$amplitude_user_id"),
                Some(&Value::String(expected_user_id.to_string()))
            );
            assert_eq!(
                data.properties.get("$amplitude_device_id"),
                Some(&Value::String(expected_device_id.to_string()))
            );
            assert_eq!(
                data.properties.get("$anon_distinct_id"),
                Some(&Value::String(expected_device_id.to_string()))
            );

            // Also verify distinct_id is trimmed
            assert_eq!(
                data.distinct_id,
                Some(Value::String(expected_user_id.to_string()))
            );
            assert_eq!(event.inner.distinct_id, expected_user_id);
        }
    }
}
