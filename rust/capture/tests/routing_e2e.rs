//! End-to-end routing coverage over a real broker: HTTP request → pipeline
//! stamps → address resolution → a message on the addressed topic.
//!
//! The routing goldens (`sinks/kafka.rs`) pin the produce contract against a
//! capturing mock producer, and the restriction integration suites pin the
//! stamped metadata; each half is covered, but only a real-broker test
//! catches the two halves agreeing with each other while being wrong about
//! the wire. This suite covers the addresses no other real-broker test
//! consumes: the dlq and custom admin redirects and the AI lanes.

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use assert_json_diff::assert_json_include;
use redis::Commands;
use reqwest::StatusCode;
use serde_json::json;
use std::num::NonZeroU32;

/// Writes restriction entries at the production Redis key for one restriction
/// type, deleting the key on drop. The production repository reads
/// unprefixed keys, so parallel safety comes from ownership discipline: each
/// test owns a distinct restriction type, and tokens are random, so another
/// concurrently booted server reading this key sees only inert entries.
struct RestrictionKey {
    key: String,
}

impl RestrictionKey {
    fn set(restriction_type: &str, entries: serde_json::Value) -> Self {
        let key = format!("event_ingestion_restriction_dynamic_config:{restriction_type}");
        let client = redis::Client::open(DEFAULT_CONFIG.redis_url.as_str())
            .expect("failed to create redis client");
        let mut conn = client.get_connection().expect("failed to connect to redis");
        conn.set::<_, _, ()>(&key, entries.to_string())
            .expect("failed to write restriction entries");
        Self { key }
    }
}

impl Drop for RestrictionKey {
    fn drop(&mut self) {
        if let Ok(client) = redis::Client::open(DEFAULT_CONFIG.redis_url.as_str()) {
            if let Ok(mut conn) = client.get_connection() {
                drop(conn.del::<_, ()>(&self.key));
            }
        }
    }
}

#[tokio::test]
async fn it_routes_dlq_redirected_events_to_the_dlq_topic() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let dlq_topic = EphemeralTopic::new().await;

    let _restriction = RestrictionKey::set(
        "redirect_to_dlq",
        json!([{"version": 2, "token": token, "pipelines": ["analytics"]}]),
    );

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.kafka.kafka_dlq_topic = dlq_topic.topic_name().to_string();
    config.event_restrictions_enabled = true;
    config.event_restrictions_redis_url = Some(config.redis_url.clone());
    // A failed first load (tight Redis timeout on a busy runner) retries on
    // the next tick; keep that tick close so the loaded-state wait recovers.
    config.event_restrictions_refresh_interval_secs = 1;
    let server = ServerHandle::for_config(config).await;
    server.wait_for_restrictions_loaded().await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    });
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let (key, event, headers) = dlq_topic.next_message_full()?;
    assert_eq!(
        key,
        Some(format!("{token}:{distinct_id}")),
        "dlq messages must keep the event key"
    );
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );
    assert_eq!(
        headers.get("dlq_reason"),
        Some(&"event_restriction".to_string())
    );
    assert_eq!(headers.get("dlq_step"), Some(&"capture".to_string()));
    assert!(
        headers.contains_key("dlq_timestamp"),
        "dlq messages must carry a dlq_timestamp header"
    );

    main_topic.assert_empty();
    Ok(())
}

#[tokio::test]
async fn it_routes_custom_redirected_events_to_the_admin_topic() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let custom_topic = EphemeralTopic::new().await;

    let _restriction = RestrictionKey::set(
        "redirect_to_topic",
        json!([{
            "version": 2,
            "token": token,
            "pipelines": ["analytics"],
            "args": {"topic": custom_topic.topic_name()}
        }]),
    );

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.event_restrictions_enabled = true;
    config.event_restrictions_redis_url = Some(config.redis_url.clone());
    // A failed first load (tight Redis timeout on a busy runner) retries on
    // the next tick; keep that tick close so the loaded-state wait recovers.
    config.event_restrictions_refresh_interval_secs = 1;
    let server = ServerHandle::for_config(config).await;
    server.wait_for_restrictions_loaded().await;

    let event = json!({
        "token": token,
        "event": "testing",
        "distinct_id": distinct_id
    });
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    let (key, event, headers) = custom_topic.next_message_full()?;
    assert_eq!(
        key,
        Some(format!("{token}:{distinct_id}")),
        "custom-redirected messages must keep the event key"
    );
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );
    assert!(
        !headers.contains_key("dlq_reason"),
        "a custom redirect is not a dlq: no dlq headers"
    );

    main_topic.assert_empty();
    Ok(())
}

#[tokio::test]
async fn it_routes_diverted_ai_events_to_the_ai_topic() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let ai_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.kafka.capture_analytics_ai_events_topic = ai_topic.topic_name().to_string();
    let server = ServerHandle::for_config(config).await;

    let batch = json!([
        {
            "token": token,
            "event": "$ai_generation",
            "distinct_id": distinct_id
        },
        {
            "token": token,
            "event": "$pageview",
            "distinct_id": distinct_id
        }
    ]);
    let res = server.capture_events(batch.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // The diverted AI event lands on the AI topic, keyed on the event key.
    let (key, event, _headers) = ai_topic.next_message_full()?;
    assert_eq!(key, Some(format!("{token}:{distinct_id}")));
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );
    ai_topic.assert_empty();

    // The non-AI event from the same batch stays on the main topic.
    let event = main_topic.next_event()?;
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );
    main_topic.assert_empty();
    Ok(())
}

#[tokio::test]
async fn it_routes_forced_ai_events_to_ai_overflow_when_the_valve_is_armed() -> Result<()> {
    setup_tracing();
    let token = random_string("token", 16);
    let distinct_id = random_string("id", 16);

    let main_topic = EphemeralTopic::new().await;
    let ai_topic = EphemeralTopic::new().await;
    let ai_overflow_topic = EphemeralTopic::new().await;

    let mut config = DEFAULT_CONFIG.clone();
    config.kafka.kafka_topic = main_topic.topic_name().to_string();
    config.kafka.capture_analytics_ai_events_topic = ai_topic.topic_name().to_string();
    config.kafka.capture_analytics_ai_events_overflow_topic =
        Some(ai_overflow_topic.topic_name().to_string());
    config.overflow_enabled = true;
    config.overflow_burst_limit = NonZeroU32::new(10).unwrap();
    config.overflow_per_second_limit = NonZeroU32::new(10).unwrap();
    config.ingestion_force_overflow_by_token_distinct_id = Some(token.clone());
    let server = ServerHandle::for_config(config).await;

    let event = json!({
        "token": token,
        "event": "$ai_generation",
        "distinct_id": distinct_id
    });
    let res = server.capture_events(event.to_string()).await;
    assert_eq!(StatusCode::OK, res.status());

    // A force-limited AI key overflows to the AI overflow topic — never the
    // analytics overflow — with the key dropped and person processing off.
    let (key, event, headers) = ai_overflow_topic.next_message_full()?;
    assert_eq!(key, None, "force-limited overflow must drop the event key");
    assert_json_include!(
        actual: event,
        expected: json!({
            "token": token,
            "distinct_id": distinct_id
        })
    );
    assert_eq!(
        headers.get("force_disable_person_processing"),
        Some(&"true".to_string()),
        "a force-limited key implies person processing off"
    );

    ai_topic.assert_empty();
    main_topic.assert_empty();
    Ok(())
}
