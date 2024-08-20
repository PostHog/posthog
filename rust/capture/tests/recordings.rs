use std::num::NonZeroU32;
use time::Duration;

use crate::common::*;
use anyhow::Result;
use assert_json_diff::assert_json_include;
use capture::limiters::billing::QuotaResource;
use reqwest::StatusCode;
use serde_json::json;
use uuid::Uuid;
mod common;

#[tokio::test]
async fn it_captures_one_recording() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = random_string("id", 16);
    let window_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id,
        "$session_id": session_id,
        "properties": {
            "$session_id": session_id,
            "$window_id": window_id,
            "$snapshot_data": [],
        }
    });
    let res = server.capture_recording(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let event = main_topic.next_event()?;
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_fails_no_session_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = random_string("id", 16);
    let window_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id,
        "$session_id": session_id,
        "properties": {
            "$window_id": window_id,
            "$snapshot_data": [],
        }
    });
    let res = server.capture_recording(event.to_string()).await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());
    Ok(())
}
