use anyhow::Result;
use assert_json_diff::assert_json_include;
use capture::config::CaptureMode;
use chrono::Utc;

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use limiters::redis::QuotaResource;
use reqwest::StatusCode;
use serde_json::{json, value::Value};
use time::Duration;
use uuid::Uuid;

#[tokio::test]
async fn it_captures_one_recording() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();
    let window_id = random_string("id", 16);
    let lib = random_string("lib", 16);

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
            "$lib": lib,
        }
    });
    let res = server.capture_recording(event.to_string(), None).await;
    assert_eq!(StatusCode::OK, res.status());

    let event = main_topic.next_event()?;

    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id,
        })
    );

    let data_json: Value = serde_json::from_str(event["data"].as_str().unwrap())?;
    assert_json_include!(
        actual: data_json,
        expected: json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": session_id,
                "$window_id": window_id,
                "$snapshot_items": [],
                "$lib": lib,
                "$snapshot_source": "web"
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_captures_one_recording_with_user_agent_fallback_for_lib() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();
    let window_id = random_string("id", 16);
    let lib = "posthog-android/1.0.4";

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
            // NO LIB SET HERE
        }
    });
    let res = server
        .capture_recording(event.to_string(), Option::from(lib))
        .await;
    assert_eq!(StatusCode::OK, res.status());

    let event = main_topic.next_event()?;

    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id,
        })
    );

    let data_json: Value = serde_json::from_str(event["data"].as_str().unwrap())?;
    assert_json_include!(
        actual: data_json,
        expected: json!({
            "event": "$snapshot_items",
            "properties": {
                "$session_id": session_id,
                "$window_id": window_id,
                "$snapshot_items": [],
                "$lib": "posthog-android",
                "$snapshot_source": "web"
            }
        })
    );

    Ok(())
}

#[tokio::test]
async fn it_fails_no_session_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();
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
    let res = server.capture_recording(event.to_string(), None).await;
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
    let res = server.capture_recording(event.to_string(), None).await;
    assert_eq!(StatusCode::BAD_REQUEST, res.status());
    Ok(())
}

#[tokio::test]
async fn it_validates_session_id_formats() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let window_id = random_string("id", 16);

    // These are valid session IDs that should pass validation
    let valid_session_ids = vec![
        // UUIDv7 style
        Uuid::now_v7().to_string(),
        // UUIDv4 style
        "f47ac10b-58cc-4372-a567-0e02b2c3d479".to_string(),
        // The example UUIDs that were previously problematic but should now pass
        "1960056980813e1-0a097dad71d3f-26011d51-144000-19600569809bc5".to_string(),
        "196007bca5942f-076a0cca0e9058-b457454-4e000-196007bca5a9ca".to_string(),
        "19600767475aa8-0ee6565b416bd78-f407878-61d78-19600767476811d".to_string(),
        "196007e76cb16e2-0587fb99f6dd4e-1b525636-157188-196007e76cc35cc".to_string(),
        "19600495cc74f8-068f4554dc7281-26011d51-1fa400-19600495cc81cc8".to_string(),
    ];

    // These are invalid session IDs that should be rejected
    let invalid_session_ids = vec![
        // Very long string that exceeds length limit
        "not-a-uuid-string".repeat(10),
        // Similar pattern to the example UUIDs but with extra length
        "1960056980813e1-0a097dad71d3f-26011d51-144000-19600569809bc5".repeat(2),
        // Extremely long version of the problematic format
        "19600767475aa8-0ee6565b416bd78-f407878-61d78-19600767476811d".repeat(3),
        // Extremely long session ID
        "x".repeat(200),
        // URL-encoded string
        "%3Cscript%3Ealert%28%27hello%27%29%3C%2Fscript%3E".to_string(),
        // Session ID with invalid characters
        "1234-5678-9abc-def!@#".to_string(),
        // Session ID with spaces
        "1234 5678 9abc def".to_string(),
    ];

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    // Test valid session IDs (should be accepted)
    for session_id in valid_session_ids {
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
        let res = server.capture_recording(event.to_string(), None).await;
        assert_eq!(
            StatusCode::OK,
            res.status(),
            "Expected session ID '{session_id}' to be accepted, but got error status"
        );
    }

    // Test invalid session IDs (should be rejected)
    for session_id in invalid_session_ids {
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
        let res = server.capture_recording(event.to_string(), None).await;
        assert_eq!(
            StatusCode::BAD_REQUEST,
            res.status(),
            "Expected session ID '{session_id}' to be rejected, but was accepted"
        );
    }

    Ok(())
}

#[tokio::test]
async fn it_defaults_window_id_to_session_id() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();

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
    let res = server.capture_recording(event.to_string(), None).await;
    assert_eq!(StatusCode::OK, res.status());
    Ok(())
}

#[tokio::test]
async fn it_applies_overflow_limits() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let session1 = Uuid::now_v7().to_string();
    let session2 = Uuid::now_v7().to_string();
    let session3 = Uuid::now_v7().to_string();
    let distinct_id = random_string("id", 16);

    let topic = EphemeralTopic::new().await;
    let overflow_topic = EphemeralTopic::new().await;

    // Setup overflow limits:
    //   - session1 limit is expired -> accept messages
    //   - session2 limit is active -> send to overflow
    //   - session3 is not in redis -> accept by default
    let redis = PrefixedRedis::new().await;
    redis.add_overflow_limit(QuotaResource::Replay, &session1, Duration::seconds(-60));
    redis.add_overflow_limit(QuotaResource::Replay, &session2, Duration::seconds(60));

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
        let res = server.capture_recording(payload.to_string(), None).await;
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

#[tokio::test]
async fn it_returns_200() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();
    let window_id = Uuid::now_v7().to_string();

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let recording_event = json!([{
        "token": token,
        "event": "$snapshot",
        "distinct_id": distinct_id,
        "$session_id": session_id.clone(),
        "properties": {
            "$session_id": session_id.clone(),
            "$window_id": window_id.clone(),
            "$snapshot_data": [
                {"type": 2, "data": {"source": 0}, "timestamp": Utc::now().timestamp_millis()}
            ]
        }
    }]);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(3000))
        .build()
        .unwrap();

    let timestamp = Utc::now().timestamp_millis();
    let beacon_url = format!(
        "http://{:?}/s/?ip=1&_={}&ver=1.240.6",
        server.addr, timestamp
    );

    let res = client
        .post(beacon_url)
        .body(recording_event.to_string())
        .send()
        .await
        .expect("Failed to send beacon request to /s/");

    assert_eq!(StatusCode::OK, res.status(), "Expected OK");

    Ok(())
}

#[tokio::test]
async fn it_returns_204_when_beacon_is_1_for_recordings() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);
    let session_id = Uuid::now_v7().to_string();
    let window_id = Uuid::now_v7().to_string();

    let main_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings(&main_topic).await;

    let recording_event = json!([{
        "token": token,
        "event": "$snapshot",
        "distinct_id": distinct_id,
        "$session_id": session_id.clone(),
        "properties": {
            "$session_id": session_id.clone(),
            "$window_id": window_id.clone(),
            "$snapshot_data": [
                {"type": 2, "data": {"source": 0}, "timestamp": Utc::now().timestamp_millis()}
            ]
        }
    }]);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(3000))
        .build()
        .unwrap();

    let timestamp = Utc::now().timestamp_millis();
    let beacon_url = format!(
        "http://{:?}/s/?ip=1&_={}&ver=1.240.6&beacon=1",
        server.addr, timestamp
    );

    let res_no_content = client
        .post(beacon_url)
        .body(recording_event.to_string())
        .send()
        .await
        .expect("Failed to send beacon request to /s/");

    assert_eq!(
        StatusCode::NO_CONTENT,
        res_no_content.status(),
        "Expected NO_CONTENT for beacon recording request"
    );

    Ok(())
}
