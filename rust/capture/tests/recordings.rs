use crate::common::*;
use anyhow::Result;
use assert_json_diff::assert_json_include;
use capture::config::CaptureMode;
use capture::limiters::redis::QuotaResource;
use reqwest::StatusCode;
use serde_json::{json, value::Value};
use time::Duration;

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

#[tokio::test]
async fn it_rejects_bad_session_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let window_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id,
        "$session_id": {"should_not_be": "an object"},
        "properties": {
            "$session_id": {"should_not_be": "an object"},
            "$window_id": window_id,
            "$snapshot_data": [],
        }
    });
    let res = server.capture_recording(event.to_string()).await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());
    Ok(())
}

#[tokio::test]
async fn it_defaults_window_id_to_session_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id,
        "properties": {
            "$session_id": session_id,
            "$snapshot_data": [],
        }
    });
    let res = server.capture_recording(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());
    Ok(())
}

#[tokio::test]
async fn it_applies_overflow_limits() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let session1 = random_string("session1", 16);
    let session2 = random_string("session2", 16);
    let session3 = random_string("session3", 16);
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    // Setup overflow limits:
    //   - session1 limit is expired -> accept messages
    //   - session2 limit is active -> send to overflow
    //   - session3 is not in redis -> accept by default
    let redis = PrefixedRedis::new().await;
    redis.add_overflow_limit(QuotaResource::Recordings, &session1, Duration::seconds(-60));
    redis.add_overflow_limit(QuotaResource::Recordings, &session2, Duration::seconds(60));

    let mut config = DEFAULT_CONFIG.clone();
    config.redis_key_prefix = redis.key_prefix();
    config.kafka.kafka_topic = topic.topic_name().to_string();
    config.kafka.kafka_replay_overflow_topic = overflow_topic.topic_name().to_string();
    config.kafka.kafka_replay_overflow_topic = overflow_topic.topic_name().to_string();
    config.capture_mode = CaptureMode::Recordings;
    let server = ServerHandle::for_config(config).await;

    for payload in [
        json!({
            "token": token,
            "event": "testing",
            "distinct_id": distinct_id,
            "properties": {
                "$session_id": session1,
                "$snapshot_data": [],
            },
        }),
        json!({
            "token": token,
            "event": "testing",
            "distinct_id": distinct_id,
            "properties": {
                "$session_id": session2,
                "$snapshot_data": [],
            },
        }),
        json!({
            "token": token,
            "event": "testing",
            "distinct_id": distinct_id,
            "properties": {
                "$session_id": session3,
                "$snapshot_data": [],
            },
        }),
    ] {
        let res = server.capture_recording(payload.to_string()).await;
        assert_eq!(StatusCode::OK, res.status());
    }

    // Batches 1 and 3 go through, batch 2 is sent to overflow
    assert_json_include!(
        actual: serde_json::from_str::<Value>(topic.next_event()?.get("data").unwrap().as_str().unwrap())?,
        expected: json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": session1,
                "distinct_id": distinct_id,
                "$snapshot_items": [],
            },
        })
    );
    assert_json_include!(
        actual: serde_json::from_str::<Value>(topic.next_event()?.get("data").unwrap().as_str().unwrap())?,
        expected: json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": session3,
                "distinct_id": distinct_id,
                "$snapshot_items": [],
            },
        })
    );

    assert_json_include!(
        actual: serde_json::from_str::<Value>(overflow_topic.next_event()?.get("data").unwrap().as_str().unwrap())?,
        expected: json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": session2,
                "distinct_id": distinct_id,
                "$snapshot_items": [],
            },
        })
    );

    Ok(())
}
