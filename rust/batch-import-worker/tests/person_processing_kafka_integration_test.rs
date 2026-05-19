//! Integration test for person processing filter with Kafka emission
//!
//! Tests that when FORCE_DISABLE_PERSON_PROCESSING env var is set,
//! events matching token:distinct_id pairs are sent to Kafka without a key
//! and with force_disable_person_processing header set to true.
//!
//! Requires Kafka running at localhost:9092. Skips if Kafka is unreachable.

use anyhow::Result;
use batch_import_worker::{
    config::Config,
    context::AppContext,
    emit::{kafka::KafkaEmitter, Emitter},
    job::config::KafkaEmitterConfig,
};
use common_types::{CapturedEvent, CapturedEventHeaders, InternallyCapturedEvent};
use envconfig::Envconfig;
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    message::Message,
};
use std::sync::{Arc, OnceLock};
use std::time::Duration;
use tokio::sync::Mutex as TokioMutex;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";

// Global mutex to serialize Kafka integration tests
static KAFKA_TEST_MUTEX: OnceLock<TokioMutex<()>> = OnceLock::new();

/// Helper to create Kafka topics before tests
async fn create_kafka_topic(topic: &str) -> Result<()> {
    let admin_client: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topic = NewTopic::new(topic, 1, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    match admin_client.create_topics(&[new_topic], &opts).await {
        Ok(results) => {
            for result in results {
                match result {
                    Ok(topic) => println!("Created topic: {topic}"),
                    Err((topic, error)) => {
                        println!("Topic {topic} result: {error:?}");
                    }
                }
            }
        }
        Err(e) => {
            println!("Failed to create topic: {e:?}");
        }
    }

    Ok(())
}

/// Create test events
fn create_test_events() -> Vec<InternallyCapturedEvent> {
    vec![
        InternallyCapturedEvent {
            inner: CapturedEvent {
                uuid: Uuid::new_v4(),
                distinct_id: "user1".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: r#"{"event":"test_event","properties":{}}"#.to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "token1".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
                is_cookieless_mode: false,
                historical_migration: false,
            },
            team_id: 1,
        },
        InternallyCapturedEvent {
            inner: CapturedEvent {
                uuid: Uuid::new_v4(),
                distinct_id: "user2".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: r#"{"event":"test_event","properties":{}}"#.to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "token1".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
                is_cookieless_mode: false,
                historical_migration: false,
            },
            team_id: 1,
        },
        InternallyCapturedEvent {
            inner: CapturedEvent {
                uuid: Uuid::new_v4(),
                distinct_id: "user3".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: r#"{"event":"test_event","properties":{}}"#.to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "token2".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
                is_cookieless_mode: false,
                historical_migration: false,
            },
            team_id: 1,
        },
    ]
}

/// Consume messages from Kafka topic and return them with their keys, headers, and payload
async fn consume_messages_with_metadata(
    topic: &str,
    expected_count: usize,
    timeout: Duration,
) -> Result<Vec<(Option<String>, CapturedEventHeaders, String)>> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", format!("test-{}", Uuid::new_v4()))
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .create()?;

    consumer.subscribe(&[topic])?;

    let mut messages = Vec::new();
    let start = std::time::Instant::now();

    while start.elapsed() < timeout && messages.len() < expected_count {
        match tokio::time::timeout(Duration::from_millis(100), consumer.recv()).await {
            Ok(Ok(msg)) => {
                let key = msg.key().map(|k| String::from_utf8_lossy(k).to_string());
                let headers = msg
                    .headers()
                    .map(|h| CapturedEventHeaders::from(h.detach()));
                let payload = msg
                    .payload()
                    .map(|p| String::from_utf8_lossy(p).to_string())
                    .unwrap_or_default();

                if let Some(headers) = headers {
                    messages.push((key, headers, payload));
                }
            }
            Ok(Err(e)) => {
                if !matches!(e, rdkafka::error::KafkaError::NoMessageReceived) {
                    println!("Error consuming message: {e:?}");
                }
            }
            Err(_) => {}
        }
    }

    Ok(messages)
}

#[tokio::test]
async fn test_person_processing_filter_with_kafka() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let topic = format!("test-person-processing-{}", Uuid::new_v4());
    create_kafka_topic(&topic).await?;

    // Create a mock config with the person processing filter
    std::env::set_var(
        "FORCE_DISABLE_PERSON_PROCESSING",
        "token1:user1,token2:user3",
    );
    std::env::set_var("KAFKA_HOSTS", KAFKA_BROKERS);
    std::env::set_var(
        "DATABASE_URL",
        "postgres://posthog:posthog@localhost:5432/posthog",
    );

    let config = Config::init_from_env()?;
    let context = Arc::new(AppContext::new(&config).await?);

    // Create KafkaEmitter
    let emitter_config = KafkaEmitterConfig {
        topic: topic.clone(),
        send_rate: 1000,
        transaction_timeout_seconds: 60,
    };

    let mut emitter = KafkaEmitter::new(emitter_config, "test-txn-id", context).await?;

    // Emit test events
    let events = create_test_events();
    let txn = emitter.begin_write().await?;
    txn.emit(&events).await?;
    txn.commit_write().await?;

    // Consume messages and verify
    let messages = consume_messages_with_metadata(&topic, 3, Duration::from_secs(10)).await?;

    assert_eq!(messages.len(), 3, "Should have received 3 messages");

    // Verify all payloads deserialize as InternallyCapturedEvent (not as a tuple/array)
    for (i, (_, _, payload)) in messages.iter().enumerate() {
        let parsed: serde_json::Value =
            serde_json::from_str(payload).expect("payload should be valid JSON");
        assert!(
            parsed.is_object(),
            "Message {i} payload should be a JSON object, got: {payload}"
        );
        let deserialized: InternallyCapturedEvent =
            serde_json::from_str(payload).unwrap_or_else(|e| {
                panic!("Message {i} payload should deserialize as InternallyCapturedEvent: {e}")
            });
        assert_eq!(deserialized.inner.token, events[i].inner.token);
        assert_eq!(deserialized.inner.distinct_id, events[i].inner.distinct_id);
    }

    // Event 1: token1:user1 should have no key and force_disable_person_processing=true
    let (key1, headers1, _) = &messages[0];
    assert!(key1.is_none(), "First event should have no key");
    assert_eq!(
        headers1.force_disable_person_processing,
        Some(true),
        "First event should have force_disable_person_processing=true"
    );
    assert_eq!(headers1.token, Some("token1".to_string()));
    assert_eq!(headers1.distinct_id, Some("user1".to_string()));

    // Event 2: token1:user2 should have a key and no force_disable_person_processing
    let (key2, headers2, _) = &messages[1];
    assert!(
        key2.is_some(),
        "Second event should have a key (not in filter)"
    );
    assert_eq!(
        headers2.force_disable_person_processing, None,
        "Second event should not have force_disable_person_processing header"
    );
    assert_eq!(headers2.token, Some("token1".to_string()));
    assert_eq!(headers2.distinct_id, Some("user2".to_string()));

    // Event 3: token2:user3 should have no key and force_disable_person_processing=true
    let (key3, headers3, _) = &messages[2];
    assert!(key3.is_none(), "Third event should have no key");
    assert_eq!(
        headers3.force_disable_person_processing,
        Some(true),
        "Third event should have force_disable_person_processing=true"
    );
    assert_eq!(headers3.token, Some("token2".to_string()));
    assert_eq!(headers3.distinct_id, Some("user3".to_string()));

    // Clean up env vars
    std::env::remove_var("FORCE_DISABLE_PERSON_PROCESSING");

    Ok(())
}

#[tokio::test]
async fn test_empty_person_processing_filter() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let topic = format!("test-person-processing-empty-{}", Uuid::new_v4());
    create_kafka_topic(&topic).await?;

    // Empty filter - all events should have keys
    std::env::set_var("FORCE_DISABLE_PERSON_PROCESSING", "");
    std::env::set_var("KAFKA_HOSTS", KAFKA_BROKERS);
    std::env::set_var(
        "DATABASE_URL",
        "postgres://posthog:posthog@localhost:5432/posthog",
    );

    let config = Config::init_from_env()?;
    let context = Arc::new(AppContext::new(&config).await?);

    let emitter_config = KafkaEmitterConfig {
        topic: topic.clone(),
        send_rate: 1000,
        transaction_timeout_seconds: 60,
    };

    let mut emitter = KafkaEmitter::new(emitter_config, "test-txn-id-2", context).await?;

    let events = create_test_events();
    let txn = emitter.begin_write().await?;
    txn.emit(&events).await?;
    txn.commit_write().await?;

    let messages = consume_messages_with_metadata(&topic, 3, Duration::from_secs(10)).await?;

    assert_eq!(messages.len(), 3, "Should have received 3 messages");

    // All events should have keys and no force_disable_person_processing header
    for (key, headers, payload) in &messages {
        assert!(key.is_some(), "All events should have keys");
        assert_eq!(
            headers.force_disable_person_processing, None,
            "No events should have force_disable_person_processing header"
        );
        let parsed: serde_json::Value =
            serde_json::from_str(payload).expect("payload should be valid JSON");
        assert!(
            parsed.is_object(),
            "Payload should be a JSON object, got: {payload}"
        );
    }

    std::env::remove_var("FORCE_DISABLE_PERSON_PROCESSING");

    Ok(())
}
