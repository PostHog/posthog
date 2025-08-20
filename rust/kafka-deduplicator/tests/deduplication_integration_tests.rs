use anyhow::Result;
use kafka_deduplicator::{config::Config, service::KafkaDeduplicatorService};
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    producer::{FutureProducer, FutureRecord, Producer},
    util::Timeout,
    Message,
};
use serde_json::{json, Value};
use std::env;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tempfile::TempDir;
use tokio::sync::Mutex as TokioMutex;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";

// Global mutex to serialize Kafka integration tests (using async-aware Tokio Mutex)
static KAFKA_TEST_MUTEX: OnceLock<TokioMutex<()>> = OnceLock::new();

/// Helper to create Kafka topics before tests
async fn create_kafka_topics(topics: Vec<&str>) -> Result<()> {
    println!("Creating Kafka admin client for broker: {KAFKA_BROKERS}");
    let admin_client: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    println!("Creating {} topics", topics.len());
    let new_topics: Vec<NewTopic> = topics
        .into_iter()
        .map(|topic| NewTopic::new(topic, 1, TopicReplication::Fixed(1)))
        .collect();

    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    println!("Sending create topics request to Kafka...");
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

/// Produce duplicate events to test deduplication
async fn produce_duplicate_events(
    topic: &str,
    distinct_id: &str,
    event_name: &str,
    count: usize,
) -> Result<()> {
    produce_duplicate_events_with_timestamp(
        topic,
        distinct_id,
        event_name,
        count,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
    )
    .await
}

/// Produce duplicate events with a specific timestamp
async fn produce_duplicate_events_with_timestamp(
    topic: &str,
    distinct_id: &str,
    event_name: &str,
    count: usize,
    timestamp: u64,
) -> Result<()> {
    println!("Creating producer for topic: {topic}");
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    println!("Producing {count} events to topic {topic}");
    for i in 0..count {
        let event = json!({
            "uuid": Uuid::new_v4().to_string(),
            "distinct_id": distinct_id,
            "event": event_name,
            "timestamp": timestamp.to_string(),  // Convert to string
            "token": "test_token",
            "properties": {
                "index": i,
                "duplicate_test": true,
            }
        });

        let key = format!("{distinct_id}:{event_name}");
        let payload = serde_json::to_string(&event)?;

        let record = FutureRecord::to(topic).key(&key).payload(&payload);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e:?}"))?;
    }

    println!("Flushing producer...");
    producer.flush(Timeout::After(Duration::from_secs(5)))?;
    println!("Successfully produced {count} events");
    Ok(())
}

/// Consume messages from output topic to verify deduplication
async fn consume_output_messages(
    topic: &str,
    group_id: &str,
    timeout: Duration,
) -> Result<Vec<Value>> {
    println!("Creating consumer for output topic: {topic}");
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .create()?;

    println!("Subscribing to output topic: {topic}");
    consumer.subscribe(&[topic])?;

    let mut messages = Vec::new();
    let start = std::time::Instant::now();

    println!("Starting to consume messages (timeout: {timeout:?})...");
    let mut poll_count = 0;
    while start.elapsed() < timeout {
        poll_count += 1;
        if poll_count % 100 == 0 {
            println!(
                "Still polling... elapsed: {:?}, messages so far: {}",
                start.elapsed(),
                messages.len()
            );
        }
        // Use poll with timeout instead of recv().await which blocks indefinitely
        match tokio::time::timeout(Duration::from_millis(100), consumer.recv()).await {
            Ok(Ok(msg)) => {
                println!("Received a message!");
                if let Some(payload) = msg.payload() {
                    if let Ok(json) = serde_json::from_slice::<Value>(payload) {
                        println!("Parsed message from output topic");
                        messages.push(json);
                    }
                }
            }
            Ok(Err(e)) => {
                // Kafka error
                if !matches!(e, rdkafka::error::KafkaError::NoMessageReceived) {
                    println!("Error consuming message: {e:?}");
                }
            }
            Err(_) => {
                // Timeout - no message received, continue polling
            }
        }
    }

    Ok(messages)
}

#[tokio::test]
async fn test_basic_deduplication() -> Result<()> {
    println!("Starting test_basic_deduplication");

    println!("Acquiring test mutex...");
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;
    println!("Test mutex acquired");

    let input_topic = format!("test_dedup_input_{}", Uuid::new_v4());
    let output_topic = format!("test_dedup_output_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    println!("Test topics: input={input_topic}, output={output_topic}, group={group_id}");

    // Create topics
    println!("Creating Kafka topics...");
    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    println!("Topics created successfully");

    // Create temporary directory for RocksDB (keep it alive for test duration)
    let _temp_dir = TempDir::new()?;

    // Set only the environment variables that differ from defaults
    env::set_var("KAFKA_CONSUMER_TOPIC", &input_topic);
    env::set_var("KAFKA_CONSUMER_GROUP", &group_id);
    env::set_var("OUTPUT_TOPIC", &output_topic);
    env::set_var("STORE_PATH", _temp_dir.path().to_str().unwrap());
    // Faster for tests
    env::set_var("COMMIT_INTERVAL_SECS", "1");
    env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
    env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

    // Create configuration from environment
    let config = Config::init_with_defaults()?;

    // Create the service using the same abstraction as production
    println!("Creating Kafka Deduplicator service...");
    let mut service = KafkaDeduplicatorService::new(config)?;
    service.initialize()?;
    println!("Service initialized");

    // Produce test events
    println!("Producing 5 duplicate events for user_123...");
    produce_duplicate_events(&input_topic, "user_123", "test_event", 5).await?;
    println!("Produced first batch");

    println!("Producing 3 duplicate events for user_456...");
    produce_duplicate_events(&input_topic, "user_456", "test_event", 3).await?;
    println!("Produced second batch");

    // Run the service with a controlled shutdown
    let shutdown_signal = async {
        println!("Waiting 5 seconds for processing...");
        tokio::time::sleep(Duration::from_secs(5)).await;
        println!("Initiating shutdown...");
    };

    // Run service with custom shutdown signal
    let service_handle =
        tokio::spawn(async move { service.run_with_shutdown(shutdown_signal).await });

    // Wait for service to complete
    let _ = tokio::time::timeout(Duration::from_secs(10), service_handle).await;
    println!("Service stopped");

    // Consume from output topic to verify deduplication
    println!("Starting to consume from output topic for verification...");
    let output_messages = consume_output_messages(
        &output_topic,
        &format!("verify_{group_id}"),
        Duration::from_secs(5),
    )
    .await?;
    println!(
        "Consumed {} messages from output topic",
        output_messages.len()
    );

    // Should have only 2 unique events (one per distinct_id)
    assert_eq!(
        output_messages.len(),
        2,
        "Expected 2 unique events, got {}",
        output_messages.len()
    );

    // Verify the events have different distinct_ids
    let distinct_ids: Vec<&str> = output_messages
        .iter()
        .filter_map(|msg| msg.get("distinct_id")?.as_str())
        .collect();

    assert!(distinct_ids.contains(&"user_123"));
    assert!(distinct_ids.contains(&"user_456"));

    Ok(())
}

#[tokio::test]
async fn test_deduplication_with_different_events() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let input_topic = format!("test_dedup_events_{}", Uuid::new_v4());
    let output_topic = format!("test_dedup_events_output_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    // Create topics
    create_kafka_topics(vec![&input_topic, &output_topic]).await?;

    // Create temporary directory for RocksDB (keep it alive for test duration)
    let _temp_dir = TempDir::new()?;

    // Set only the environment variables that differ from defaults
    env::set_var("KAFKA_CONSUMER_TOPIC", &input_topic);
    env::set_var("KAFKA_CONSUMER_GROUP", &group_id);
    env::set_var("OUTPUT_TOPIC", &output_topic);
    env::set_var("STORE_PATH", _temp_dir.path().to_str().unwrap());
    // Faster for tests
    env::set_var("COMMIT_INTERVAL_SECS", "1");
    env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
    env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

    // Create configuration from environment
    let config = Config::init_with_defaults()?;

    // Create and initialize the service
    let mut service = KafkaDeduplicatorService::new(config)?;
    service.initialize()?;

    // Produce events with same distinct_id but different event names
    produce_duplicate_events(&input_topic, "user_123", "event_a", 3).await?;
    produce_duplicate_events(&input_topic, "user_123", "event_b", 2).await?;
    produce_duplicate_events(&input_topic, "user_123", "event_c", 1).await?;

    // Run the service with a controlled shutdown
    let shutdown_signal = async {
        tokio::time::sleep(Duration::from_secs(5)).await;
    };

    let service_handle =
        tokio::spawn(async move { service.run_with_shutdown(shutdown_signal).await });

    // Wait for service to complete
    let _ = tokio::time::timeout(Duration::from_secs(10), service_handle).await;

    // Verify output
    let output_messages = consume_output_messages(
        &output_topic,
        &format!("verify_{group_id}"),
        Duration::from_secs(5),
    )
    .await?;

    // Should have 3 unique events (one per event name)
    assert_eq!(
        output_messages.len(),
        3,
        "Expected 3 unique events, got {}",
        output_messages.len()
    );

    // Verify we have all three event types
    let event_names: Vec<&str> = output_messages
        .iter()
        .filter_map(|msg| msg.get("event")?.as_str())
        .collect();

    assert!(event_names.contains(&"event_a"));
    assert!(event_names.contains(&"event_b"));
    assert!(event_names.contains(&"event_c"));

    Ok(())
}

#[tokio::test]
async fn test_deduplication_persistence() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let input_topic = format!("test_persistence_{}", Uuid::new_v4());
    let output_topic = format!("test_persistence_output_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    // Create topics
    create_kafka_topics(vec![&input_topic, &output_topic]).await?;

    // Create temp directory that persists across processor restarts
    let temp_dir = TempDir::new()?;
    let store_path = temp_dir.path().to_path_buf();
    println!("Using store base path: {store_path:?}");

    // Use fixed timestamps for all events
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();

    // First, produce ALL events to the input topic
    println!("Producing all test events to input topic...");

    // Batch 1: 3 events (event_a unique, event_b unique, event_a duplicate)
    produce_duplicate_events_with_timestamp(&input_topic, "user1", "event_a", 1, timestamp).await?;
    produce_duplicate_events_with_timestamp(&input_topic, "user1", "event_b", 1, timestamp).await?;
    produce_duplicate_events_with_timestamp(&input_topic, "user1", "event_a", 1, timestamp).await?; // Duplicate!

    println!("Produced 3 events in first batch");

    // First processor instance - process first 3 messages
    {
        // Set environment variables for the first service instance
        env::set_var("KAFKA_CONSUMER_TOPIC", &input_topic);
        env::set_var("KAFKA_CONSUMER_GROUP", &group_id);
        env::set_var("OUTPUT_TOPIC", &output_topic);
        env::set_var("STORE_PATH", store_path.to_str().unwrap());
        env::set_var("COMMIT_INTERVAL_SECS", "1");
        env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
        env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

        // Create configuration from environment
        let config = Config::init_with_defaults()?;

        println!("First processor: Creating and initializing service...");
        let mut service = KafkaDeduplicatorService::new(config)?;
        service.initialize()?;

        println!("First processor: Starting to process first 3 events...");

        // Run service for 3 seconds then shutdown
        let shutdown_signal = async {
            tokio::time::sleep(Duration::from_secs(3)).await;
            println!("First processor: Initiating graceful shutdown...");
        };

        let service_handle =
            tokio::spawn(async move { service.run_with_shutdown(shutdown_signal).await });

        // Wait for service to complete
        let _ = tokio::time::timeout(Duration::from_secs(10), service_handle).await;

        // The processor should have:
        // - Processed event_a (unique) -> published
        // - Processed event_b (unique) -> published
        // - Processed event_a (duplicate) -> skipped
        // And committed offset at position 3

        println!("First processor: Shutdown complete, RocksDB should be flushed");
    }

    // Wait a bit to ensure RocksDB files are fully flushed to disk
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Batch 2: 2 events (event_c unique, event_b duplicate)
    produce_duplicate_events_with_timestamp(&input_topic, "user1", "event_c", 1, timestamp).await?;
    produce_duplicate_events_with_timestamp(&input_topic, "user1", "event_b", 1, timestamp).await?; // Duplicate!

    println!("Produced 2 more events in second batch (5 total events: 3 unique, 2 duplicates)");

    println!("Starting second processor instance with same store path");

    // Second processor instance with same store path
    {
        // Set environment variables for the second service instance (same store path)
        env::set_var("KAFKA_CONSUMER_TOPIC", &input_topic);
        env::set_var("KAFKA_CONSUMER_GROUP", &group_id);
        env::set_var("OUTPUT_TOPIC", &output_topic);
        env::set_var("STORE_PATH", store_path.to_str().unwrap());
        env::set_var("COMMIT_INTERVAL_SECS", "1");
        env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
        env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

        // Create configuration from environment
        let config = Config::init_with_defaults()?;

        println!("Second processor: Creating and initializing service with same store path...");
        let mut service = KafkaDeduplicatorService::new(config)?;
        service.initialize()?;

        println!("Second processor: Starting to process remaining 2 events...");

        // Run service for 3 seconds then shutdown
        let shutdown_signal = async {
            tokio::time::sleep(Duration::from_secs(3)).await;
            println!("Second processor: Initiating shutdown...");
        };

        let service_handle =
            tokio::spawn(async move { service.run_with_shutdown(shutdown_signal).await });

        // Wait for service to complete
        let _ = tokio::time::timeout(Duration::from_secs(10), service_handle).await;

        // The processor should:
        // - Process event_c (unique) -> published
        // - Process event_b (duplicate from first batch!) -> skipped (if RocksDB persisted)

        println!("Second processor: Shutdown complete");
    }

    // Verify output - should have exactly 3 unique events
    println!("Verifying output topic...");
    let output_messages = consume_output_messages(
        &output_topic,
        &format!("verify_{group_id}"),
        Duration::from_secs(5),
    )
    .await?;

    println!("Found {} messages in output topic", output_messages.len());

    // Expected: event_a, event_b, event_c (duplicates should be filtered)
    assert_eq!(
        output_messages.len(),
        3,
        "Expected 3 unique events (event_a, event_b, event_c), got {}",
        output_messages.len()
    );

    // Verify we have the right events
    let events: Vec<&str> = output_messages
        .iter()
        .filter_map(|msg| msg.get("event")?.as_str())
        .collect();

    assert!(events.contains(&"event_a"), "Missing event_a");
    assert!(events.contains(&"event_b"), "Missing event_b");
    assert!(events.contains(&"event_c"), "Missing event_c");

    println!("✓ Persistence test passed: RocksDB correctly preserved deduplication state across restarts");

    Ok(())
}
