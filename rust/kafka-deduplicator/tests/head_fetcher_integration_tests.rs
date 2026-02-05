//! Integration tests for HeadFetcher - one-shot head-of-log fetching.
//!
//! These tests require a running Kafka instance (typically via docker-compose).

use std::time::Duration;

use common_types::CapturedEvent;
use kafka_deduplicator::kafka::head_fetcher::PartitionFetchResult;
use kafka_deduplicator::kafka::{ConsumerConfigBuilder, HeadFetcher};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use time::OffsetDateTime;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC_BASE: &str = "kdedup-head-fetcher-integration-test";
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(5);

/// Helper to create a topic with specific number of partitions
async fn create_topic_with_partitions(topic: &str, num_partitions: i32) -> anyhow::Result<()> {
    let admin_client: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topic = NewTopic::new(topic, num_partitions, TopicReplication::Fixed(1));
    let opts = AdminOptions::new();

    let results = admin_client.create_topics(&[new_topic], &opts).await?;
    for result in results {
        match result {
            Ok(_) => {}
            Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((topic, e)) => {
                return Err(anyhow::anyhow!("Failed to create topic {}: {:?}", topic, e))
            }
        }
    }

    // Give Kafka time to create partitions and propagate metadata
    tokio::time::sleep(Duration::from_millis(200)).await;
    Ok(())
}

/// Create a test CapturedEvent with unique identifiers
fn create_captured_event() -> CapturedEvent {
    let now = std::time::SystemTime::now();
    let now_offset_datetime = OffsetDateTime::from(now);
    let now_rfc3339 = chrono::DateTime::<chrono::Utc>::from(now).to_rfc3339();
    let distinct_id = Uuid::now_v7().to_string();
    let token = Uuid::now_v7().to_string();
    let event_name = "$pageview";
    let event_uuid = Uuid::now_v7();
    let data = format!(
        r#"{{"uuid": "{event_uuid}", "event": "{event_name}", "distinct_id": "{distinct_id}", "token": "{token}", "properties": {{}}}}"#,
    );

    CapturedEvent {
        uuid: event_uuid,
        distinct_id: distinct_id.to_string(),
        session_id: None,
        ip: "127.0.0.1".to_string(),
        now: now_rfc3339,
        token: token.to_string(),
        data,
        sent_at: Some(now_offset_datetime),
        event: event_name.to_string(),
        timestamp: chrono::Utc::now(),
        is_cookieless_mode: false,
        historical_migration: false,
    }
}

/// Send a test message to a specific partition
async fn send_message_to_partition(
    topic: &str,
    partition: i32,
    event: &CapturedEvent,
) -> anyhow::Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    let serialized = serde_json::to_string(event)?;
    let key = event.uuid.to_string();
    let record = FutureRecord::to(topic)
        .partition(partition)
        .key(&key)
        .payload(&serialized);

    producer
        .send(record, Timeout::After(Duration::from_secs(5)))
        .await
        .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;

    // Flush to ensure message is fully sent
    producer.flush(Timeout::After(Duration::from_secs(5)))?;

    // Small delay for message propagation
    tokio::time::sleep(Duration::from_millis(50)).await;
    Ok(())
}

/// Create a HeadFetcher with default test config
fn create_head_fetcher() -> HeadFetcher {
    create_head_fetcher_with_timeout(DEFAULT_TIMEOUT)
}

/// Create a HeadFetcher with custom timeout
fn create_head_fetcher_with_timeout(timeout: Duration) -> HeadFetcher {
    let config = ConsumerConfigBuilder::new_for_fetch(KAFKA_BROKERS).build_for_fetch();
    HeadFetcher::new(config, timeout)
}

#[tokio::test]
async fn test_fetch_head_from_empty_partition() -> anyhow::Result<()> {
    // Create unique topic to ensure it's empty
    let topic = format!("{}-empty-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    let fetcher = create_head_fetcher();

    // Fetch from empty partition - should return Empty result
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;

    assert_eq!(results.len(), 1);
    let (partition, result) = &results[0];
    assert_eq!(*partition, 0);
    assert!(
        matches!(result, PartitionFetchResult::Empty),
        "Empty partition should return Empty result"
    );

    Ok(())
}

#[tokio::test]
async fn test_fetch_head_from_single_partition() -> anyhow::Result<()> {
    let topic = format!("{}-single-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    // Send multiple messages to partition 0
    let event1 = create_captured_event();
    let event2 = create_captured_event();
    let event3 = create_captured_event();

    send_message_to_partition(&topic, 0, &event1).await?;
    send_message_to_partition(&topic, 0, &event2).await?;
    send_message_to_partition(&topic, 0, &event3).await?;

    let fetcher = create_head_fetcher();

    // Fetch head - should get the last message (event3)
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;

    assert_eq!(results.len(), 1);
    let (partition, result) = &results[0];
    assert_eq!(*partition, 0);
    assert!(
        result.is_success(),
        "Should get the head message, got: {:?}",
        result
    );

    let kafka_msg = match result {
        PartitionFetchResult::Success(msg) => msg,
        _ => panic!("Expected Success result"),
    };
    let event = kafka_msg
        .get_message()
        .expect("Should have deserialized event");
    assert_eq!(event.uuid, event3.uuid, "Should get the latest message");

    Ok(())
}

#[tokio::test]
async fn test_fetch_head_from_multiple_partitions() -> anyhow::Result<()> {
    let topic = format!("{}-multi-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 3).await?;

    // Send different messages to each partition
    let events: Vec<CapturedEvent> = (0..3).map(|_| create_captured_event()).collect();

    send_message_to_partition(&topic, 0, &events[0]).await?;
    send_message_to_partition(&topic, 1, &events[1]).await?;
    send_message_to_partition(&topic, 2, &events[2]).await?;

    let fetcher = create_head_fetcher();

    // Fetch head from all 3 partitions
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0, 1, 2])?;

    assert_eq!(results.len(), 3);

    // Verify each partition got the correct head message
    for (partition, result) in results {
        assert!(
            result.is_success(),
            "Partition {} should have a message, got: {:?}",
            partition,
            result
        );
        let kafka_msg = match result {
            PartitionFetchResult::Success(msg) => msg,
            _ => panic!("Expected Success result for partition {}", partition),
        };
        let event = kafka_msg
            .get_message()
            .expect("Should have deserialized event");
        assert_eq!(
            event.uuid, events[partition as usize].uuid,
            "Partition {} should have its head message",
            partition
        );
    }

    Ok(())
}

#[tokio::test]
async fn test_fetch_head_partial_partitions() -> anyhow::Result<()> {
    // Test fetching only some partitions from a topic with more partitions
    let topic = format!("{}-partial-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 4).await?;

    // Only send messages to partitions 1 and 3
    let event1 = create_captured_event();
    let event3 = create_captured_event();

    send_message_to_partition(&topic, 1, &event1).await?;
    send_message_to_partition(&topic, 3, &event3).await?;

    let fetcher = create_head_fetcher();

    // Fetch head only from partitions 0 and 1 (0 empty, 1 has message)
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0, 1])?;

    assert_eq!(results.len(), 2);

    // Partition 0 should be empty
    let (p0, result0) = &results[0];
    assert_eq!(*p0, 0);
    assert!(
        matches!(result0, PartitionFetchResult::Empty),
        "Partition 0 should be empty"
    );

    // Partition 1 should have the message
    let (p1, result1) = &results[1];
    assert_eq!(*p1, 1);
    assert!(result1.is_success(), "Partition 1 should have message");
    let kafka_msg = match result1 {
        PartitionFetchResult::Success(msg) => msg,
        _ => panic!("Expected Success result"),
    };
    let event = kafka_msg
        .get_message()
        .expect("Should have deserialized event");
    assert_eq!(event.uuid, event1.uuid);

    Ok(())
}

#[tokio::test]
async fn test_fetch_head_deserialization_failure() -> anyhow::Result<()> {
    let topic = format!("{}-bad-json-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    // Send invalid JSON to the partition
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    let invalid_json = "this is not valid json";
    let record = FutureRecord::to(&topic)
        .partition(0)
        .key("bad-key")
        .payload(invalid_json);

    producer
        .send(record, Timeout::After(Duration::from_secs(5)))
        .await
        .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;

    tokio::time::sleep(Duration::from_millis(50)).await;

    let fetcher = create_head_fetcher();

    // Fetch should return DeserializationError
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;

    assert_eq!(results.len(), 1);
    let (partition, result) = &results[0];
    assert_eq!(*partition, 0);
    assert!(
        matches!(result, PartitionFetchResult::DeserializationError(_)),
        "Should return DeserializationError, got: {:?}",
        result.result_type()
    );

    Ok(())
}

#[tokio::test]
async fn test_fetch_head_fresh_consumer_per_call() -> anyhow::Result<()> {
    // Verify that each fetch call gets fresh metadata by sending messages between calls
    let topic = format!("{}-fresh-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    let fetcher = create_head_fetcher();

    // First fetch - should be empty
    let results1 = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;
    assert!(
        matches!(results1[0].1, PartitionFetchResult::Empty),
        "First fetch should be empty"
    );

    // Send a message
    let event = create_captured_event();
    send_message_to_partition(&topic, 0, &event).await?;

    // Second fetch - should get the new message (proves fresh consumer was created)
    let results2 = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;
    assert!(
        results2[0].1.is_success(),
        "Second fetch should get the new message"
    );
    let kafka_msg = match &results2[0].1 {
        PartitionFetchResult::Success(msg) => msg,
        _ => panic!("Expected Success result"),
    };
    let fetched_event = kafka_msg
        .get_message()
        .expect("Should have deserialized event");
    assert_eq!(fetched_event.uuid, event.uuid);

    Ok(())
}

#[tokio::test]
async fn test_head_fetcher_clone() -> anyhow::Result<()> {
    // Verify that cloned HeadFetcher works correctly
    let topic = format!("{}-clone-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    let event = create_captured_event();
    send_message_to_partition(&topic, 0, &event).await?;

    let fetcher = create_head_fetcher();
    let cloned_fetcher = fetcher.clone();

    // Both should work independently
    let results1 = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;
    let results2 = cloned_fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;

    assert!(
        results1[0].1.is_success(),
        "First fetch failed: type={:?}, details={:?}",
        results1[0].1.result_type(),
        results1[0].1
    );
    assert!(
        results2[0].1.is_success(),
        "Second fetch failed: type={:?}, details={:?}",
        results2[0].1.result_type(),
        results2[0].1
    );

    let uuid1 = match &results1[0].1 {
        PartitionFetchResult::Success(msg) => msg.get_message().unwrap().uuid,
        _ => panic!("Expected Success"),
    };
    let uuid2 = match &results2[0].1 {
        PartitionFetchResult::Success(msg) => msg.get_message().unwrap().uuid,
        _ => panic!("Expected Success"),
    };

    assert_eq!(uuid1, uuid2, "Both should get the same head message");
    assert_eq!(uuid1, event.uuid);

    Ok(())
}

#[tokio::test]
async fn test_partition_fetch_result_methods() -> anyhow::Result<()> {
    // Test the PartitionFetchResult helper methods
    let topic = format!("{}-result-methods-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    create_topic_with_partitions(&topic, 1).await?;

    let event = create_captured_event();
    send_message_to_partition(&topic, 0, &event).await?;

    let fetcher = create_head_fetcher();
    let results = fetcher.fetch_head_messages::<CapturedEvent>(&topic, &[0])?;

    let (partition, result) = results.into_iter().next().unwrap();
    assert!(
        result.is_success(),
        "Expected success for partition {}, got: {:?}",
        partition,
        result.result_type()
    );
    assert!(!result.is_timeout());
    assert_eq!(result.result_type(), "success");

    // Test into_message consumes and returns the message
    let msg = result.into_message();
    assert!(msg.is_some());

    Ok(())
}
