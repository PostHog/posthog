use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::async_trait;
use kafka_deduplicator::kafka::{
    batch_consumer::*,
    batch_message::*,
    offset_tracker::OffsetTracker,
    partition_router::{shutdown_workers, PartitionRouter, PartitionRouterConfig},
    rebalance_handler::RebalanceHandler,
    routing_processor::RoutingProcessor,
    test_utils::TestRebalanceHandler,
    types::Partition,
};

use common_types::CapturedEvent;

use anyhow::Result;
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
    TopicPartitionList,
};
use time::OffsetDateTime;
use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver, UnboundedSender};
use tokio::sync::oneshot;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC_BASE: &str = "kdedup-batch-consumer-integration-test";

/// Helper to create a BatchKafkaConsumer for integration smoke tests
#[allow(clippy::type_complexity)]
fn create_batch_kafka_consumer(
    topic: &str,
    group_id: &str,
    batch_size: usize,
    batch_timeout: Duration,
) -> Result<(
    BatchConsumer<CapturedEvent>,
    UnboundedReceiver<Batch<CapturedEvent>>,
    oneshot::Sender<()>,
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
    let (shutdown_tx, shutdown_rx) = oneshot::channel();

    let (chan_tx, chan_rx) = unbounded_channel();

    // Create a test processor that sends batches to the channel
    struct TestProcessor {
        sender: UnboundedSender<Batch<CapturedEvent>>,
    }

    #[async_trait]
    impl BatchConsumerProcessor<CapturedEvent> for TestProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<CapturedEvent>>) -> Result<()> {
            let mut batch = Batch::new();
            for msg in messages {
                batch.push_message(msg);
            }
            self.sender
                .send(batch)
                .map_err(|e| anyhow::anyhow!("Failed to send batch: {e}"))
        }
    }

    let processor = Arc::new(TestProcessor { sender: chan_tx });
    let offset_tracker = Arc::new(OffsetTracker::new());

    let consumer = BatchConsumer::<CapturedEvent>::new(
        &config,
        Arc::new(TestRebalanceHandler::default()),
        processor,
        offset_tracker,
        shutdown_rx,
        topic,
        batch_size,
        batch_timeout,
        Duration::from_secs(1),
    )?;

    Ok((consumer, chan_rx, shutdown_tx))
}

/// Helper to send test messages
async fn send_test_messages(
    topic: &str,
    messages: Vec<(String, String)>, // (key, value) pairs
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, value) in messages {
        let record = FutureRecord::to(topic).key(&key).payload(&value);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;
    }

    // Give kafka some time to process the messages
    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

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

    // Create a mock KafkaMessage for testing
    CapturedEvent {
        uuid: event_uuid,
        distinct_id: distinct_id.to_string(),
        session_id: None,
        ip: "127.0.0.1".to_string(),
        now: now_rfc3339.clone(),
        token: token.to_string(),
        // serialized RawEvent
        data: data.to_string(),
        sent_at: Some(now_offset_datetime),
        event: event_name.to_string(),
        timestamp: chrono::Utc::now(),
        is_cookieless_mode: false,
        historical_migration: false,
    }
}

// convenience to generate and serialize some simple CapturedEvent message payloads
fn generate_test_messages(count: usize) -> Vec<(String, String)> {
    (0..count)
        .map(|i| {
            let payload = create_captured_event();
            let serialized = serde_json::to_string(&payload).unwrap();
            (format!("key_{i}"), serialized)
        })
        .collect()
}

#[tokio::test]
async fn test_simple_batch_kafka_consumer() -> Result<()> {
    let test_topic = format!("{}-{}", TEST_TOPIC_BASE, uuid::Uuid::now_v7());
    let group_id = format!("test-group-{}", uuid::Uuid::now_v7());
    let batch_size = 3;
    let batch_timeout = Duration::from_millis(100);

    // Send test messages first
    let expected_msg_count = 9;
    let test_messages = generate_test_messages(expected_msg_count);

    send_test_messages(&test_topic, test_messages).await?;

    let (consumer, mut batch_rx, shutdown_tx) =
        create_batch_kafka_consumer(&test_topic, &group_id, batch_size, batch_timeout)?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // this will cause the consumer.recv() loop below to exit
    //when the consumer's start_consumption loop breaks and
    // closes the batch submission channel
    let _shutdown_handle = tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        let _ = shutdown_tx.send(());
    });

    tokio::time::sleep(Duration::from_millis(1)).await;

    let mut msgs_recv = 0;
    while let Some(batch_result) = batch_rx.recv().await {
        let (msgs, errs) = batch_result.unpack();
        if !errs.is_empty() {
            panic!("Errors in batch: {errs:?}");
        }
        assert!(
            msgs.len() <= 3,
            "Batch size should be at most 3, got: {}",
            msgs.len()
        );
        msgs_recv += msgs.len();
    }

    assert_eq!(
        msgs_recv, expected_msg_count,
        "Should have received all messages, got: {msgs_recv}",
    );

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

    Ok(())
}

/// Helper to create a topic with a specific number of partitions
async fn create_topic_with_partitions(topic: &str, num_partitions: i32) -> Result<()> {
    use rdkafka::client::DefaultClientContext;

    let admin_client: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topic = NewTopic::new(topic, num_partitions, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(5)));

    let results = admin_client.create_topics(&[new_topic], &opts).await?;

    for result in results {
        match result {
            Ok(_) => {}
            Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {
                // Topic already exists, that's fine
            }
            Err((topic_name, err)) => {
                return Err(anyhow::anyhow!(
                    "Failed to create topic {topic_name}: {err:?}"
                ));
            }
        }
    }

    // Wait for topic metadata to propagate
    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(())
}

/// Helper to send test messages to a specific partition
async fn send_test_messages_to_partition(
    topic: &str,
    partition: i32,
    messages: Vec<(String, String)>,
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, value) in messages {
        let record = FutureRecord::to(topic)
            .key(&key)
            .payload(&value)
            .partition(partition);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;
    }

    // Give kafka some time to process the messages
    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

/// Test rebalance handler that also manages partition workers via a router
struct RoutingRebalanceHandler {
    inner: TestRebalanceHandler,
    router: Arc<PartitionRouter<CapturedEvent, CountingProcessor>>,
    offset_tracker: Arc<OffsetTracker>,
}

impl RoutingRebalanceHandler {
    fn new(
        router: Arc<PartitionRouter<CapturedEvent, CountingProcessor>>,
        offset_tracker: Arc<OffsetTracker>,
    ) -> Self {
        Self {
            inner: TestRebalanceHandler::default(),
            router,
            offset_tracker,
        }
    }
}

#[async_trait]
impl RebalanceHandler for RoutingRebalanceHandler {
    fn setup_assigned_partitions(&self, partitions: &TopicPartitionList) {
        self.inner.setup_assigned_partitions(partitions);

        // Create workers for assigned partitions
        for elem in partitions.elements() {
            let partition = Partition::new(elem.topic().to_string(), elem.partition());
            self.router.add_partition(partition);
        }
    }

    fn setup_revoked_partitions(&self, partitions: &TopicPartitionList) {
        self.inner.setup_revoked_partitions(partitions);
    }

    async fn cleanup_assigned_partitions(&self, partitions: &TopicPartitionList) -> Result<()> {
        self.inner.cleanup_assigned_partitions(partitions).await
    }

    async fn cleanup_revoked_partitions(&self, partitions: &TopicPartitionList) -> Result<()> {
        // Shutdown workers for revoked partitions
        let partitions_to_cleanup: Vec<_> = partitions
            .elements()
            .iter()
            .map(|elem| Partition::new(elem.topic().to_string(), elem.partition()))
            .collect();

        let workers = self.router.remove_partitions(&partitions_to_cleanup);
        shutdown_workers(workers).await;

        // Clear offset tracker state
        for partition in &partitions_to_cleanup {
            self.offset_tracker.clear_partition(partition);
        }

        self.inner.cleanup_revoked_partitions(partitions).await
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        self.offset_tracker.set_rebalancing(true);
        self.inner.on_pre_rebalance().await
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        self.offset_tracker.set_rebalancing(false);
        self.inner.on_post_rebalance().await
    }
}

/// A simple processor that counts processed messages
struct CountingProcessor {
    count: AtomicUsize,
}

impl CountingProcessor {
    fn new() -> Self {
        Self {
            count: AtomicUsize::new(0),
        }
    }

    fn get_count(&self) -> usize {
        self.count.load(Ordering::SeqCst)
    }
}

#[async_trait]
impl BatchConsumerProcessor<CapturedEvent> for CountingProcessor {
    async fn process_batch(&self, messages: Vec<KafkaMessage<CapturedEvent>>) -> Result<()> {
        self.count.fetch_add(messages.len(), Ordering::SeqCst);
        Ok(())
    }
}

/// Integration test that verifies offset commits work correctly with the routing processor.
///
/// This test:
/// 1. Creates a topic with 3 partitions and sends 100 messages to each
/// 2. Runs the batch consumer with routing processor and partition workers
/// 3. Waits for all messages to be processed
/// 4. Verifies the consumer group offsets are committed at the correct positions
#[tokio::test]
async fn test_offset_commits_with_routing_processor() -> Result<()> {
    let test_topic = format!("{}-offset-commit-{}", TEST_TOPIC_BASE, uuid::Uuid::now_v7());
    let group_id = format!("test-group-offset-commit-{}", uuid::Uuid::now_v7());
    let messages_per_partition = 100;
    let partitions_to_use = vec![0, 1, 2];
    let total_messages = messages_per_partition * partitions_to_use.len();

    // Step 1: Create topic with the required number of partitions
    create_topic_with_partitions(&test_topic, partitions_to_use.len() as i32).await?;

    // Step 2: Send messages to specific partitions
    for partition in &partitions_to_use {
        let messages = generate_test_messages(messages_per_partition);
        send_test_messages_to_partition(&test_topic, *partition, messages).await?;
    }

    // Step 3: Set up the consumer with routing processor
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000");

    let (shutdown_tx, shutdown_rx) = oneshot::channel();

    // Create the processor that counts messages
    let processor = Arc::new(CountingProcessor::new());

    // Create offset tracker
    let offset_tracker = Arc::new(OffsetTracker::new());

    // Create router with partition workers
    let router = Arc::new(PartitionRouter::new(
        processor.clone(),
        offset_tracker.clone(),
        PartitionRouterConfig::default(),
    ));

    // Create routing processor
    let routing_processor = Arc::new(RoutingProcessor::new(
        router.clone(),
        offset_tracker.clone(),
    ));

    // Create rebalance handler that manages workers
    let rebalance_handler = Arc::new(RoutingRebalanceHandler::new(
        router.clone(),
        offset_tracker.clone(),
    ));

    // Create the batch consumer
    let consumer = BatchConsumer::<CapturedEvent>::new(
        &config,
        rebalance_handler,
        routing_processor,
        offset_tracker.clone(),
        shutdown_rx,
        &test_topic,
        50, // batch size
        Duration::from_millis(100),
        Duration::from_millis(500), // commit interval - 500ms to ensure commits happen
    )?;

    // Step 4: Start consumption and wait for processing
    let processor_clone = processor.clone();
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // Wait for all messages to be processed
    let start = std::time::Instant::now();
    let timeout = Duration::from_secs(30);
    while processor_clone.get_count() < total_messages {
        if start.elapsed() > timeout {
            panic!(
                "Timeout waiting for messages. Got {} of {}",
                processor_clone.get_count(),
                total_messages
            );
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    // Wait a bit longer to ensure offset commits have happened
    // The commit interval is 500ms, so wait 1 second to be safe
    tokio::time::sleep(Duration::from_secs(1)).await;

    // Step 5: Verify offset_tracker's committed offsets BEFORE shutdown
    // (shutdown clears partition state, so we must check before that)
    for partition_num in &partitions_to_use {
        let partition = Partition::new(test_topic.clone(), *partition_num);
        let tracker_committed = offset_tracker.get_committed_offset(&partition);

        assert_eq!(
            tracker_committed,
            Some(messages_per_partition as i64),
            "Offset tracker should have committed offset {messages_per_partition} for partition {partition_num}, got {tracker_committed:?}"
        );
    }

    // Shutdown the consumer
    let _ = shutdown_tx.send(());
    let _ = consumer_handle.await;

    // Shutdown all workers
    let workers = router.shutdown_all();
    shutdown_workers(workers).await;

    // Step 6: Verify committed offsets using a new consumer
    let verification_consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .create()?;

    // Build topic partition list for the partitions we used
    let mut tpl = TopicPartitionList::new();
    for partition in &partitions_to_use {
        tpl.add_partition(&test_topic, *partition);
    }

    // Fetch committed offsets
    let committed = verification_consumer.committed_offsets(tpl, Duration::from_secs(5))?;

    // Verify each partition has the correct committed offset
    for partition in &partitions_to_use {
        let offset = committed
            .find_partition(&test_topic, *partition)
            .expect("Partition should exist in committed offsets");

        match offset.offset() {
            rdkafka::Offset::Offset(o) => {
                // The committed offset should be messages_per_partition (100)
                // because offset represents "next offset to consume"
                assert_eq!(
                    o, messages_per_partition as i64,
                    "Partition {partition} should have committed offset {messages_per_partition}, got {o}"
                );
            }
            other => {
                panic!("Partition {partition} should have a specific offset, got {other:?}");
            }
        }
    }

    // Verify total processed count
    assert_eq!(
        processor.get_count(),
        total_messages,
        "Should have processed all {total_messages} messages"
    );

    Ok(())
}
