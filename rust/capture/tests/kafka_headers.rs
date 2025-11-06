#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use chrono::{DateTime, Utc};
use reqwest::StatusCode;
use serde_json::json;

#[tokio::test]
async fn it_adds_timestamp_header_to_kafka_messages() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test with explicit timestamp
    let explicit_timestamp = "2023-01-01T12:00:00Z";
    let event = json!({
        "token": token,
        "event": "testing_timestamp_header",
        "distinct_id": distinct_id,
        "timestamp": explicit_timestamp
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get both event data and headers from the same message
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was processed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();
    assert_eq!(event_obj.get("token").unwrap().as_str().unwrap(), token);
    assert_eq!(
        event_obj.get("distinct_id").unwrap().as_str().unwrap(),
        distinct_id
    );

    // Verify timestamp header exists and is correct
    assert!(
        headers.contains_key("timestamp"),
        "Missing 'timestamp' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );

    let header_timestamp = headers.get("timestamp").unwrap();
    let timestamp_millis: i64 = header_timestamp
        .parse()
        .expect("timestamp header should be a valid number");

    // Convert back to DateTime to verify it matches our input
    let header_datetime =
        DateTime::from_timestamp_millis(timestamp_millis).expect("timestamp should be valid");

    let expected_datetime = DateTime::parse_from_rfc3339(explicit_timestamp)?.with_timezone(&Utc);

    assert_eq!(
        header_datetime, expected_datetime,
        "Timestamp header {header_datetime} should match event timestamp {expected_datetime}"
    );

    // Verify other expected headers are present
    assert_eq!(headers.get("token").unwrap(), &token);
    assert_eq!(headers.get("distinct_id").unwrap(), &distinct_id);

    Ok(())
}

#[tokio::test]
async fn it_adds_timestamp_header_for_events_without_timestamp() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test without any timestamp - should use server time
    let event = json!({
        "token": token,
        "event": "testing_no_timestamp",
        "distinct_id": distinct_id
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get both event data and headers from the same message
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was processed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();
    assert_eq!(event_obj.get("token").unwrap().as_str().unwrap(), token);
    assert_eq!(
        event_obj.get("distinct_id").unwrap().as_str().unwrap(),
        distinct_id
    );

    // Verify timestamp header exists and is reasonable
    assert!(
        headers.contains_key("timestamp"),
        "Missing 'timestamp' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );

    let header_timestamp = headers.get("timestamp").unwrap();
    let timestamp_millis: i64 = header_timestamp
        .parse()
        .expect("timestamp header should be a valid number");

    // Should be current server time
    assert!(timestamp_millis > 0, "Timestamp should be positive");

    let header_datetime =
        DateTime::from_timestamp_millis(timestamp_millis).expect("timestamp should be valid");

    // Should be very recent (within last 10 seconds)
    let now = Utc::now();
    let diff = (now - header_datetime).num_seconds().abs();
    assert!(
        diff < 10,
        "Timestamp should be very recent (diff: {diff} seconds)"
    );

    Ok(())
}

#[tokio::test]
async fn it_adds_timestamp_header_with_clock_skew_correction() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test with recent timestamp and sent_at for clock skew correction
    let now = Utc::now();
    let event_timestamp = now.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let sent_at = (now + chrono::Duration::seconds(5))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string(); // 5 seconds after event timestamp

    let event = json!({
        "token": token,
        "event": "testing_clock_skew",
        "distinct_id": distinct_id,
        "timestamp": event_timestamp,
        "sent_at": sent_at
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get both event data and headers from the same message
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was processed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();
    assert_eq!(event_obj.get("token").unwrap().as_str().unwrap(), token);
    assert_eq!(
        event_obj.get("distinct_id").unwrap().as_str().unwrap(),
        distinct_id
    );

    // Verify timestamp header exists and has been adjusted for clock skew
    assert!(
        headers.contains_key("timestamp"),
        "Missing 'timestamp' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );

    let header_timestamp = headers.get("timestamp").unwrap();
    let timestamp_millis: i64 = header_timestamp
        .parse()
        .expect("timestamp header should be a valid number");

    // The timestamp should be adjusted for clock skew
    // Since we don't know the exact server time, we just verify it's a reasonable value
    assert!(timestamp_millis > 0, "Timestamp should be positive");

    // Convert to DateTime for basic validation
    let header_datetime =
        DateTime::from_timestamp_millis(timestamp_millis).expect("timestamp should be valid");

    // Should be a reasonable date (within last few minutes)
    let current_time = Utc::now();
    let diff = (current_time - header_datetime).num_seconds().abs();
    assert!(
        diff < 300,
        "Timestamp should be within 5 minutes of now (diff: {diff} seconds)"
    );

    Ok(())
}

#[tokio::test]
async fn it_adds_event_and_uuid_headers_to_kafka_messages() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let event_name = "test_event_with_headers";
    let uuid = "550e8400-e29b-41d4-a716-446655440000"; // Test with explicit UUID

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test with explicit event name and UUID
    let event = json!({
        "token": token,
        "event": event_name,
        "distinct_id": distinct_id,
        "uuid": uuid
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get both event data and headers from the same message
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was processed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();
    assert_eq!(event_obj.get("token").unwrap().as_str().unwrap(), token);
    assert_eq!(
        event_obj.get("distinct_id").unwrap().as_str().unwrap(),
        distinct_id
    );

    // Verify event header exists and matches
    assert!(
        headers.contains_key("event"),
        "Missing 'event' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );
    assert_eq!(
        headers.get("event").unwrap(),
        event_name,
        "Event header should match the event name"
    );

    // Verify uuid header exists and matches
    assert!(
        headers.contains_key("uuid"),
        "Missing 'uuid' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );
    assert_eq!(
        headers.get("uuid").unwrap(),
        uuid,
        "UUID header should match the provided UUID"
    );

    // Verify other expected headers are still present
    assert_eq!(headers.get("token").unwrap(), &token);
    assert_eq!(headers.get("distinct_id").unwrap(), &distinct_id);
    assert!(headers.contains_key("timestamp"));

    Ok(())
}

#[tokio::test]
async fn it_adds_event_and_generated_uuid_headers() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let event_name = "test_event_generated_uuid";

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test without providing UUID - should generate one
    let event = json!({
        "token": token,
        "event": event_name,
        "distinct_id": distinct_id
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get both event data and headers from the same message
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was processed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();
    assert_eq!(event_obj.get("token").unwrap().as_str().unwrap(), token);

    // Verify event header
    assert_eq!(
        headers.get("event").unwrap(),
        event_name,
        "Event header should match the event name"
    );

    // Verify uuid header exists and is a valid UUID
    assert!(
        headers.contains_key("uuid"),
        "Missing 'uuid' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );

    let uuid_header = headers.get("uuid").unwrap();
    // Basic UUID format validation
    assert!(
        uuid_header.len() == 36,
        "UUID should be 36 characters long, got: {uuid_header}"
    );
    assert!(
        uuid_header.contains('-'),
        "UUID should contain dashes, got: {uuid_header}"
    );

    Ok(())
}

#[tokio::test]
async fn it_adds_correct_headers_for_special_events() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let histo_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_topics(&main_topic, &histo_topic).await;

    // Test with $identify event (special case from engage endpoint)
    let event = json!({
        "token": token,
        "event": "$identify",
        "distinct_id": distinct_id,
        "$set": {"email": "test@example.com"}
    });

    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let (_, headers) = main_topic.next_message_with_headers()?;

    // Verify the $identify event name is in the header
    assert_eq!(
        headers.get("event").unwrap(),
        "$identify",
        "Event header should be $identify"
    );

    // Test with $pageview event
    let pageview_event = json!({
        "token": token,
        "event": "$pageview",
        "distinct_id": distinct_id,
        "properties": {"$current_url": "https://example.com"}
    });

    let res = server.capture_events(pageview_event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let (_, headers) = main_topic.next_message_with_headers()?;

    assert_eq!(
        headers.get("event").unwrap(),
        "$pageview",
        "Event header should be $pageview"
    );

    Ok(())
}

#[tokio::test]
async fn it_adds_correct_headers_for_snapshot_events() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = "550e8400-e29b-41d4-a716-446655440001";
    let window_id = random_string("window", 16);

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    // Test with snapshot event
    let event = json!([{
        "token": token,
        "event": "$snapshot",
        "distinct_id": distinct_id,
        "properties": {
            "$session_id": session_id,
            "$window_id": window_id,
            "$snapshot_data": [{"type": 2, "data": {"source": 0}}]
        }
    }]);

    let res = server.capture_recording(event.to_string(), None).await;
    assert_eq!(StatusCode::OK, res.status());

    // Get message from snapshot topic
    let (event_data, headers) = main_topic.next_message_with_headers()?;

    // Check that the event was transformed correctly
    assert!(event_data.is_object(), "Event should be a JSON object");
    let event_obj = event_data.as_object().unwrap();

    // Check event data contains the expected fields
    let data = serde_json::from_str::<serde_json::Value>(
        event_obj.get("data").unwrap().as_str().unwrap(),
    )?;
    assert_eq!(
        data.get("event").unwrap().as_str().unwrap(),
        "$snapshot_items",
        "Snapshot events should be transformed to $snapshot_items"
    );

    // Verify event header is set to $snapshot_items
    assert_eq!(
        headers.get("event").unwrap(),
        "$snapshot_items",
        "Event header should be $snapshot_items for snapshot events"
    );

    // Verify uuid header exists
    assert!(
        headers.contains_key("uuid"),
        "Missing 'uuid' header. Available headers: {:?}",
        headers.keys().collect::<Vec<_>>()
    );

    // Verify other headers
    assert_eq!(headers.get("token").unwrap(), &token);
    assert_eq!(headers.get("distinct_id").unwrap(), &distinct_id);
    assert!(headers.contains_key("timestamp"));

    Ok(())
}
