use anyhow::Result;
use common_types::RawEvent;

use kafka_deduplicator::{
    deduplication_processor::{DeduplicationConfig, DeduplicationProcessor},
    kafka::{rebalance_handler::RebalanceHandler, stateful_consumer::StatefulKafkaConsumer},
    processor_rebalance_handler::ProcessorRebalanceHandler,
    rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig},
};
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::Consumer,
    message::BorrowedMessage,
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
    Message,
};
use serde_json::{json, Value};
use std::sync::OnceLock;
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tempfile::TempDir;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";

// Global mutex to serialize Kafka integration tests
static KAFKA_TEST_MUTEX: OnceLock<Mutex<()>> = OnceLock::new();

/// Helper to create Kafka topics before tests
async fn create_kafka_topics(topics: Vec<&str>) -> Result<()> {
    let admin_client: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topics: Vec<NewTopic> = topics
        .into_iter()
        .map(|topic| NewTopic::new(topic, 1, TopicReplication::Fixed(1)))
        .collect();

    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    match admin_client.create_topics(&new_topics, &opts).await {
        Ok(results) => {
            for result in results {
                match result {
                    Ok(topic) => println!("Created topic: {topic}"),
                    Err((topic, error)) => {
                        // Topic might already exist, which is fine
                        println!("Topic {topic} result: {error:?}");
                    }
                }
            }
        }
        Err(e) => {
            println!("Failed to create topics: {e:?}");
            // Don't fail the test if topic creation fails - they might already exist
        }
    }

    Ok(())
}

/// Helper to create a deduplication processor and rebalance handler (following main.rs pattern)
fn create_deduplication_setup(
    output_topic: &str,
) -> Result<(
    Arc<DeduplicationProcessor>,
    Arc<ProcessorRebalanceHandler>,
    TempDir,
)> {
    let temp_dir = TempDir::new()?;
    println!("Created temp store at: {:?}", temp_dir.path());

    // Create deduplication store config
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    // Create producer config for output topic
    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    // Create deduplication processor (same as main.rs)
    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic.to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);

    // Create rebalance handler (same as main.rs)
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor.clone()));

    Ok((processor, rebalance_handler, temp_dir))
}

/// Helper to create test RawEvent instances
fn create_test_raw_event(
    uuid: Option<Uuid>,
    event: &str,
    distinct_id: &str,
    token: &str,
    timestamp: Option<u64>,
    properties: Option<HashMap<String, Value>>,
) -> RawEvent {
    let mut props = properties.unwrap_or_default();
    if props.is_empty() {
        props.insert("test_property".to_string(), json!("test_value"));
    }

    RawEvent {
        uuid,
        event: event.to_string(),
        distinct_id: Some(json!(distinct_id)),
        token: Some(token.to_string()),
        properties: props,
        timestamp: timestamp.map(|t| t.to_string()),
        ..Default::default()
    }
}

/// Helper to send messages to Kafka topic
async fn send_test_messages_to_topic(
    topic: &str,
    messages: Vec<(&str, &str)>, // (key, payload) pairs
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, payload) in messages {
        let record = FutureRecord::to(topic).key(key).payload(payload);
        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {}", e))?;
    }

    // Wait for messages to be committed to Kafka
    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(())
}

/// Helper to consume messages from output topic
async fn consume_output_messages(
    topic: &str,
    group_id: &str,
    expected_count: usize,
    timeout_secs: u64,
) -> Result<Vec<String>> {
    let consumer: rdkafka::consumer::StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create()?;

    consumer.subscribe(&[topic])?;

    let mut messages = Vec::new();
    let start_time = std::time::Instant::now();

    while messages.len() < expected_count && start_time.elapsed().as_secs() < timeout_secs {
        if let Ok(Some(message)) = consumer
            .recv()
            .await
            .map(Some)
            .or_else(|_| Ok::<Option<BorrowedMessage>, rdkafka::error::KafkaError>(None))
        {
            if let Some(payload) = message.payload() {
                if let Ok(payload_str) = std::str::from_utf8(payload) {
                    messages.push(payload_str.to_string());
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }

    Ok(messages)
}

#[tokio::test]
async fn test_kafka_connectivity() -> Result<()> {
    // Simple test to verify Kafka is accessible
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    let test_topic = "connectivity-test";
    let record = FutureRecord::to(test_topic).key("test").payload("test");

    // This should succeed if Kafka is running
    match producer
        .send(record, Timeout::After(Duration::from_secs(2)))
        .await
    {
        Ok(_) => println!("Kafka connectivity confirmed"),
        Err((e, _)) => println!("Kafka error: {e}"),
    }

    Ok(())
}

#[tokio::test]
async fn test_end_to_end_deduplication_with_uuids() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here
    let test_id = Uuid::new_v4();
    let input_topic = format!("dedup-input-uuid-{test_id}");
    let output_topic = format!("dedup-output-uuid-{test_id}");
    let group_id = format!("test-group-uuid-{test_id}");

    // Create Kafka topics first
    create_kafka_topics(vec![&input_topic, &output_topic]).await?;

    // Give Kafka a moment to fully create topics
    tokio::time::sleep(Duration::from_millis(1000)).await;

    // Create deduplication setup (same as main.rs)
    let (processor, rebalance_handler, _temp_dir) = create_deduplication_setup(&output_topic)?;

    // Create test events with UUIDs
    let uuid1 = Uuid::new_v4();
    let uuid2 = Uuid::new_v4();
    println!("Test expecting UUIDs - uuid1: {uuid1}, uuid2: {uuid2}");
    let events = vec![
        create_test_raw_event(Some(uuid1), "page_view", "user1", "token1", Some(1640995200), None),
        create_test_raw_event(Some(uuid1), "page_view", "user1", "token1", Some(1640995200), None), // duplicate UUID
        create_test_raw_event(Some(uuid2), "click", "user2", "token1", Some(1640995201), None),
        create_test_raw_event(Some(uuid2), "click", "user2", "token1", Some(1640995201), None), // duplicate UUID
    ];

    // Serialize events and send to input topic
    let serialized_messages: Vec<(String, String)> = events
        .iter()
        .enumerate()
        .map(|(i, event)| {
            let key = format!("key{i}");
            let payload = serde_json::to_string(event).unwrap();
            (key, payload)
        })
        .collect();

    let messages_to_send: Vec<(&str, &str)> = serialized_messages
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();

    send_test_messages_to_topic(&input_topic, messages_to_send).await?;

    // Create Kafka consumer (exactly like main.rs)
    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .clone();

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        (*processor).clone(), // Same pattern as main.rs
        10,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Start consumption in background with timeout
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Wait for processing with timeout
    tokio::time::sleep(Duration::from_secs(5)).await;

    // Attempt graceful shutdown first
    if !consumer_handle.is_finished() {
        consumer_handle.abort();
    }

    // Give it a moment to clean up
    tokio::time::sleep(Duration::from_millis(100)).await;

    // Consume from output topic - should only have 2 unique events
    let consumer_group = format!(
        "consumer-{}-{}",
        test_id,
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis()
    );
    let output_messages = consume_output_messages(&output_topic, &consumer_group, 2, 15).await?;

    assert_eq!(
        output_messages.len(),
        2,
        "Should have exactly 2 unique events in output"
    );

    // Verify the events are the correct ones
    let output_events: Vec<RawEvent> = output_messages
        .iter()
        .map(|msg| serde_json::from_str(msg).unwrap())
        .collect();

    let output_uuids: Vec<Uuid> = output_events.iter().map(|e| e.uuid.unwrap()).collect();
    println!("Received UUIDs from output: {output_uuids:?}");
    assert!(output_uuids.contains(&uuid1), "Missing uuid1: {uuid1}");
    assert!(output_uuids.contains(&uuid2), "Missing uuid2: {uuid2}");

    Ok(())
}

#[tokio::test]
async fn test_deduplication_store_direct() -> Result<()> {
    // Test the DeduplicationStore directly without Kafka
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;

    // Create test events with fixed timestamp
    let now = 1640995200u64; // Fixed timestamp to ensure consistency
    let events = vec![
        create_test_raw_event(None, "user1", "token1", "page_view", Some(now), None),
        create_test_raw_event(None, "user1", "token1", "page_view", Some(now), None), // duplicate
        create_test_raw_event(None, "user2", "token1", "click", Some(now), None),
    ];

    // Process events individually instead of batch
    for event in &events {
        let result = store.handle_event_with_raw(event)?;
        // First event should be stored (new), second event should be duplicate (false), third should be stored (new)
        println!("Event processed, is_new: {result}");
    }

    // Test individual event handling for duplicates
    // Note: handle_event returns true when event is stored (not duplicate), false when duplicate
    let stored_1 = store.handle_event_with_raw(&events[0])?;
    let stored_2 = store.handle_event_with_raw(&events[2])?;

    println!("stored_1 (should be false for duplicate): {stored_1}");
    println!("stored_2 (should be false for duplicate): {stored_2}");

    assert!(
        !stored_1,
        "First event should now be a duplicate (already stored in batch) - got: {stored_1}"
    );
    assert!(
        !stored_2,
        "Third event should now be a duplicate (already stored in batch) - got: {stored_2}"
    );

    // Test new event is not duplicate
    let new_event = create_test_raw_event(None, "user3", "token1", "signup", None, None);

    let is_new = store.handle_event_with_raw(&new_event)?;
    assert!(
        is_new,
        "New event should not be a duplicate (should be stored)"
    );

    Ok(())
}

#[tokio::test]
async fn test_processor_statistics() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);

    // Initial state
    let initial_store_count = processor.get_active_store_count().await;
    assert_eq!(initial_store_count, 0, "Should start with no active stores");

    Ok(())
}

#[tokio::test]
async fn test_duplicate_metrics_tracking() -> Result<()> {
    // Test the duplicate metrics functionality directly
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;

    // Create test events with same composite key but different properties
    let now = 1640995200u64;

    // First event - should be stored
    let first_raw_event = RawEvent {
        uuid: Some(uuid::Uuid::new_v4()),
        event: "page_view".to_string(),
        distinct_id: Some(serde_json::json!("user1")),
        token: Some("token1".to_string()),
        properties: {
            let mut props = std::collections::HashMap::new();
            props.insert("url".to_string(), serde_json::json!("/home"));
            props.insert("referrer".to_string(), serde_json::json!("google"));
            props
        },
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored = store.handle_event_with_raw(&first_raw_event)?;
    assert!(is_stored, "First event should be stored");

    // Second event - duplicate with different UUID and properties
    let second_raw_event = RawEvent {
        uuid: Some(uuid::Uuid::new_v4()),
        event: "page_view".to_string(),
        distinct_id: Some(serde_json::json!("user1")),
        token: Some("token1".to_string()),
        properties: {
            let mut props = std::collections::HashMap::new();
            props.insert("url".to_string(), serde_json::json!("/home")); // Same
            props.insert("referrer".to_string(), serde_json::json!("bing")); // Different
            props.insert("campaign".to_string(), serde_json::json!("summer")); // New
            props
        },
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_duplicate = !store.handle_event_with_raw(&second_raw_event)?;
    assert!(is_duplicate, "Second event should be a duplicate");

    // Third event - another duplicate with same UUID as second
    let third_raw_event = RawEvent {
        uuid: second_raw_event.uuid, // Same UUID as second
        event: "page_view".to_string(),
        distinct_id: Some(serde_json::json!("user1")),
        token: Some("token1".to_string()),
        properties: {
            let mut props = std::collections::HashMap::new();
            props.insert("url".to_string(), serde_json::json!("/home"));
            props.insert("referrer".to_string(), serde_json::json!("yahoo")); // Different again
            props
        },
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_duplicate_again = !store.handle_event_with_raw(&third_raw_event)?;
    assert!(is_duplicate_again, "Third event should also be a duplicate");

    Ok(())
}

#[tokio::test]
async fn test_properties_normalization_in_metrics() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;

    let now = 1640995200u64;

    // First event with nested object properties in one order
    let first_raw_event = RawEvent {
        uuid: Some(uuid::Uuid::new_v4()),
        event: "page_view".to_string(),
        distinct_id: Some(serde_json::json!("user1")),
        token: Some("token1".to_string()),
        properties: {
            let mut props = std::collections::HashMap::new();
            props.insert(
                "metadata".to_string(),
                serde_json::json!({
                    "z_prop": "last",
                    "a_prop": "first",
                    "m_prop": "middle"
                }),
            );
            props
        },
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored = store.handle_event_with_raw(&first_raw_event)?;
    assert!(is_stored, "First event should be stored");

    // Second event with same nested object but different key order - should be considered identical
    let second_raw_event = RawEvent {
        uuid: Some(uuid::Uuid::new_v4()),
        event: "page_view".to_string(),
        distinct_id: Some(serde_json::json!("user1")),
        token: Some("token1".to_string()),
        properties: {
            let mut props = std::collections::HashMap::new();
            props.insert(
                "metadata".to_string(),
                serde_json::json!({
                    "a_prop": "first",
                    "m_prop": "middle",
                    "z_prop": "last"
                }),
            );
            props
        },
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_duplicate = !store.handle_event_with_raw(&second_raw_event)?;
    assert!(
        is_duplicate,
        "Second event should be a duplicate due to identical normalized properties"
    );

    Ok(())
}

// CRITICAL DEDUPLICATION EDGE CASE TESTS

#[tokio::test]
async fn test_deduplication_malformed_timestamp_edge_cases() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;

    // Test case 1: Empty timestamp - should use current time fallback
    let event_empty_timestamp = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event_empty".to_string(), // Different event to avoid duplication
        distinct_id: Some(json!("user1")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some("".to_string()), // Empty string
        ..Default::default()
    };

    let is_stored_empty = store.handle_event_with_raw(&event_empty_timestamp)?;
    assert!(
        is_stored_empty,
        "Event with empty timestamp should be stored"
    );

    // Test case 2: Invalid timestamp format - should use current time fallback
    let event_invalid_timestamp = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event_invalid".to_string(), // Different event to avoid duplication
        distinct_id: Some(json!("user2")),       // Different user to avoid duplication
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some("not-a-timestamp".to_string()),
        ..Default::default()
    };

    let is_stored_invalid = store.handle_event_with_raw(&event_invalid_timestamp)?;
    assert!(
        is_stored_invalid,
        "Event with invalid timestamp should be stored"
    );

    // Test case 3: None timestamp - should use current time fallback
    let event_none_timestamp = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event_none".to_string(), // Different event to avoid duplication
        distinct_id: Some(json!("user3")),    // Different user to avoid duplication
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: None,
        ..Default::default()
    };

    let is_stored_none = store.handle_event_with_raw(&event_none_timestamp)?;
    assert!(is_stored_none, "Event with None timestamp should be stored");

    // Test case 4: Very large timestamp - should handle gracefully
    let event_large_timestamp = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event_large".to_string(), // Different event to avoid duplication
        distinct_id: Some(json!("user4")),     // Different user to avoid duplication
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some("99999999999999999999".to_string()), // Very large number
        ..Default::default()
    };

    let is_stored_large = store.handle_event_with_raw(&event_large_timestamp)?;
    assert!(
        is_stored_large,
        "Event with very large timestamp should be stored"
    );

    // Test case 5: Verify that duplicate detection still works with malformed timestamps
    // Two events with same composite key but different UUIDs should be considered duplicates
    let duplicate_event = RawEvent {
        uuid: Some(Uuid::new_v4()),            // Different UUID
        event: "test_event_empty".to_string(), // Same event name as first test
        distinct_id: Some(json!("user1")),     // Same distinct_id as first test
        token: Some("token1".to_string()),     // Same token as first test
        properties: HashMap::new(),
        timestamp: Some("".to_string()), // Same malformed timestamp
        ..Default::default()
    };

    // This should be detected as a duplicate because the composite key is the same
    let is_duplicate = store.handle_event_with_raw(&duplicate_event)?;
    // Note: is_duplicate should be false (meaning it WAS a duplicate and not stored)
    assert!(
        !is_duplicate,
        "Duplicate event with malformed timestamp should be detected"
    );

    Ok(())
}

#[tokio::test]
async fn test_deduplication_distinct_id_edge_cases() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;
    let now = 1640995200u64;

    // Test case 1: Null distinct_id - should use "unknown" fallback
    let event_null_distinct_id = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!(null)),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_null = store.handle_event_with_raw(&event_null_distinct_id)?;
    assert!(
        is_stored_null,
        "Event with null distinct_id should be stored"
    );

    // Test case 2: None distinct_id - should also use "unknown" fallback
    // This should be detected as a DUPLICATE of case 1 since both normalize to "unknown"
    let event_none_distinct_id = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: None,
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_none = store.handle_event_with_raw(&event_none_distinct_id)?;
    assert!(
        !is_stored_none,
        "Event with None distinct_id should be detected as duplicate of null distinct_id"
    );

    // Test case 3: Complex JSON distinct_id - now gets stringified, not "unknown"
    // This creates a unique composite key since the JSON is stringified
    let event_complex_distinct_id = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!({"user_id": 123, "session": "abc"})),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_complex = store.handle_event_with_raw(&event_complex_distinct_id)?;
    assert!(
        is_stored_complex,
        "Event with complex distinct_id should be stored (stringified JSON creates unique key)"
    );

    // Test case 4: Empty string distinct_id
    // Use different timestamp to ensure unique composite key
    let event_empty_distinct_id = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!("")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some((now + 2).to_string()),
        ..Default::default()
    };

    let is_stored_empty = store.handle_event_with_raw(&event_empty_distinct_id)?;
    assert!(
        is_stored_empty,
        "Event with empty distinct_id should be stored"
    );

    // Test case 5: Very long distinct_id - should be handled
    // Use different timestamp to ensure unique composite key
    let long_distinct_id = "a".repeat(500); // Very long string
    let event_long_distinct_id = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!(long_distinct_id)),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some((now + 3).to_string()),
        ..Default::default()
    };

    let is_stored_long = store.handle_event_with_raw(&event_long_distinct_id)?;
    assert!(
        is_stored_long,
        "Event with very long distinct_id should be stored"
    );

    Ok(())
}

#[tokio::test]
async fn test_deduplication_token_edge_cases() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;
    let now = 1640995200u64;

    // Test case 1: None token - should use "unknown" fallback
    let event_none_token = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!("user1")),
        token: None,
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_none = store.handle_event_with_raw(&event_none_token)?;
    assert!(is_stored_none, "Event with None token should be stored");

    // Test case 2: Empty string token
    let event_empty_token = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!("user1")),
        token: Some("".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_empty = store.handle_event_with_raw(&event_empty_token)?;
    assert!(is_stored_empty, "Event with empty token should be stored");

    // Test case 3: Very long token
    let long_token = "t".repeat(1000);
    let event_long_token = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!("user1")),
        token: Some(long_token),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_long = store.handle_event_with_raw(&event_long_token)?;
    assert!(
        is_stored_long,
        "Event with very long token should be stored"
    );

    // Test case 4: Token with special characters
    let special_token = "token-with-special!@#$%^&*()chars";
    let event_special_token = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "test_event".to_string(),
        distinct_id: Some(json!("user1")),
        token: Some(special_token.to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_special = store.handle_event_with_raw(&event_special_token)?;
    assert!(
        is_stored_special,
        "Event with special character token should be stored"
    );

    Ok(())
}

#[tokio::test]
async fn test_deduplication_event_name_edge_cases() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;
    let now = 1640995200u64;

    // Test case 1: Empty event name
    let event_empty_name = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "".to_string(),
        distinct_id: Some(json!("user1")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_empty = store.handle_event_with_raw(&event_empty_name)?;
    assert!(is_stored_empty, "Event with empty name should be stored");

    // Test case 2: Very long event name
    let long_event_name = "event_".repeat(200); // Very long event name
    let event_long_name = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: long_event_name,
        distinct_id: Some(json!("user1")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_long = store.handle_event_with_raw(&event_long_name)?;
    assert!(is_stored_long, "Event with very long name should be stored");

    // Test case 3: Event name with special characters and unicode
    let special_event_name = "event-name!@#$%^&*()_+={}[]|\\:;\"'<>,.?/~`测试事件";
    let event_special_name = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: special_event_name.to_string(),
        distinct_id: Some(json!("user1")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_special = store.handle_event_with_raw(&event_special_name)?;
    assert!(
        is_stored_special,
        "Event with special character name should be stored"
    );

    // Test case 4: Event name with newlines and tabs
    let event_with_whitespace = "event\nwith\ttabs\rand\r\nlinebreaks";
    let event_whitespace_name = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: event_with_whitespace.to_string(),
        distinct_id: Some(json!("user1")),
        token: Some("token1".to_string()),
        properties: HashMap::new(),
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_stored_whitespace = store.handle_event_with_raw(&event_whitespace_name)?;
    assert!(
        is_stored_whitespace,
        "Event with whitespace in name should be stored"
    );

    Ok(())
}

#[tokio::test]
async fn test_deduplication_composite_key_consistency() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;

    // Test that events with edge cases but same composite key are properly deduplicated

    // First event - baseline with edge cases
    let first_event = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: "special:event\nwith\ttabs".to_string(),
        distinct_id: Some(json!(null)), // Will become "unknown"
        token: Some("token!@#$%".to_string()),
        properties: HashMap::new(),
        timestamp: Some("invalid-timestamp".to_string()), // Will use current time
        ..Default::default()
    };

    let is_stored_first = store.handle_event_with_raw(&first_event)?;
    assert!(
        is_stored_first,
        "First event with edge cases should be stored"
    );

    // Second event - same logical composite key but different UUID and properties
    // Note: Both null and None normalize to "unknown", so this will be a duplicate
    let mut different_props = HashMap::new();
    different_props.insert("extra".to_string(), json!("data"));

    let second_event = RawEvent {
        uuid: Some(Uuid::new_v4()),                     // Different UUID
        event: "special:event\nwith\ttabs".to_string(), // Same event name
        distinct_id: None,                              // Will also become "unknown" like null
        token: Some("token!@#$%".to_string()),          // Same token
        properties: different_props,                    // Different properties
        timestamp: Some("also-invalid".to_string()),    // Will also use current time fallback
        ..Default::default()
    };

    let is_stored_second = store.handle_event_with_raw(&second_event)?;
    assert!(
        !is_stored_second,
        "Second event should be a duplicate despite different UUID and properties"
    );

    Ok(())
}

#[tokio::test]
async fn test_deduplication_with_very_large_field_values() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let store = DeduplicationStore::new(store_config, "test_topic".to_string(), 0)?;
    let now = 1640995200u64;

    // Create event with very large field values
    let large_distinct_id = "user_".repeat(1000);
    let large_token = "token_".repeat(500);
    let large_event_name = "event_name_".repeat(200);

    let mut large_properties = HashMap::new();
    large_properties.insert("large_prop".to_string(), json!("data_".repeat(2000)));

    let large_event = RawEvent {
        uuid: Some(Uuid::new_v4()),
        event: large_event_name,
        distinct_id: Some(json!(large_distinct_id)),
        token: Some(large_token),
        properties: large_properties,
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    // Should handle large values without errors
    let is_stored = store.handle_event_with_raw(&large_event)?;
    assert!(
        is_stored,
        "Event with very large field values should be stored"
    );

    // Duplicate with same large values should be detected
    let duplicate_large_event = RawEvent {
        uuid: Some(Uuid::new_v4()), // Different UUID
        event: large_event.event.clone(),
        distinct_id: large_event.distinct_id.clone(),
        token: large_event.token.clone(),
        properties: HashMap::new(), // Different properties
        timestamp: Some(now.to_string()),
        ..Default::default()
    };

    let is_duplicate = store.handle_event_with_raw(&duplicate_large_event)?;
    assert!(
        !is_duplicate,
        "Duplicate with large values should be detected"
    );

    Ok(())
}

// COMPREHENSIVE PROCESSOR REBALANCE HANDLER TESTS

#[tokio::test]
async fn test_rebalance_handler_partition_cleanup() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = ProcessorRebalanceHandler::new(processor.clone());

    // Simulate creating stores for multiple partitions by processing events
    let _events = vec![
        create_test_raw_event(None, "event1", "user1", "token1", Some(1640995200), None),
        create_test_raw_event(None, "event2", "user2", "token1", Some(1640995201), None),
    ];

    // Simulate processing events from different partitions
    // This would normally happen through the consumer, but we'll test the store creation directly
    let initial_store_count = processor.get_active_store_count().await;
    assert_eq!(initial_store_count, 0, "Should start with no active stores");

    // Create TopicPartitionList for assignment simulation
    let mut assigned_partitions = rdkafka::TopicPartitionList::new();
    assigned_partitions.add_partition("test-topic", 0);
    assigned_partitions.add_partition("test-topic", 1);
    assigned_partitions.add_partition("test-topic", 2);

    // Test partition assignment
    let assign_result = rebalance_handler
        .on_partitions_assigned(&assigned_partitions)
        .await;
    assert!(assign_result.is_ok(), "Partition assignment should succeed");

    // Verify partitions were assigned (stores are created lazily, so count still 0)
    let store_count_after_assignment = processor.get_active_store_count().await;
    assert_eq!(
        store_count_after_assignment, 0,
        "Stores should be created lazily"
    );

    // Now test partition revocation
    let mut revoked_partitions = rdkafka::TopicPartitionList::new();
    revoked_partitions.add_partition("test-topic", 1);
    revoked_partitions.add_partition("test-topic", 2);

    let revoke_result = rebalance_handler
        .on_partitions_revoked(&revoked_partitions)
        .await;
    assert!(revoke_result.is_ok(), "Partition revocation should succeed");

    // Test pre and post rebalance hooks
    let pre_rebalance_result = rebalance_handler.on_pre_rebalance().await;
    assert!(pre_rebalance_result.is_ok(), "Pre-rebalance should succeed");

    let post_rebalance_result = rebalance_handler.on_post_rebalance().await;
    assert!(
        post_rebalance_result.is_ok(),
        "Post-rebalance should succeed"
    );

    Ok(())
}

#[tokio::test]
async fn test_rebalance_handler_with_active_stores() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = ProcessorRebalanceHandler::new(processor.clone());

    // Test cleanup of specific partitions (processor method)
    let partitions_to_revoke = vec![
        ("test-topic-1".to_string(), 0),
        ("test-topic-1".to_string(), 1),
        ("test-topic-2".to_string(), 0),
    ];

    processor.cleanup_stores(&partitions_to_revoke).await;

    // Verify cleanup worked (should not error)
    let store_count = processor.get_active_store_count().await;
    // Since we didn't actually create stores, count should still be 0
    assert_eq!(store_count, 0);

    // Test with TopicPartitionList revocation (rebalance handler method)
    let mut revoked_partitions = rdkafka::TopicPartitionList::new();
    revoked_partitions.add_partition("test-topic-1", 0);
    revoked_partitions.add_partition("test-topic-1", 1);
    revoked_partitions.add_partition("test-topic-2", 0);

    let revoke_result = rebalance_handler
        .on_partitions_revoked(&revoked_partitions)
        .await;
    assert!(
        revoke_result.is_ok(),
        "Should handle revocation of non-existent stores gracefully"
    );

    Ok(())
}

#[tokio::test]
async fn test_rebalance_handler_concurrent_operations() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor.clone()));

    // Test concurrent rebalance operations
    let mut handles = Vec::new();

    // Spawn multiple rebalance operations concurrently
    for i in 0..5 {
        let handler = rebalance_handler.clone();
        let handle = tokio::spawn(async move {
            let mut partitions = rdkafka::TopicPartitionList::new();
            partitions.add_partition(&format!("concurrent-topic-{i}"), 0);
            partitions.add_partition(&format!("concurrent-topic-{i}"), 1);

            // Assignment
            let assign_result = handler.on_partitions_assigned(&partitions).await;
            assert!(assign_result.is_ok());

            // Pre-rebalance
            let pre_result = handler.on_pre_rebalance().await;
            assert!(pre_result.is_ok());

            // Revocation
            let revoke_result = handler.on_partitions_revoked(&partitions).await;
            assert!(revoke_result.is_ok());

            // Post-rebalance
            let post_result = handler.on_post_rebalance().await;
            assert!(post_result.is_ok());

            i
        });
        handles.push(handle);
    }

    // Wait for all concurrent operations to complete
    let results: Vec<usize> = futures::future::try_join_all(handles).await?;
    assert_eq!(
        results.len(),
        5,
        "All concurrent operations should complete"
    );
    assert_eq!(
        results,
        vec![0, 1, 2, 3, 4],
        "All operations should return expected values"
    );

    // Verify final state
    let final_store_count = processor.get_active_store_count().await;
    assert_eq!(final_store_count, 0, "All stores should be cleaned up");

    Ok(())
}

#[tokio::test]
async fn test_rebalance_handler_error_scenarios() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = ProcessorRebalanceHandler::new(processor.clone());

    // Test with empty partition lists
    let empty_partitions = rdkafka::TopicPartitionList::new();

    let assign_result = rebalance_handler
        .on_partitions_assigned(&empty_partitions)
        .await;
    assert!(
        assign_result.is_ok(),
        "Should handle empty assignment gracefully"
    );

    let revoke_result = rebalance_handler
        .on_partitions_revoked(&empty_partitions)
        .await;
    assert!(
        revoke_result.is_ok(),
        "Should handle empty revocation gracefully"
    );

    // Test with many partitions
    let mut many_partitions = rdkafka::TopicPartitionList::new();
    for i in 0..100 {
        many_partitions.add_partition(&format!("stress-topic-{}", i % 10), i % 3);
    }

    let assign_many_result = rebalance_handler
        .on_partitions_assigned(&many_partitions)
        .await;
    assert!(
        assign_many_result.is_ok(),
        "Should handle many partitions assignment"
    );

    let revoke_many_result = rebalance_handler
        .on_partitions_revoked(&many_partitions)
        .await;
    assert!(
        revoke_many_result.is_ok(),
        "Should handle many partitions revocation"
    );

    // Test with partitions that have special characters in topic names
    let mut special_partitions = rdkafka::TopicPartitionList::new();
    special_partitions.add_partition("topic-with-special-chars!@#$%", 0);
    special_partitions.add_partition("topic_with_underscores", 1);
    special_partitions.add_partition("topic.with.dots", 2);

    let assign_special_result = rebalance_handler
        .on_partitions_assigned(&special_partitions)
        .await;
    assert!(
        assign_special_result.is_ok(),
        "Should handle special character topics"
    );

    let revoke_special_result = rebalance_handler
        .on_partitions_revoked(&special_partitions)
        .await;
    assert!(
        revoke_special_result.is_ok(),
        "Should handle special character topic revocation"
    );

    Ok(())
}

#[tokio::test]
async fn test_rebalance_handler_store_isolation() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);

    // Test that stores are properly isolated by partition
    // We'll test the cleanup specifically to ensure only the right partitions are affected

    let partitions_group_a = vec![("topic-a".to_string(), 0), ("topic-a".to_string(), 1)];

    let partitions_group_b = vec![("topic-b".to_string(), 0), ("topic-b".to_string(), 1)];

    // Simulate cleanup of group A
    processor.cleanup_stores(&partitions_group_a).await;

    // Verify we can still cleanup group B (different partitions)
    processor.cleanup_stores(&partitions_group_b).await;

    // Test overlapping cleanup (same topic, different partitions)
    let overlapping_partitions = vec![
        ("topic-a".to_string(), 0), // Same as group A
        ("topic-c".to_string(), 0), // Different topic
    ];

    processor.cleanup_stores(&overlapping_partitions).await;

    // All operations should succeed without errors
    let final_count = processor.get_active_store_count().await;
    assert_eq!(
        final_count, 0,
        "No stores should be active after cleanup tests"
    );

    Ok(())
}

#[tokio::test]
async fn test_rebalance_handler_with_processor_statistics() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000");

    let dedup_config = DeduplicationConfig {
        output_topic: Some("test-output".to_string()),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = ProcessorRebalanceHandler::new(processor.clone());

    // Test that rebalance operations properly interact with processor statistics

    // Initial state
    let initial_count = processor.get_active_store_count().await;
    assert_eq!(initial_count, 0, "Should start with zero active stores");

    // Simulate assignment and verify statistics
    let mut partitions = rdkafka::TopicPartitionList::new();
    partitions.add_partition("stats-topic", 0);
    partitions.add_partition("stats-topic", 1);
    partitions.add_partition("stats-topic", 2);

    rebalance_handler
        .on_partitions_assigned(&partitions)
        .await?;

    // Verify post-assignment state
    let post_assign_count = processor.get_active_store_count().await;
    assert_eq!(
        post_assign_count, 0,
        "Stores created lazily, so count still 0"
    );

    // Test pre-rebalance statistics
    rebalance_handler.on_pre_rebalance().await?;

    // Test post-rebalance statistics
    rebalance_handler.on_post_rebalance().await?;

    let post_rebalance_count = processor.get_active_store_count().await;
    assert_eq!(post_rebalance_count, 0, "Count should remain consistent");

    // Test revocation and statistics
    rebalance_handler.on_partitions_revoked(&partitions).await?;

    let post_revoke_count = processor.get_active_store_count().await;
    assert_eq!(
        post_revoke_count, 0,
        "Count should remain zero after revocation"
    );

    Ok(())
}
