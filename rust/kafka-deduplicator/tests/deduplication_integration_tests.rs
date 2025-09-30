use anyhow::Result;
use common_types::{CapturedEvent, RawEvent};
use health::HealthRegistry;
use kafka_deduplicator::{config::Config, service::KafkaDeduplicatorService};
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    message::{Header, Headers, OwnedHeaders},
    producer::{FutureProducer, FutureRecord, Producer},
    util::Timeout,
    Message,
};
use serde_json::{json, Value};
use std::collections::HashMap;
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

/// Helper function to create a test CapturedEvent with embedded RawEvent
fn create_test_captured_event(
    distinct_id: &str,
    event_name: &str,
    uuid: Uuid,
    timestamp: u64,
    properties: HashMap<String, Value>,
) -> Result<CapturedEvent> {
    // Create the RawEvent
    let raw_event = RawEvent {
        uuid: Some(uuid),
        distinct_id: Some(Value::String(distinct_id.to_string())),
        event: event_name.to_string(),
        timestamp: Some(timestamp.to_string()),
        token: Some("test_token".to_string()),
        properties,
        offset: None,
        set: None,
        set_once: None,
    };

    // Serialize the RawEvent to a string for the data field
    let data = serde_json::to_string(&raw_event)?;

    // Create the CapturedEvent wrapper
    let captured_event = CapturedEvent {
        uuid,
        distinct_id: distinct_id.to_string(),
        ip: "127.0.0.1".to_string(),
        data,
        now: format!("{timestamp}000"), // timestamp in milliseconds
        sent_at: None,
        token: "test_token".to_string(),
        is_cookieless_mode: false,
    };

    Ok(captured_event)
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
        let uuid = Uuid::new_v4();

        // Create properties for the event (same for all duplicates within a batch)
        let mut properties = HashMap::new();
        properties.insert("duplicate_test".to_string(), json!(true));
        properties.insert("batch_id".to_string(), json!(distinct_id)); // Same for all in batch

        // Create the CapturedEvent using our helper
        let captured_event =
            create_test_captured_event(distinct_id, event_name, uuid, timestamp, properties)?;

        let key = format!("{distinct_id}:{event_name}");
        let payload = serde_json::to_string(&captured_event)?;

        // Add test headers to verify they're preserved
        let headers = OwnedHeaders::new()
            .insert(Header {
                key: "test-header",
                value: Some(&format!("test-value-{i}")),
            })
            .insert(Header {
                key: "event-index",
                value: Some(&i.to_string()),
            });

        let record = FutureRecord::to(topic)
            .key(&key)
            .payload(&payload)
            .headers(headers);

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
) -> Result<Vec<(Value, Option<OwnedHeaders>)>> {
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
                        let headers = msg.detach().headers().cloned();
                        println!("Parsed message from output topic");
                        messages.push((json, headers));
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
    // For tests, we need to read from the beginning since we produce before starting
    env::set_var("KAFKA_CONSUMER_OFFSET_RESET", "earliest");
    // Faster for tests
    env::set_var("COMMIT_INTERVAL_SECS", "1");
    env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
    env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

    // Create configuration from environment
    let config = Config::init_with_defaults()?;

    // Create the service using the same abstraction as production
    println!("Creating Kafka Deduplicator service...");
    let liveness = HealthRegistry::new("test_liveness");
    let mut service = KafkaDeduplicatorService::new(config, liveness).await?;
    service.initialize().await?;
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
    // 5 events for user_123 -> 1 unique + 4 duplicates (ConfirmedDuplicate with OnlyUuidDifferent)
    // 3 events for user_456 -> 1 unique + 2 duplicates (ConfirmedDuplicate with OnlyUuidDifferent)
    // Total: 2 unique events, 6 filtered duplicates
    assert_eq!(
        output_messages.len(),
        2,
        "Expected 2 unique events, got {}",
        output_messages.len()
    );

    // Verify the events have different distinct_ids
    let distinct_ids: Vec<&str> = output_messages
        .iter()
        .filter_map(|(msg, _)| msg.get("distinct_id")?.as_str())
        .collect();

    assert!(distinct_ids.contains(&"user_123"));
    assert!(distinct_ids.contains(&"user_456"));

    // Verify headers were preserved
    for (i, (_, headers)) in output_messages.iter().enumerate() {
        assert!(headers.is_some(), "Message {i} should have headers");
        let headers = headers.as_ref().unwrap();

        // Use the iterator to check if our test header exists
        let has_test_header = headers.iter().any(|h| h.key == "test-header");
        assert!(
            has_test_header,
            "test-header should be preserved in message {i}"
        );
    }

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
    // For tests, we need to read from the beginning since we produce before starting
    env::set_var("KAFKA_CONSUMER_OFFSET_RESET", "earliest");
    // Faster for tests
    env::set_var("COMMIT_INTERVAL_SECS", "1");
    env::set_var("SHUTDOWN_TIMEOUT_SECS", "10");
    env::set_var("KAFKA_PRODUCER_LINGER_MS", "0");

    // Create configuration from environment
    let config = Config::init_with_defaults()?;

    // Create and initialize the service
    let liveness = HealthRegistry::new("test_liveness");
    let mut service = KafkaDeduplicatorService::new(config, liveness).await?;
    service.initialize().await?;

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
    // Since output is CapturedEvent format, we need to parse the nested RawEvent from the data field
    let event_names: Vec<String> = output_messages
        .iter()
        .filter_map(|(msg, _)| {
            // Get the data field which contains the serialized RawEvent
            let data_str = msg.get("data")?.as_str()?;
            // Parse the RawEvent from the data field
            let raw_event: Value = serde_json::from_str(data_str).ok()?;
            // Get the event name from the RawEvent
            raw_event.get("event")?.as_str().map(|s| s.to_string())
        })
        .collect();

    assert!(event_names.contains(&"event_a".to_string()));
    assert!(event_names.contains(&"event_b".to_string()));
    assert!(event_names.contains(&"event_c".to_string()));

    Ok(())
}
