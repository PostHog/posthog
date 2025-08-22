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
) -> Result<InternallyCapturedEvent, Error> {
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
        distinct_id: Some(Value::String(user_id.to_string())), // Use user_id as distinct_id
        uuid: Some(event_uuid),
        event: "$identify".to_string(),
        properties: properties.into_iter().collect(),
        timestamp: Some(Utc::now().to_rfc3339()),
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
        is_cookieless_mode: false,
    };

    Ok(InternallyCapturedEvent {
        team_id,
        inner: captured_event,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn test_create_identify_event() {
        let team_id = 123;
        let token = "test_token";
        let user_id = "user123";
        let device_id = "device456";
        let event_uuid = Uuid::now_v7();

        let result = create_identify_event(team_id, token, user_id, device_id, event_uuid).unwrap();

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

        let result = create_identify_event(team_id, token, user_id, device_id, event_uuid).unwrap();

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
}
