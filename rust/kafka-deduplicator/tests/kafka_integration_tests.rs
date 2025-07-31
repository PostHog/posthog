use anyhow::Result;
use async_trait::async_trait;
use kafka_deduplicator::kafka::{
    generic_consumer::GenericKafkaConsumer,
    generic_context::GenericConsumerContext, 
    message::{AckableMessage, MessageProcessor},
    rebalance_handler::RebalanceHandler,
};
use rdkafka::{
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
    TopicPartitionList,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC: &str = "kafka-deduplicator-integration-test";

/// Test message processor that counts processed messages
#[derive(Clone, Default)]
struct TestProcessor {
    processed_count: Arc<AtomicUsize>,
    failed_count: Arc<AtomicUsize>,
    should_fail: Arc<AtomicUsize>, // Messages to fail (for testing error handling)
}

impl TestProcessor {
    fn new() -> Self {
        Self::default()
    }

    fn get_processed_count(&self) -> usize {
        self.processed_count.load(Ordering::SeqCst)
    }

    fn get_failed_count(&self) -> usize {
        self.failed_count.load(Ordering::SeqCst)
    }

    fn set_should_fail(&self, count: usize) {
        self.should_fail.store(count, Ordering::SeqCst);
    }
}

#[async_trait]
impl MessageProcessor for TestProcessor {
    async fn process_message(&self, message: AckableMessage) -> Result<()> {
        // Simulate some processing time
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Check if we should fail this message  
        let current_count = self.should_fail.load(Ordering::SeqCst);
        let should_fail = if current_count > 0 {
            self.should_fail.fetch_sub(1, Ordering::SeqCst) > 0
        } else {
            false
        };
        if should_fail {
            self.failed_count.fetch_add(1, Ordering::SeqCst);
            message.nack("Intentional test failure".to_string()).await;
            return Err(anyhow::anyhow!("Intentional test failure"));
        }

        self.processed_count.fetch_add(1, Ordering::SeqCst);
        message.ack().await;
        Ok(())
    }
}

/// Test rebalance handler that tracks partition assignments
#[derive(Default)]
struct TestRebalanceHandler {
    assigned_partitions: Arc<std::sync::Mutex<Vec<(String, i32)>>>,
    revoked_partitions: Arc<std::sync::Mutex<Vec<(String, i32)>>>,
}

impl TestRebalanceHandler {
    fn get_assigned_partitions(&self) -> Vec<(String, i32)> {
        self.assigned_partitions.lock().unwrap().clone()
    }

    fn get_revoked_partitions(&self) -> Vec<(String, i32)> {
        self.revoked_partitions.lock().unwrap().clone()
    }
}

#[async_trait]
impl RebalanceHandler for TestRebalanceHandler {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        let mut assigned = self.assigned_partitions.lock().unwrap();
        for elem in partitions.elements() {
            assigned.push((elem.topic().to_string(), elem.partition()));
        }
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        let mut revoked = self.revoked_partitions.lock().unwrap();
        for elem in partitions.elements() {
            revoked.push((elem.topic().to_string(), elem.partition()));
        }
        Ok(())
    }
}

/// Helper to create a GenericKafkaConsumer using our abstractions
fn create_generic_kafka_consumer(
    topic: &str,
    group_id: &str,
    processor: TestProcessor,
    rebalance_handler: Arc<dyn RebalanceHandler>,
) -> Result<GenericKafkaConsumer<TestProcessor>> {
    // Create the context with our rebalance handler
    let context = GenericConsumerContext::new(rebalance_handler);

    // Create the underlying rdkafka consumer with our context
    let consumer: StreamConsumer<GenericConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .create_with_context(context)?;

    consumer.subscribe(&[topic])?;

    // Create our GenericKafkaConsumer wrapper
    let kafka_consumer = GenericKafkaConsumer::with_commit_interval(
        consumer,
        processor,
        10,
        Duration::from_secs(1),
    );

    Ok(kafka_consumer)
}

/// Helper to send test messages
async fn send_test_messages(
    topic: &str,
    messages: Vec<(&str, &str)>, // (key, value) pairs
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, value) in messages {
        let record = FutureRecord::to(topic).key(key).payload(value);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {}", e))?;
    }

    // Give kafka some time to process the messages
    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

#[tokio::test]
async fn test_generic_kafka_consumer_message_processing() -> Result<()> {

    let test_topic = format!("{}-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-{}", uuid::Uuid::new_v4());

    // Send test messages first
    let test_messages = vec![
        ("key1", "message1"),
        ("key2", "message2"),
        ("key3", "message3"),
        ("key4", "message4"),
        ("key5", "message5"),
    ];

    send_test_messages(&test_topic, test_messages.clone()).await?;

    // Create consumer using our abstractions
    let processor = TestProcessor::new();
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());
    
    let kafka_consumer = create_generic_kafka_consumer(
        &test_topic,
        &group_id,
        processor.clone(),
        rebalance_handler.clone(),
    )?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move {
        kafka_consumer.start_consumption().await
    });

    // Wait for messages to be processed
    let mut attempts = 0;
    while processor.get_processed_count() < test_messages.len() && attempts < 50 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Stop the consumer
    consumer_handle.abort();

    // Verify results
    assert_eq!(
        processor.get_processed_count(),
        test_messages.len(),
        "Should have processed all messages"
    );
    assert_eq!(processor.get_failed_count(), 0, "Should have no failures");

    // Verify rebalance handler was called
    let assigned = rebalance_handler.get_assigned_partitions();
    assert!(!assigned.is_empty(), "Should have assigned partitions");
    assert!(
        assigned.iter().any(|(topic, _)| topic == &test_topic),
        "Should have assigned the test topic"
    );

    Ok(())
}

#[tokio::test]
async fn test_generic_kafka_consumer_error_handling() -> Result<()> {
    
    let test_topic = format!("{}-error-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-error-{}", uuid::Uuid::new_v4());

    // Send test messages
    let test_messages = vec![
        ("key1", "message1"),
        ("key2", "message2"),
        ("key3", "message3"),
    ];

    send_test_messages(&test_topic, test_messages.clone()).await?;

    // Create consumer with failing processor
    let processor = TestProcessor::new();
    processor.set_should_fail(2); // Fail first 2 messages
    
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());
    
    let kafka_consumer = create_generic_kafka_consumer(
        &test_topic,
        &group_id,
        processor.clone(),
        rebalance_handler,
    )?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move {
        kafka_consumer.start_consumption().await
    });

    // Wait for messages to be processed
    let mut attempts = 0;
    while (processor.get_processed_count() + processor.get_failed_count()) < test_messages.len()
        && attempts < 50
    {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Stop the consumer
    consumer_handle.abort();

    // Verify results
    assert_eq!(processor.get_processed_count(), 1, "Should have processed 1 message");
    assert_eq!(processor.get_failed_count(), 2, "Should have failed 2 messages");

    Ok(())
}

#[tokio::test]
async fn test_generic_kafka_consumer_tracker_stats() -> Result<()> {

    let test_topic = format!("{}-stats-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-stats-{}", uuid::Uuid::new_v4());

    // Create consumer using our abstractions
    let processor = TestProcessor::new();
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());
    
    let kafka_consumer = create_generic_kafka_consumer(
        &test_topic,
        &group_id,
        processor,
        rebalance_handler,
    )?;

    // Check initial stats
    let initial_stats = kafka_consumer.get_tracker_stats().await;
    assert_eq!(initial_stats.in_flight, 0);
    assert_eq!(initial_stats.completed, 0);
    assert_eq!(initial_stats.failed, 0);

    Ok(())
}
