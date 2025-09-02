use anyhow::Result;
use async_trait::async_trait;
use kafka_deduplicator::kafka::{
    message::{AckableMessage, MessageProcessor},
    rebalance_handler::RebalanceHandler,
    stateful_consumer::StatefulKafkaConsumer,
    ConsumerConfigBuilder,
};
use kafka_deduplicator::processor_pool::ProcessorPool;
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::Consumer,
    producer::{FutureProducer, FutureRecord, Producer},
    util::Timeout,
};
use serde_json::json;
use std::sync::OnceLock;
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::sync::{mpsc, Mutex as TokioMutex};
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";

// Global mutex to serialize Kafka integration tests (using async-aware Tokio Mutex)
static KAFKA_TEST_MUTEX: OnceLock<TokioMutex<()>> = OnceLock::new();

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

        // Successfully process the message
        message.ack().await;
        Ok(())
    }
}

/// Helper to create test Kafka topics
async fn create_test_topics(topics: Vec<&str>) -> Result<()> {
    let admin_client: AdminClient<_> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topics: Vec<NewTopic> = topics
        .into_iter()
        .map(|topic| NewTopic::new(topic, 3, TopicReplication::Fixed(1)))
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

/// Produce test messages to Kafka
async fn produce_test_messages(topic: &str, count: usize) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for i in 0..count {
        let event = json!({
            "uuid": Uuid::new_v4().to_string(),
            "distinct_id": format!("test_user_{}", i % 10),
            "event": format!("test_event_{}", i % 5),
            "timestamp": chrono::Utc::now().to_rfc3339(),
            "properties": {
                "index": i,
                "test": true,
            }
        });

        let key = format!("key_{i}");
        let payload = serde_json::to_string(&event)?;

        let record = FutureRecord::to(topic).key(&key).payload(&payload);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e:?}"))?;
    }

    producer.flush(Timeout::After(Duration::from_secs(5)))?;
    Ok(())
}

#[tokio::test]
async fn test_consumer_error_recovery() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let test_topic = format!("test_error_recovery_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    // Create topics
    create_test_topics(vec![&test_topic]).await?;

    // Produce test messages
    produce_test_messages(&test_topic, 20).await?;

    // Create mock processor with 20% failure rate
    let processor = MockMessageProcessor::new();
    processor.set_failure_rate(20);

    // Create consumer
    let consumer_config = ConsumerConfigBuilder::new(KAFKA_BROKERS, &group_id)
        .offset_reset("earliest")
        .build();

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles = processor_pool.start();

    let consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        Arc::new(EmptyRebalanceHandler),
        message_sender,
        10,
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption in background
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // Let it process for a bit
    tokio::time::sleep(Duration::from_secs(5)).await;

    // Check that we processed messages despite failures
    let processed = processor.get_processed_count();
    assert!(
        processed >= 16,
        "Should have processed at least 80% of messages, got {processed}"
    );

    // Shutdown
    let _ = shutdown_tx.send(());
    let _ = tokio::time::timeout(Duration::from_secs(10), consumer_handle).await;

    Ok(())
}

#[tokio::test]
async fn test_consumer_processing_delay_resilience() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let test_topic = format!("test_delay_resilience_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    // Create topics
    create_test_topics(vec![&test_topic]).await?;

    // Produce test messages
    produce_test_messages(&test_topic, 50).await?;

    // Create mock processor with 100ms delay per message
    let processor = MockMessageProcessor::new();
    processor.set_processing_delay(100);

    // Create consumer with high concurrency
    let consumer_config = ConsumerConfigBuilder::new(KAFKA_BROKERS, &group_id)
        .offset_reset("earliest")
        .build();

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool with more workers for concurrent processing
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 4);
    let _pool_handles = processor_pool.start();

    let consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        Arc::new(EmptyRebalanceHandler),
        message_sender,
        20, // Higher concurrency to handle slow processing
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // Wait for processing (50 messages * 100ms = 5s minimum, but with concurrency should be faster)
    tokio::time::sleep(Duration::from_secs(10)).await;

    // Check all messages were processed despite delay
    let processed = processor.get_processed_count();
    assert_eq!(
        processed, 50,
        "Should have processed all 50 messages despite delay"
    );

    // Shutdown
    let _ = shutdown_tx.send(());
    let _ = tokio::time::timeout(Duration::from_secs(10), consumer_handle).await;

    Ok(())
}

#[tokio::test]
async fn test_consumer_failure_notification() -> Result<()> {
    let _guard = KAFKA_TEST_MUTEX
        .get_or_init(|| TokioMutex::new(()))
        .lock()
        .await;

    let test_topic = format!("test_failure_notification_{}", Uuid::new_v4());
    let group_id = format!("test_group_{}", Uuid::new_v4());

    // Create topics
    create_test_topics(vec![&test_topic]).await?;

    // Produce test messages
    produce_test_messages(&test_topic, 10).await?;

    // Create failure notification channel
    let (failure_tx, mut failure_rx) = mpsc::unbounded_channel();

    // Create mock processor that fails every other message
    let processor = MockMessageProcessor::new();
    processor.set_failure_rate(50);
    processor.set_failure_sender(failure_tx);

    // Create consumer
    let consumer_config = ConsumerConfigBuilder::new(KAFKA_BROKERS, &group_id)
        .offset_reset("earliest")
        .build();

    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    // Create processor pool
    let (message_sender, processor_pool) = ProcessorPool::new(processor.clone(), 1);
    let _pool_handles = processor_pool.start();

    let consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        Arc::new(EmptyRebalanceHandler),
        message_sender,
        10,
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    consumer.inner_consumer().subscribe(&[&test_topic])?;

    // Start consumption
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // Collect failure notifications
    let mut failures = Vec::new();
    let collect_handle = tokio::spawn(async move {
        while let Some(failure) = failure_rx.recv().await {
            failures.push(failure);
        }
        failures
    });

    // Let it process
    tokio::time::sleep(Duration::from_secs(5)).await;

    // Shutdown
    let _ = shutdown_tx.send(());
    let _ = tokio::time::timeout(Duration::from_secs(10), consumer_handle).await;

    // Check we got failure notifications
    drop(processor); // Drop to close the channel
    let failures = collect_handle.await?;
    assert!(
        !failures.is_empty(),
        "Should have received failure notifications"
    );
    println!("Received {} failure notifications", failures.len());

    Ok(())
}

// Simple rebalance handler for tests
struct EmptyRebalanceHandler;

#[async_trait]
impl RebalanceHandler for EmptyRebalanceHandler {
    async fn on_partitions_assigned(
        &self,
        _partitions: &rdkafka::TopicPartitionList,
    ) -> Result<()> {
        Ok(())
    }

    async fn on_partitions_revoked(&self, _partitions: &rdkafka::TopicPartitionList) -> Result<()> {
        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        Ok(())
    }
}
