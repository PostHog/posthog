//! Sink-level integration tests for the v1 analytics pipeline.
//!
//! These tests verify the end-to-end path:
//!   WrappedEvent -> KafkaSink.publish_batch() -> real Kafka -> consumer -> CapturedEvent
//!
//! Requires Docker Kafka (same rig as legacy integration tests).
//!
//! TODO(v1): add HTTP-level integration tests (ServerHandle + POST /i/v1/general/events)
//! and process_batch orchestration tests once the v1 HTTP router is merged into the
//! main application and process_batch is fully implemented (currently a stub).

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use common_types::{CapturedEvent, RawEvent};

use capture::config::CaptureMode;
use capture::v1::context::Context;
use capture::v1::sinks::event::Event;
use capture::v1::sinks::kafka::producer::KafkaProducer;
use capture::v1::sinks::kafka::KafkaSink;
use capture::v1::sinks::sink::Sink;
use capture::v1::sinks::types::Outcome;
use capture::v1::sinks::{Config, SinkName};
use capture::v1::test_utils::{self, WrappedEventMut};

fn v1_kafka_config(topic: &str) -> capture::v1::sinks::kafka::config::Config {
    let env: std::collections::HashMap<String, String> = [
        ("HOSTS", "kafka:9092"),
        ("TOPIC_MAIN", topic),
        ("TOPIC_HISTORICAL", topic),
        ("TOPIC_OVERFLOW", topic),
        ("TOPIC_DLQ", topic),
        ("LINGER_MS", "0"),
        ("COMPRESSION_CODEC", "none"),
        ("MESSAGE_TIMEOUT_MS", "10000"),
        ("QUEUE_MIB", "10"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect();
    envconfig::Envconfig::init_from_hashmap(&env).unwrap()
}

fn v1_test_context() -> Context {
    let mut ctx = test_utils::test_context();
    ctx.api_token = "phc_integration_test_token".to_string();
    ctx
}

async fn build_v1_sink(topic: &str) -> (KafkaSink<KafkaProducer>, lifecycle::MonitorGuard) {
    let mut manager = lifecycle::Manager::builder("v1-sink-integration-test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .build();
    let handle = manager.register("v1_kafka", lifecycle::ComponentOptions::new());
    handle.report_healthy();
    let monitor = manager.monitor_background();

    let kafka_config = v1_kafka_config(topic);
    let producer = KafkaProducer::new(
        SinkName::Msk,
        &kafka_config,
        handle.clone(),
        CaptureMode::Events.as_tag(),
    )
    .expect("failed to create v1 KafkaProducer");

    let config = Config {
        produce_timeout: Duration::from_secs(10),
        kafka: kafka_config,
    };

    let sink = KafkaSink::new(
        SinkName::Msk,
        Arc::new(producer),
        config,
        CaptureMode::Events,
        handle,
    );

    (sink, monitor)
}

// ---------------------------------------------------------------------------
// Single realistic pageview round-trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_single_pageview_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let (sink, _monitor) = build_v1_sink(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-1");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = sink.publish_batch(&ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].key(), wrapped.uuid);
    assert_eq!(results[0].outcome(), Outcome::Success);

    let event_json = topic.next_event()?;
    let captured: CapturedEvent = serde_json::from_value(event_json)?;
    assert_eq!(captured.uuid, wrapped.uuid);
    assert_eq!(captured.distinct_id, "integ-user-1");
    assert_eq!(captured.event, "$pageview");
    assert_eq!(captured.token, "phc_integration_test_token");

    let data: RawEvent = serde_json::from_str(&captured.data)?;
    assert_eq!(data.event, "$pageview");
    assert_eq!(data.properties["$browser"], "Chrome");
    assert_eq!(
        data.properties["$session_id"],
        "01jq9abc-def0-1234-5678-9abcdef01234"
    );
    assert_eq!(data.properties["$process_person_profile"], true);
    assert_eq!(data.properties["custom_prop"], 42);

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// 3-event realistic batch round-trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_batch_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let (sink, _monitor) = build_v1_sink(topic.topic_name()).await;
    let ctx = v1_test_context();

    let batch = test_utils::realistic_batch();
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&batch[0], &batch[1], &batch[2]];

    let results = sink.publish_batch(&ctx, &events).await;

    assert_eq!(results.len(), 3);
    for r in &results {
        assert_eq!(r.outcome(), Outcome::Success);
    }

    let mut event_names = Vec::new();
    for _ in 0..3 {
        let json = topic.next_event()?;
        let captured: CapturedEvent = serde_json::from_value(json)?;
        let data: RawEvent = serde_json::from_str(&captured.data)?;
        assert_eq!(captured.distinct_id, "user-42");
        assert_eq!(captured.token, "phc_integration_test_token");
        event_names.push(data.event.clone());
    }

    event_names.sort();
    assert_eq!(
        event_names,
        vec!["$identify", "$pageview", "button_clicked"]
    );

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Verify Kafka headers round-trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_kafka_headers_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let (sink, _monitor) = build_v1_sink(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-headers");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = sink.publish_batch(&ctx, &events).await;
    assert_eq!(results[0].outcome(), Outcome::Success);

    let (_event_json, headers) = topic.next_message_with_headers()?;

    assert_eq!(
        headers.get("token").map(|s| s.as_str()),
        Some("phc_integration_test_token")
    );
    assert_eq!(
        headers.get("distinct_id").map(|s| s.as_str()),
        Some("integ-user-headers")
    );
    assert_eq!(headers.get("event").map(|s| s.as_str()), Some("$pageview"));
    assert!(headers.contains_key("uuid"));
    assert!(headers.contains_key("timestamp"));

    Ok(())
}

// ---------------------------------------------------------------------------
// Partition key verification
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_partition_key_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let (sink, _monitor) = build_v1_sink(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-pkey");
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = sink.publish_batch(&ctx, &events).await;
    assert_eq!(results[0].outcome(), Outcome::Success);

    let key = topic.next_message_key()?;
    assert_eq!(
        key.as_deref(),
        Some("phc_integration_test_token:integ-user-pkey")
    );

    Ok(())
}

// ---------------------------------------------------------------------------
// Dropped event not published
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_dropped_event_not_published() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let (sink, _monitor) = build_v1_sink(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-dropped").with_result(
        capture::v1::analytics::types::EventResult::Drop,
        Some("rate_limited"),
    );
    let events: Vec<&(dyn Event + Send + Sync)> = vec![&wrapped];

    let results = sink.publish_batch(&ctx, &events).await;
    assert!(results.is_empty());

    topic.assert_empty();
    Ok(())
}
