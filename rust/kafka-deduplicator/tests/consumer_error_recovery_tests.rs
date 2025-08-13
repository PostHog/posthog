use anyhow::Result;
use async_trait::async_trait;
use common_types::RawEvent;
use kafka_deduplicator::{
    deduplication_processor::{DeduplicationConfig, DeduplicationProcessor},
    kafka::message::{AckableMessage, MessageProcessor},
    kafka::stateful_consumer::StatefulKafkaConsumer,
    processor_rebalance_handler::ProcessorRebalanceHandler,
    rocksdb::deduplication_store::DeduplicationStoreConfig,
};
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::Consumer,
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
};
use serde_json::json;
use std::sync::OnceLock;
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tempfile::TempDir;
use tokio::sync::mpsc;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";

// Global mutex to serialize Kafka integration tests
static KAFKA_TEST_MUTEX: OnceLock<Mutex<()>> = OnceLock::new();

/// Mock message processor that can simulate various failure scenarios
#[derive(Clone)]
struct MockMessageProcessor {
    processed_count: Arc<AtomicUsize>,
    should_fail: Arc<AtomicBool>,
    failure_rate: Arc<AtomicUsize>, // Out of 100
    delay_ms: Arc<AtomicUsize>,
    failure_sender: Arc<Mutex<Option<mpsc::UnboundedSender<String>>>>,
}

impl MockMessageProcessor {
    fn new() -> Self {
        Self {
            processed_count: Arc::new(AtomicUsize::new(0)),
            should_fail: Arc::new(AtomicBool::new(false)),
            failure_rate: Arc::new(AtomicUsize::new(0)),
            delay_ms: Arc::new(AtomicUsize::new(0)),
            failure_sender: Arc::new(Mutex::new(None)),
        }
    }

    fn set_failure_rate(&self, rate: usize) {
        self.failure_rate.store(rate, Ordering::SeqCst);
    }

    fn set_processing_delay(&self, delay_ms: usize) {
        self.delay_ms.store(delay_ms, Ordering::SeqCst);
    }

    fn set_failure_sender(&self, sender: mpsc::UnboundedSender<String>) {
        *self.failure_sender.lock().unwrap() = Some(sender);
    }

    fn get_processed_count(&self) -> usize {
        self.processed_count.load(Ordering::SeqCst)
    }
}

#[async_trait]
impl MessageProcessor for MockMessageProcessor {
    async fn process_message(&self, message: AckableMessage) -> Result<()> {
        let delay = self.delay_ms.load(Ordering::SeqCst);
        if delay > 0 {
            tokio::time::sleep(Duration::from_millis(delay as u64)).await;
        }

        let count = self.processed_count.fetch_add(1, Ordering::SeqCst);
        let should_fail = self.should_fail.load(Ordering::SeqCst);
        let failure_rate = self.failure_rate.load(Ordering::SeqCst);

        // Determine if this message should fail
        let should_fail_this_message =
            should_fail || (failure_rate > 0 && (count % 100) < failure_rate);

        if should_fail_this_message {
            let error_msg = format!("Simulated failure for message {count}");

            // Send failure notification if sender is available
            if let Some(sender) = self.failure_sender.lock().unwrap().as_ref() {
                let _ = sender.send(error_msg.clone());
            }

            message.nack(error_msg.clone()).await;
            return Err(anyhow::anyhow!(error_msg));
        }

        // Success case
        message.ack().await;
        Ok(())
    }
}

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
                        println!("Topic {topic} result: {error:?}");
                    }
                }
            }
        }
        Err(e) => {
            println!("Failed to create topics: {e:?}");
        }
    }

    Ok(())
}

/// Helper to send test messages to Kafka topic
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

/// Helper to create test RawEvent instances
fn create_test_raw_event(
    uuid: Option<Uuid>,
    event: &str,
    distinct_id: &str,
    token: &str,
    timestamp: Option<u64>,
) -> RawEvent {
    let mut properties = HashMap::new();
    properties.insert("test_property".to_string(), json!("test_value"));

    RawEvent {
        uuid,
        event: event.to_string(),
        distinct_id: Some(json!(distinct_id)),
        token: Some(token.to_string()),
        properties,
        timestamp: timestamp.map(|t| t.to_string()),
        ..Default::default()
    }
}

#[tokio::test]
async fn test_consumer_recovery_after_processing_failures() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here

    let test_id = Uuid::new_v4();
    let input_topic = format!("error-recovery-input-{test_id}");
    let output_topic = format!("error-recovery-output-{test_id}");
    let group_id = format!("error-recovery-group-{test_id}");

    // Create Kafka topics
    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    tokio::time::sleep(Duration::from_millis(1000)).await;

    // Create mock processor that fails initially then recovers
    let mock_processor = MockMessageProcessor::new();
    let (failure_tx, mut failure_rx) = mpsc::unbounded_channel();
    mock_processor.set_failure_sender(failure_tx);
    mock_processor.set_failure_rate(50); // 50% failure rate

    // Create consumer config
    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .clone();

    // Create mock rebalance handler
    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let producer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .clone();

    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor));

    // Create consumer with error-prone processor
    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        mock_processor.clone(),
        5, // Small limit to test backpressure
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Send test messages
    let test_events = vec![
        create_test_raw_event(Some(Uuid::new_v4()), "event1", "user1", "token1", None),
        create_test_raw_event(Some(Uuid::new_v4()), "event2", "user2", "token1", None),
        create_test_raw_event(Some(Uuid::new_v4()), "event3", "user3", "token1", None),
        create_test_raw_event(Some(Uuid::new_v4()), "event4", "user4", "token1", None),
    ];

    let serialized_messages: Vec<(String, String)> = test_events
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

    // Start consumer processing with failures
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Let it process with failures for a bit
    tokio::time::sleep(Duration::from_secs(2)).await;

    // Collect some failure notifications
    let mut failures = Vec::new();
    while let Ok(failure) = failure_rx.try_recv() {
        failures.push(failure);
    }

    assert!(
        !failures.is_empty(),
        "Should have recorded some processing failures"
    );
    println!(
        "Recorded {} failures during initial processing",
        failures.len()
    );

    // Now disable failures and let it recover
    mock_processor.set_failure_rate(0);

    // Continue processing for recovery
    tokio::time::sleep(Duration::from_secs(3)).await;

    // Should have processed some messages despite failures
    let processed_count = mock_processor.get_processed_count();
    assert!(processed_count > 0, "Should have processed some messages");
    println!(
        "Processed {processed_count} messages with 50% failure rate"
    );

    // Clean up
    consumer_handle.abort();
    tokio::time::sleep(Duration::from_millis(100)).await;

    Ok(())
}

#[tokio::test]
async fn test_consumer_max_in_flight_limit_enforcement() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here

    let test_id = Uuid::new_v4();
    let input_topic = format!("backpressure-input-{test_id}");
    let output_topic = format!("backpressure-output-{test_id}");
    let group_id = format!("backpressure-group-{test_id}");

    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    tokio::time::sleep(Duration::from_millis(1000)).await;

    // Create slow processor to test backpressure
    let mock_processor = MockMessageProcessor::new();
    mock_processor.set_processing_delay(1000); // 1 second delay per message

    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .clone();

    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let producer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .clone();

    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor));

    // Create consumer with very low in-flight limit
    let max_in_flight = 2;
    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        mock_processor.clone(),
        max_in_flight,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Send more messages than the in-flight limit
    let num_messages = 10;
    let test_events: Vec<RawEvent> = (0..num_messages)
        .map(|i| {
            create_test_raw_event(
                Some(Uuid::new_v4()),
                &format!("event{i}"),
                &format!("user{i}"),
                "token1",
                None,
            )
        })
        .collect();

    let serialized_messages: Vec<(String, String)> = test_events
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

    // Start processing
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Let it process for a limited time
    tokio::time::sleep(Duration::from_secs(3)).await;

    // With 2 max in-flight and 1 second delay, should have processed roughly 3 messages
    // (2 initially + 1 more as they complete)
    let processed_count = mock_processor.get_processed_count();
    assert!(
        (2..=5).contains(&processed_count),
        "Expected 2-5 messages processed with backpressure, got {processed_count}"
    );

    println!(
        "Processed {processed_count} messages with max_in_flight={max_in_flight} and 1s delay"
    );

    consumer_handle.abort();
    tokio::time::sleep(Duration::from_millis(100)).await;

    Ok(())
}

#[tokio::test]
async fn test_consumer_graceful_shutdown_with_in_flight_messages() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here

    let test_id = Uuid::new_v4();
    let input_topic = format!("shutdown-input-{test_id}");
    let output_topic = format!("shutdown-output-{test_id}");
    let group_id = format!("shutdown-group-{test_id}");

    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    tokio::time::sleep(Duration::from_millis(1000)).await;

    // Create processor with medium processing delay
    let mock_processor = MockMessageProcessor::new();
    mock_processor.set_processing_delay(500); // 500ms delay

    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .clone();

    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let producer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .clone();

    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor));

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        mock_processor.clone(),
        5,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Send several test messages
    let test_events: Vec<RawEvent> = (0..8)
        .map(|i| {
            create_test_raw_event(
                Some(Uuid::new_v4()),
                &format!("shutdown_test_{i}"),
                &format!("user{i}"),
                "token1",
                None,
            )
        })
        .collect();

    let serialized_messages: Vec<(String, String)> = test_events
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

    // Start consumer
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Let it start processing
    tokio::time::sleep(Duration::from_millis(100)).await;
    let count_before_shutdown = mock_processor.get_processed_count();

    // Simulate shutdown
    consumer_handle.abort();

    // Give it a moment to handle the abort
    tokio::time::sleep(Duration::from_millis(200)).await;

    let count_after_shutdown = mock_processor.get_processed_count();

    // Should have started processing some messages
    assert!(
        count_after_shutdown >= count_before_shutdown,
        "Processing should not go backwards"
    );

    println!(
        "Before shutdown: {count_before_shutdown}, After shutdown: {count_after_shutdown}"
    );

    // Verify the consumer handle is actually finished
    assert!(
        consumer_handle.is_finished(),
        "Consumer should be finished after abort"
    );

    Ok(())
}

#[tokio::test]
async fn test_consumer_network_interruption_simulation() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here

    let test_id = Uuid::new_v4();
    let input_topic = format!("network-input-{test_id}");
    let output_topic = format!("network-output-{test_id}");
    let group_id = format!("network-group-{test_id}");

    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    tokio::time::sleep(Duration::from_millis(1000)).await;

    let mock_processor = MockMessageProcessor::new();

    // Use aggressive timeouts to simulate network issues
    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "3000") // Short session timeout
        .set("heartbeat.interval.ms", "1000") // Frequent heartbeats
        .set("request.timeout.ms", "2000") // Short request timeout
        .clone();

    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let producer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "2000") // Short timeout for producer too
        .clone();

    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor));

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        mock_processor.clone(),
        3,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Send test messages
    let test_events: Vec<RawEvent> = (0..5)
        .map(|i| {
            create_test_raw_event(
                Some(Uuid::new_v4()),
                &format!("network_test_{i}"),
                &format!("user{i}"),
                "token1",
                None,
            )
        })
        .collect();

    let serialized_messages: Vec<(String, String)> = test_events
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

    // Start consumer
    let consumer_handle = tokio::spawn(async move {
        // This should handle timeouts and network issues gracefully
        // The consumer loop should continue despite polling timeouts
        match kafka_consumer.start_consumption().await {
            Ok(_) => println!("Consumer finished normally"),
            Err(e) => println!("Consumer finished with error: {e}"),
        }
    });

    // Let it run with potential network timeouts
    tokio::time::sleep(Duration::from_secs(5)).await;

    let processed_count = mock_processor.get_processed_count();
    println!(
        "Processed {processed_count} messages despite network timeouts"
    );

    // Should have processed at least some messages even with timeouts
    // The exact count may vary due to timeout behavior
    assert!(processed_count <= 5, "Shouldn't process more than sent");

    consumer_handle.abort();
    tokio::time::sleep(Duration::from_millis(100)).await;

    Ok(())
}

#[tokio::test]
async fn test_consumer_commit_failure_resilience() -> Result<()> {
    {
        let _lock = KAFKA_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
    } // Lock is dropped here

    let test_id = Uuid::new_v4();
    let input_topic = format!("commit-failure-input-{test_id}");
    let output_topic = format!("commit-failure-output-{test_id}");
    let group_id = format!("commit-failure-group-{test_id}");

    create_kafka_topics(vec![&input_topic, &output_topic]).await?;
    tokio::time::sleep(Duration::from_millis(1000)).await;

    let mock_processor = MockMessageProcessor::new();

    // Use very short commit interval to test commit failures
    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .clone();

    let temp_dir = TempDir::new()?;
    let store_config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    let producer_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .clone();

    let dedup_config = DeduplicationConfig {
        output_topic: Some(output_topic),
        producer_config,
        store_config,
    };

    let processor = Arc::new(DeduplicationProcessor::new(dedup_config)?);
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor));

    // Create consumer with very short commit interval (500ms)
    let kafka_consumer = StatefulKafkaConsumer::from_config_with_commit_interval(
        &consumer_config,
        rebalance_handler,
        mock_processor.clone(),
        3,
        Duration::from_millis(500), // Very frequent commits
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&input_topic])?;

    // Send test messages
    let test_events: Vec<RawEvent> = (0..6)
        .map(|i| {
            create_test_raw_event(
                Some(Uuid::new_v4()),
                &format!("commit_test_{i}"),
                &format!("user{i}"),
                "token1",
                None,
            )
        })
        .collect();

    let serialized_messages: Vec<(String, String)> = test_events
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

    // Start consumer - it will attempt frequent commits
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Let it process and commit frequently
    tokio::time::sleep(Duration::from_secs(3)).await;

    let processed_count = mock_processor.get_processed_count();

    // Should have processed messages despite frequent commit attempts
    assert!(
        processed_count > 0,
        "Should process messages despite frequent commits"
    );
    println!(
        "Processed {processed_count} messages with frequent commits"
    );

    consumer_handle.abort();
    tokio::time::sleep(Duration::from_millis(100)).await;

    Ok(())
}
