#![allow(unused_imports)]
//! Integration tests for error handling in batch-import-worker
//!
//! These tests verify that:
//! 1. JSON parse errors produce user-friendly error messages
//! 2. The full error chain is preserved for developer debugging

use batch_import_worker::{
    error::get_user_message,
    source::{folder::FolderSource, DataSource},
};
use std::fs;
use tempfile::TempDir;

async fn setup_test_directory() -> (TempDir, FolderSource) {
    let temp_dir = TempDir::new().unwrap();

    fs::write(
        temp_dir.path().join("valid.jsonl"),
        r#"{"event": "$pageview", "distinct_id": "user1", "timestamp": "2024-01-01T00:00:00Z", "properties": {"$current_url": "https://example.com"}}
{"event": "$pageview", "distinct_id": "user2", "timestamp": "2024-01-01T00:01:00Z", "properties": {"$current_url": "https://example.com/about"}}
"#,
    )
    .unwrap();

    fs::write(
        temp_dir.path().join("invalid_line.jsonl"),
        r#"{"event": "$pageview", "distinct_id": "user1", "timestamp": "2024-01-01T00:00:00Z", "properties": {}}
this is not valid json - it will cause a parse error
{"event": "signup", "distinct_id": "user1", "timestamp": "2024-01-01T00:02:00Z", "properties": {}}
"#,
    )
    .unwrap();

    fs::write(
        temp_dir.path().join("truncated.jsonl"),
        r#"{"event": "$pageview", "distinct_id": "user1", "timestamp": "2024-01-01T00:00:00Z", "properties": {}}
{"event": "$pageview", "distinct_id": "user2", "timestamp": "2024-01-01T00:01:00Z", "properties": {"$current_url"
"#,
    )
    .unwrap();

    fs::write(temp_dir.path().join("empty_objects.jsonl"), "{}\n{}\n").unwrap();

    let source = FolderSource::new(temp_dir.path().to_str().unwrap().to_string())
        .await
        .unwrap();

    (temp_dir, source)
}

#[tokio::test]
async fn test_folder_source_lists_files() {
    let (_temp_dir, source) = setup_test_directory().await;
    let keys = source.keys().await.unwrap();

    assert_eq!(keys.len(), 4);
    assert!(keys.iter().any(|k| k == "valid.jsonl"));
    assert!(keys.iter().any(|k| k == "invalid_line.jsonl"));
}

#[tokio::test]
async fn test_valid_file_parses_successfully() {
    use batch_import_worker::parse::format::json_nd;
    use common_types::RawEvent;

    let (_temp_dir, source) = setup_test_directory().await;
    let chunk = source.get_chunk("valid.jsonl", 0, 10000).await.unwrap();

    let parser = json_nd::<RawEvent>(true);
    let result = parser(chunk);

    assert!(result.is_ok(), "Valid file should parse successfully");
    let parsed = result.unwrap();
    assert_eq!(parsed.data.len(), 2);
}

#[tokio::test]
async fn test_invalid_json_produces_user_friendly_error() {
    use batch_import_worker::parse::format::json_nd;
    use common_types::RawEvent;

    let (_temp_dir, source) = setup_test_directory().await;
    let chunk = source
        .get_chunk("invalid_line.jsonl", 0, 10000)
        .await
        .unwrap();

    let parser = json_nd::<RawEvent>(false); // Don't skip blank lines
    let result = parser(chunk);

    assert!(result.is_err(), "Invalid JSON should produce an error");
    let err = result.unwrap_err();

    let user_message = get_user_message(&err);
    assert!(
        user_message.contains("JSON") && user_message.contains("column"),
        "User message should mention JSON and include column info, got: {user_message}"
    );

    let full_error = format!("{err:#}");
    assert!(
        full_error.contains("json parse"),
        "Full error should mention json parsing, got: {full_error}"
    );
}

#[tokio::test]
async fn test_truncated_json_produces_user_friendly_error() {
    use batch_import_worker::parse::format::json_nd;
    use common_types::RawEvent;

    let (_temp_dir, source) = setup_test_directory().await;
    let chunk = source.get_chunk("truncated.jsonl", 0, 10000).await.unwrap();

    let parser = json_nd::<RawEvent>(true);
    let result = parser(chunk);

    assert!(result.is_err(), "Truncated JSON should produce an error");
    let err = result.unwrap_err();

    let user_message = get_user_message(&err);
    assert!(
        user_message.contains("truncated") || user_message.contains("incomplete"),
        "User message should mention truncated/incomplete JSON, got: {user_message}"
    );
}

#[tokio::test]
async fn test_error_message_extraction_from_nested_errors() {
    use anyhow::Context;
    use batch_import_worker::error::UserError;

    // Simulate the error chain as it's created in actual code:
    // Inner error has specific message, outer error concatenates it with filename
    let root_error = std::io::Error::new(std::io::ErrorKind::InvalidData, "unexpected token");
    let inner_error = anyhow::Error::from(root_error)
        .context(UserError::new("Your import file contains invalid JSON"))
        .context("Failed to json parse line");

    // Outer error concatenates inner message with filename (like job/mod.rs does)
    let inner_msg = get_user_message(&inner_error);
    let error = inner_error
        .context(UserError::new(format!(
            "Parsing data in file 'test_file.jsonl' failed: {inner_msg}"
        )))
        .context("Processing part chunk");

    let user_message = get_user_message(&error);
    assert!(
        user_message.contains("test_file.jsonl") && user_message.contains("invalid JSON"),
        "Should have file context with specific error, got: {user_message}"
    );
}

#[tokio::test]
async fn test_error_chain_preserves_all_context() {
    use anyhow::Context;
    use batch_import_worker::error::UserError;

    let root_error = serde_json::from_str::<serde_json::Value>("not valid json").unwrap_err();
    let error = anyhow::Error::from(root_error)
        .context(UserError::new("User-friendly message"))
        .context("Developer context 1")
        .context("Developer context 2");

    let full_error = format!("{error:#}");

    assert!(full_error.contains("Developer context 1"));
    assert!(full_error.contains("Developer context 2"));
    assert!(full_error.contains("expected value") || full_error.contains("expected ident"));
}

#[test]
fn test_schema_mismatch_produces_helpful_messages() {
    use batch_import_worker::parse::format::json_nd;
    use common_types::RawEvent;

    let missing_event = b"{\"distinct_id\": \"user1\"}\n".to_vec();
    let err = json_nd::<RawEvent>(false)(missing_event).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.contains("event") && msg.contains("required"),
        "Missing event field should produce helpful message, got: {msg}"
    );

    let wrong_type = b"{\"event\": 123, \"distinct_id\": \"user1\"}\n".to_vec();
    let err = json_nd::<RawEvent>(false)(wrong_type).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.contains("event") && msg.contains("string"),
        "Wrong type for event should mention it needs to be a string, got: {msg}"
    );

    let wrong_properties = b"{\"event\": \"test\", \"properties\": \"not an object\"}\n".to_vec();
    let err = json_nd::<RawEvent>(false)(wrong_properties).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.contains("object") || msg.contains("map"),
        "Wrong properties type should mention it needs to be an object, got: {msg}"
    );
}

#[test]
fn test_mixpanel_schema_errors_produce_helpful_messages() {
    use batch_import_worker::parse::content::mixpanel::MixpanelEvent;
    use batch_import_worker::parse::format::json_nd;

    // Missing required 'event' field
    let missing_event = b"{\"properties\": {\"time\": 1697379000}}\n".to_vec();
    let err = json_nd::<MixpanelEvent>(false)(missing_event).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("event") && msg.to_lowercase().contains("missing"),
        "Missing event field should produce helpful message, got: {msg}"
    );

    let missing_properties = b"{\"event\": \"test_event\"}\n".to_vec();
    let err = json_nd::<MixpanelEvent>(false)(missing_properties).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("properties") && msg.to_lowercase().contains("missing"),
        "Missing properties field should produce helpful message, got: {msg}"
    );

    let missing_time =
        b"{\"event\": \"test_event\", \"properties\": {\"distinct_id\": \"user1\"}}\n".to_vec();
    let err = json_nd::<MixpanelEvent>(false)(missing_time).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("time") && msg.to_lowercase().contains("missing"),
        "Missing time field should produce helpful message, got: {msg}"
    );

    let wrong_event_type = b"{\"event\": 123, \"properties\": {\"time\": 1697379000}}\n".to_vec();
    let err = json_nd::<MixpanelEvent>(false)(wrong_event_type).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("event") && msg.to_lowercase().contains("string"),
        "Wrong event type should mention it needs to be a string, got: {msg}"
    );

    let wrong_time_type =
        b"{\"event\": \"test\", \"properties\": {\"time\": \"not a number\"}}\n".to_vec();
    let err = json_nd::<MixpanelEvent>(false)(wrong_time_type).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("time")
            || msg.to_lowercase().contains("timestamp")
            || msg.to_lowercase().contains("integer"),
        "Wrong time type should mention timestamp/integer issue, got: {msg}"
    );
}

#[test]
fn test_amplitude_schema_errors_produce_helpful_messages() {
    use batch_import_worker::parse::content::amplitude::AmplitudeEvent;
    use batch_import_worker::parse::format::json_nd;

    let wrong_event_type = b"{\"event_type\": 123}\n".to_vec();
    let err = json_nd::<AmplitudeEvent>(false)(wrong_event_type).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("event_type") && msg.to_lowercase().contains("string"),
        "Wrong event_type should mention it needs to be a string, got: {msg}"
    );

    let wrong_user_id = b"{\"event_type\": \"test\", \"user_id\": 12345}\n".to_vec();
    let err = json_nd::<AmplitudeEvent>(false)(wrong_user_id).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("user_id") && msg.to_lowercase().contains("string"),
        "Wrong user_id type should mention it needs to be a string, got: {msg}"
    );

    // event_properties field has wrong type (string instead of object)
    // Note: serde doesn't always include field name in type errors, so we just check for helpful type guidance
    let wrong_properties =
        b"{\"event_type\": \"test\", \"event_properties\": \"not an object\"}\n".to_vec();
    let err = json_nd::<AmplitudeEvent>(false)(wrong_properties).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("object"),
        "Wrong event_properties type should mention it needs to be an object, got: {msg}"
    );

    let wrong_user_properties =
        b"{\"event_type\": \"test\", \"user_properties\": [\"not\", \"object\"]}\n".to_vec();
    let err = json_nd::<AmplitudeEvent>(false)(wrong_user_properties).unwrap_err();
    let msg = get_user_message(&err);
    assert!(
        msg.to_lowercase().contains("object"),
        "Wrong user_properties type should mention it needs to be an object, got: {msg}"
    );

    let valid_event = b"{\"event_type\": \"button_click\", \"user_id\": \"user123\", \"event_time\": \"2023-10-15 14:30:00\"}\n".to_vec();
    let result = json_nd::<AmplitudeEvent>(false)(valid_event);
    assert!(
        result.is_ok(),
        "Valid Amplitude event should parse successfully, got: {:?}",
        result.err()
    );
}
