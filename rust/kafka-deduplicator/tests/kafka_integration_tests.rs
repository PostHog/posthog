use anyhow::Result;
use async_trait::async_trait;
use kafka_deduplicator::kafka::{
    message::{AckableMessage, MessageProcessor},
    rebalance_handler::RebalanceHandler,
    stateful_consumer::StatefulKafkaConsumer,
    types::Partition,
};
use kafka_deduplicator::processor_pool::ProcessorPool;
use rdkafka::{
    config::ClientConfig,
    consumer::Consumer,
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
    assigned_partitions: Arc<std::sync::Mutex<Vec<Partition>>>,
    revoked_partitions: Arc<std::sync::Mutex<Vec<Partition>>>,
}

impl TestRebalanceHandler {
    fn get_assigned_partitions(&self) -> Vec<Partition> {
        self.assigned_partitions.lock().unwrap().clone()
    }
}

#[async_trait]
impl RebalanceHandler for TestRebalanceHandler {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        let mut assigned = self.assigned_partitions.lock().unwrap();
        for elem in partitions.elements() {
            assigned.push(Partition::from(elem));
        }
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        let mut revoked = self.revoked_partitions.lock().unwrap();
        for elem in partitions.elements() {
            revoked.push(Partition::from(elem));
        }
        Ok(())
    }
}

/// Helper to create a StatefulKafkaConsumer and ProcessorPool using our abstractions
fn create_stateful_kafka_consumer_with_pool(
    topic: &str,
    group_id: &str,
    processor: TestProcessor,
    rebalance_handler: Arc<dyn RebalanceHandler>,
) -> Result<(
    StatefulKafkaConsumer,
    Vec<tokio::task::JoinHandle<()>>,
    tokio::sync::oneshot::Sender<()>,
)> {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000");

    // Create shutdown channel - return sender so test can control shutdown
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool with one worker for testing
    let (message_sender, processor_pool) = ProcessorPool::new(processor, 1);
    let pool_handles = processor_pool.start();

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler,
        message_sender,
        10,
        Duration::from_secs(1),
        shutdown_rx,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[topic])?;

    Ok((kafka_consumer, pool_handles.0, shutdown_tx))
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

    let (kafka_consumer, _pool_handles, shutdown_tx) = create_stateful_kafka_consumer_with_pool(
        &test_topic,
        &group_id,
        processor.clone(),
        rebalance_handler.clone(),
    )?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Wait for messages to be processed
    let mut attempts = 0;
    while processor.get_processed_count() < test_messages.len() && attempts < 50 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Send graceful shutdown signal
    let _ = shutdown_tx.send(());

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

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
        assigned
            .iter()
            .any(|partition| partition.topic() == test_topic),
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

    let (kafka_consumer, _pool_handles, shutdown_tx) = create_stateful_kafka_consumer_with_pool(
        &test_topic,
        &group_id,
        processor.clone(),
        rebalance_handler,
    )?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Wait for messages to be processed
    let mut attempts = 0;
    while (processor.get_processed_count() + processor.get_failed_count()) < test_messages.len()
        && attempts < 50
    {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Send graceful shutdown signal
    let _ = shutdown_tx.send(());

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

    // Verify results
    assert_eq!(
        processor.get_processed_count(),
        1,
        "Should have processed 1 message"
    );
    assert_eq!(
        processor.get_failed_count(),
        2,
        "Should have failed 2 messages"
    );

    Ok(())
}

#[tokio::test]
async fn test_generic_kafka_consumer_tracker_stats() -> Result<()> {
    let test_topic = format!("{}-stats-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-stats-{}", uuid::Uuid::new_v4());

    // Create consumer using our abstractions
    let processor = TestProcessor::new();
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());

    let (kafka_consumer, _pool_handles, _shutdown_tx) = create_stateful_kafka_consumer_with_pool(
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

#[tokio::test]
async fn test_partition_aware_message_filtering() -> Result<()> {
    let test_topic = format!("{}-partition-filter-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-partition-filter-{}", uuid::Uuid::new_v4());

    // Send test messages
    let test_messages = vec![
        ("key1", "message1"),
        ("key2", "message2"),
        ("key3", "message3"),
        ("key4", "message4"),
        ("key5", "message5"),
    ];

    send_test_messages(&test_topic, test_messages.clone()).await?;

    // Create processor that tracks which messages were processed
    let processor = TestProcessor::new();
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());

    let config = rdkafka::ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .clone();

    // Create shutdown channel
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool with one worker for testing
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles = processor_pool.start();

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler.clone(),
        message_sender,
        10,
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    // Subscribe to the topic
    kafka_consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption in background
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Wait for some messages to be processed
    let mut attempts = 0;
    while processor.get_processed_count() < 2 && attempts < 50 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Verify that partitions were assigned
    let assigned_partitions = rebalance_handler.get_assigned_partitions();
    assert!(
        !assigned_partitions.is_empty(),
        "Should have assigned partitions"
    );

    // Verify some messages were processed
    assert!(
        processor.get_processed_count() > 0,
        "Should have processed some messages"
    );

    // Send graceful shutdown signal
    let _ = shutdown_tx.send(());

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

    Ok(())
}

#[tokio::test]
async fn test_graceful_shutdown_with_in_flight_messages() -> Result<()> {
    let test_topic = format!("{}-graceful-shutdown-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-graceful-{}", uuid::Uuid::new_v4());

    // Send test messages
    let test_messages = vec![
        ("key1", "message1"),
        ("key2", "message2"),
        ("key3", "message3"),
    ];

    send_test_messages(&test_topic, test_messages.clone()).await?;

    // Create processor with artificial delay to simulate slow processing
    #[derive(Clone)]
    struct SlowProcessor {
        processed_count: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl MessageProcessor for SlowProcessor {
        async fn process_message(&self, message: AckableMessage) -> Result<()> {
            // Add delay to simulate slow processing
            tokio::time::sleep(Duration::from_millis(200)).await;

            self.processed_count.fetch_add(1, Ordering::SeqCst);
            message.ack().await;
            Ok(())
        }
    }

    let processor = SlowProcessor {
        processed_count: Arc::new(AtomicUsize::new(0)),
    };
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());

    let config = rdkafka::ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .clone();

    // Create shutdown channel for graceful shutdown
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool with one worker for testing
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles = processor_pool.start();

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler.clone(),
        message_sender,
        10,
        Duration::from_secs(1),
        shutdown_rx,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption with graceful shutdown support
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Let it run briefly to start processing some messages
    tokio::time::sleep(Duration::from_millis(300)).await;

    // Get initial stats to verify messages are being processed
    let initial_stats = rebalance_handler.get_assigned_partitions();
    assert!(
        !initial_stats.is_empty(),
        "Should have assigned partitions after startup"
    );

    // Send graceful shutdown signal
    let _ = shutdown_tx.send(());

    // Wait for graceful shutdown to complete
    match consumer_handle.await {
        Ok(Ok(())) => {
            println!("Consumer shut down gracefully");
        }
        Ok(Err(e)) => {
            panic!("Consumer returned error during shutdown: {e}");
        }
        Err(e) => {
            panic!("Consumer task failed: {e}");
        }
    }

    // Verify that some messages were processed during the test
    let processed_count = processor
        .processed_count
        .load(std::sync::atomic::Ordering::SeqCst);
    assert!(
        processed_count > 0,
        "Should have processed at least some messages during graceful shutdown test, got: {processed_count}"
    );

    Ok(())
}

#[tokio::test]
async fn test_factory_method_integration() -> Result<()> {
    let test_topic = format!("{}-factory-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-factory-{}", uuid::Uuid::new_v4());

    let processor = TestProcessor::new();
    let rebalance_handler = Arc::new(TestRebalanceHandler::default());

    let config = rdkafka::ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .clone();

    // Test both factory methods
    let (_, shutdown_rx1) = tokio::sync::oneshot::channel();
    let (message_sender1, processor_pool1) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles1 = processor_pool1.start();
    let consumer1 = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler.clone(),
        message_sender1,
        5,
        Duration::from_secs(5),
        shutdown_rx1,
    )?;

    let (_, shutdown_rx2) = tokio::sync::oneshot::channel();
    let (message_sender2, processor_pool2) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles2 = processor_pool2.start();
    let consumer2 = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler.clone(),
        message_sender2,
        10,
        Duration::from_secs(2),
        shutdown_rx2,
    )?;

    // Verify consumers were created successfully
    assert_eq!(consumer1.get_tracker_stats().await.in_flight, 0);
    assert_eq!(consumer2.get_tracker_stats().await.in_flight, 0);

    // Subscribe and verify no errors
    consumer1.inner_consumer().subscribe(&[&test_topic])?;
    consumer2.inner_consumer().subscribe(&[&test_topic])?;

    Ok(())
}

#[tokio::test]
async fn test_rebalance_barrier_with_fencing() -> Result<()> {
    let test_topic = format!("{}-rebalance-barrier-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-group-rebalance-{}", uuid::Uuid::new_v4());

    // Send test messages first
    let test_messages = vec![
        ("key1", "message1"),
        ("key2", "message2"),
        ("key3", "message3"),
        ("key4", "message4"),
        ("key5", "message5"),
    ];

    send_test_messages(&test_topic, test_messages.clone()).await?;

    // Create a slow processor to simulate in-flight messages during rebalance
    #[derive(Clone)]
    struct RebalanceTestProcessor {
        processed_count: Arc<AtomicUsize>,
        processing_delay: Arc<AtomicUsize>, // milliseconds
    }

    #[async_trait]
    impl MessageProcessor for RebalanceTestProcessor {
        async fn process_message(&self, message: AckableMessage) -> Result<()> {
            let delay = self.processing_delay.load(Ordering::SeqCst);
            if delay > 0 {
                tokio::time::sleep(Duration::from_millis(delay as u64)).await;
            }

            self.processed_count.fetch_add(1, Ordering::SeqCst);
            message.ack().await;
            Ok(())
        }
    }

    let processor = RebalanceTestProcessor {
        processed_count: Arc::new(AtomicUsize::new(0)),
        processing_delay: Arc::new(AtomicUsize::new(100)), // 100ms delay
    };

    // Track rebalance events
    #[derive(Default)]
    struct TrackingRebalanceHandler {
        revoked_count: Arc<AtomicUsize>,
        assigned_count: Arc<AtomicUsize>,
        pre_rebalance_count: Arc<AtomicUsize>,
        post_rebalance_count: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl RebalanceHandler for TrackingRebalanceHandler {
        async fn on_partitions_assigned(&self, _partitions: &TopicPartitionList) -> Result<()> {
            self.assigned_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        async fn on_partitions_revoked(&self, _partitions: &TopicPartitionList) -> Result<()> {
            self.revoked_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        async fn on_pre_rebalance(&self) -> Result<()> {
            self.pre_rebalance_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        async fn on_post_rebalance(&self) -> Result<()> {
            self.post_rebalance_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    let rebalance_handler = Arc::new(TrackingRebalanceHandler::default());

    let config = rdkafka::ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .clone();

    // Create shutdown channel
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool with one worker for testing
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles = processor_pool.start();

    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &config,
        rebalance_handler.clone(),
        message_sender,
        5, // limit in-flight messages
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    kafka_consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption
    let consumer_handle = tokio::spawn(async move { kafka_consumer.start_consumption().await });

    // Wait for initial assignment
    let mut attempts = 0;
    while rebalance_handler.assigned_count.load(Ordering::SeqCst) == 0 && attempts < 50 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        attempts += 1;
    }

    // Verify assignment happened
    assert!(
        rebalance_handler.assigned_count.load(Ordering::SeqCst) > 0,
        "Should have assigned partitions"
    );

    // Let some messages start processing
    tokio::time::sleep(Duration::from_millis(200)).await;

    // Send graceful shutdown signal (will trigger rebalance)
    let _ = shutdown_tx.send(());

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

    // Give time for handlers to be called
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Verify pre-rebalance was called (non-blocking)
    assert!(
        rebalance_handler.pre_rebalance_count.load(Ordering::SeqCst) > 0,
        "Pre-rebalance should have been called"
    );

    Ok(())
}
