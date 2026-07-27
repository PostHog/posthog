//! Produce-level integration tests for the v1 analytics pipeline over the
//! converged outputs machinery:
//!   WrappedEvent -> to_processed -> KafkaOutputs.publish -> real Kafka ->
//!   consumer -> CapturedEvent
//!
//! Requires Docker Kafka (same rig as legacy integration tests).
//!
//! HTTP-level round trips (POST /i/v1/analytics/events -> Kafka) live in
//! `v1_http_integration.rs`; this file stays focused on the produce layer.

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use common_types::{CapturedEvent, RawEvent};

use capture::outputs::kafka::KafkaOutputs;
use capture::outputs::topics::TopicTable;
use capture::outputs::Outputs;
use capture::sinks::SinkResult;
use capture::v1::analytics::types::WrappedEvent;
use capture::v1::context::RequestContext;
use capture::v1::test_utils::{self, WrappedEventMut};

fn v1_kafka_config(topic: &str) -> capture::v1::sinks::kafka::config::Config {
    let env: std::collections::HashMap<String, String> = [
        ("HOSTS", "kafka:9092"),
        ("TOPIC_MAIN", topic),
        ("TOPIC_HISTORICAL", topic),
        ("TOPIC_OVERFLOW", topic),
        ("TOPIC_DLQ", topic),
        ("TOPIC_EXCEPTION", topic),
        ("TOPIC_HEATMAP", topic),
        ("TOPIC_CLIENT_INGESTION_WARNING", topic),
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

fn v1_test_context() -> RequestContext {
    let mut ctx = test_utils::test_context();
    ctx.api_token = "phc_integration_test_token".to_string();
    ctx
}

async fn build_v1_surface(topic: &str) -> KafkaOutputs {
    let v1_config = v1_kafka_config(topic);
    let kafka_config = v1_config
        .to_kafka_config()
        .expect("v1 config must map onto the shared KafkaConfig");
    let topics = TopicTable::from(&v1_config);
    KafkaOutputs::new(kafka_config, topics, None)
        .await
        .expect("failed to create Kafka outputs")
}

/// The converged publish path exactly as the v1 request path runs it: map
/// publishable events onto the shared interchange, publish.
async fn publish(
    surface: &KafkaOutputs,
    ctx: &RequestContext,
    events: &[WrappedEvent],
) -> Vec<SinkResult> {
    let processed = events
        .iter()
        .filter(|e| e.should_publish())
        .map(|e| e.to_processed(ctx).expect("mapping must succeed"))
        .collect();
    surface.publish(processed).await
}

// ---------------------------------------------------------------------------
// Single realistic pageview round-trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_single_pageview_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-1");
    let events = vec![wrapped];

    let results = publish(&surface, &ctx, &events).await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].uuid, events[0].uuid);
    assert!(results[0].result.is_ok());

    let event_json = topic.next_event()?;
    let captured: CapturedEvent = serde_json::from_value(event_json)?;
    assert_eq!(captured.uuid, events[0].uuid);
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
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let batch = test_utils::realistic_batch();
    let events = batch;

    let results = publish(&surface, &ctx, &events).await;

    assert_eq!(results.len(), 3);
    for r in &results {
        assert!(r.result.is_ok());
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
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-headers");
    let events = vec![wrapped];

    let results = publish(&surface, &ctx, &events).await;
    assert!(results[0].result.is_ok());

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
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-pkey");
    let events = vec![wrapped];

    let results = publish(&surface, &ctx, &events).await;
    assert!(results[0].result.is_ok());

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
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let wrapped = test_utils::realistic_pageview("integ-user-dropped").with_result(
        capture::v1::analytics::types::EventResult::Drop,
        Some("rate_limited"),
    );
    let events = vec![wrapped];

    let results = publish(&surface, &ctx, &events).await;
    assert!(results.is_empty());

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Exception event routes to exception topic
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_exception_event_round_trip() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let uuid = uuid::Uuid::new_v4();
    let mut wrapped = test_utils::realistic_pageview("integ-user-exception");
    wrapped.event.event = "$exception".to_string();
    wrapped.uuid = uuid;
    wrapped.event.uuid = uuid.to_string();
    wrapped.destination = capture::v1::sinks::Destination::ExceptionErrorTracking;

    let events = vec![wrapped];
    let results = publish(&surface, &ctx, &events).await;
    assert_eq!(results.len(), 1);
    assert!(results[0].result.is_ok());

    let event_json = topic.next_event()?;
    let captured: CapturedEvent = serde_json::from_value(event_json)?;
    assert_eq!(captured.event, "$exception");
    assert_eq!(captured.uuid, uuid);
    assert_eq!(captured.distinct_id, "integ-user-exception");

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Cookieless mode affects partition key
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_cookieless_mode_partition_key() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let mut ctx = v1_test_context();
    ctx.client_ip = "198.51.100.7".parse().unwrap();

    let uuid = uuid::Uuid::new_v4();
    let mut wrapped = test_utils::realistic_pageview("integ-user-cookieless");
    wrapped.uuid = uuid;
    wrapped.event.uuid = uuid.to_string();
    wrapped.options.cookieless_mode = Some(true);

    let events = vec![wrapped];
    let results = publish(&surface, &ctx, &events).await;
    assert!(results[0].result.is_ok());

    let key = topic.next_message_key()?;
    assert_eq!(
        key.as_deref(),
        Some("phc_integration_test_token:198.51.100.7"),
        "cookieless mode should use token:IP as partition key"
    );

    Ok(())
}

// ---------------------------------------------------------------------------
// Event with all options fields set — property injection round-trip
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_all_options_property_injection() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let uuid = uuid::Uuid::new_v4();
    let mut wrapped = test_utils::realistic_pageview("integ-user-all-opts");
    wrapped.uuid = uuid;
    wrapped.event.uuid = uuid.to_string();
    wrapped.options = capture::v1::analytics::types::Options {
        cookieless_mode: Some(true),
        disable_skew_correction: Some(true),
        product_tour_id: Some("tour_abc123".to_string()),
        process_person_profile: Some(false),
    };
    wrapped.event.session_id = Some("sess-opt-test".to_string());
    wrapped.event.window_id = Some("win-opt-test".to_string());

    let events = vec![wrapped];
    let results = publish(&surface, &ctx, &events).await;
    assert!(results[0].result.is_ok());

    let event_json = topic.next_event()?;
    let captured: CapturedEvent = serde_json::from_value(event_json)?;
    let data: RawEvent = serde_json::from_str(&captured.data)?;

    assert_eq!(data.properties["$session_id"], "sess-opt-test");
    assert_eq!(data.properties["$window_id"], "win-opt-test");
    assert_eq!(data.properties["$cookieless_mode"], true);
    assert_eq!(data.properties["$ignore_sent_at"], true);
    assert_eq!(data.properties["$product_tour_id"], "tour_abc123");
    assert_eq!(data.properties["$process_person_profile"], false);

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Event with empty options — no extra properties injected from options
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_empty_options_no_injection() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let uuid = uuid::Uuid::new_v4();
    let mut wrapped = test_utils::realistic_pageview("integ-user-no-opts");
    wrapped.uuid = uuid;
    wrapped.event.uuid = uuid.to_string();
    wrapped.options = capture::v1::analytics::types::Options {
        cookieless_mode: None,
        disable_skew_correction: None,
        product_tour_id: None,
        process_person_profile: None,
    };
    wrapped.event.session_id = None;
    wrapped.event.window_id = None;

    let events = vec![wrapped];
    let results = publish(&surface, &ctx, &events).await;
    assert!(results[0].result.is_ok());

    let event_json = topic.next_event()?;
    let captured: CapturedEvent = serde_json::from_value(event_json)?;
    let data: RawEvent = serde_json::from_str(&captured.data)?;

    assert!(!data.properties.contains_key("$session_id"));
    assert!(!data.properties.contains_key("$window_id"));
    assert!(!data.properties.contains_key("$cookieless_mode"));
    assert!(!data.properties.contains_key("$ignore_sent_at"));
    assert!(!data.properties.contains_key("$product_tour_id"));
    assert!(!data.properties.contains_key("$process_person_profile"));

    topic.assert_empty();
    Ok(())
}

// ---------------------------------------------------------------------------
// Multi-destination batch — events route correctly
// ---------------------------------------------------------------------------

#[tokio::test]
async fn v1_multi_destination_batch() -> Result<()> {
    setup_tracing();
    let topic = EphemeralTopic::new().await;
    let surface = build_v1_surface(topic.topic_name()).await;
    let ctx = v1_test_context();

    let main_ev = test_utils::realistic_pageview("integ-dest-main");
    let hist_ev = test_utils::realistic_pageview("integ-dest-hist")
        .with_destination(capture::v1::sinks::Destination::AnalyticsHistorical);
    let overflow_ev = test_utils::realistic_pageview("integ-dest-overflow")
        .with_destination(capture::v1::sinks::Destination::Overflow);

    let events = vec![main_ev, hist_ev, overflow_ev];
    let results = publish(&surface, &ctx, &events).await;
    assert_eq!(results.len(), 3);
    for r in &results {
        assert!(r.result.is_ok());
    }

    let mut distinct_ids = Vec::new();
    for _ in 0..3 {
        let json = topic.next_event()?;
        let captured: CapturedEvent = serde_json::from_value(json)?;
        distinct_ids.push(captured.distinct_id.clone());
    }
    distinct_ids.sort();
    assert_eq!(
        distinct_ids,
        vec!["integ-dest-hist", "integ-dest-main", "integ-dest-overflow"]
    );

    topic.assert_empty();
    Ok(())
}
