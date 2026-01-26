//! End-to-end integration tests for Kafka rebalance handling with checkpoint import.
//!
//! These tests require both Kafka and MinIO to be running locally:
//! - Kafka on localhost:9092
//! - MinIO on localhost:19000
//!
//! Run with: `cargo test --test rebalance_e2e_integration_tests`
//!
//! These tests verify the complete flow:
//! 1. Partition assignment → pause → checkpoint import → resume → message processing
//! 2. Partition revocation → messages dropped for missing stores
//! 3. Overlapping rebalances → checkpoint import cancellation

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3Client;
use axum::async_trait;
use chrono::Utc;
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    client::DefaultClientContext,
    config::ClientConfig,
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
    Offset, TopicPartitionList,
};
use tempfile::TempDir;
use time::OffsetDateTime;
use tokio::sync::oneshot;
use tracing::info;
use uuid::Uuid;

use common_types::{CapturedEvent, RawEvent};
use kafka_deduplicator::checkpoint::{
    CheckpointConfig, CheckpointExporter, CheckpointImporter, CheckpointWorker, S3Downloader,
    S3Uploader,
};
use kafka_deduplicator::kafka::{
    batch_consumer::*, batch_message::*, offset_tracker::OffsetTracker,
    partition_router::PartitionRouter, partition_router::PartitionRouterConfig,
    rebalance_handler::RebalanceHandler, routing_processor::RoutingProcessor, types::Partition,
};
use kafka_deduplicator::processor_rebalance_handler::ProcessorRebalanceHandler;
use kafka_deduplicator::store::{DeduplicationStore, DeduplicationStoreConfig};
use kafka_deduplicator::store_manager::StoreManager;

// Infrastructure configuration matching docker-compose.dev.yml
const KAFKA_BROKERS: &str = "localhost:9092";
const MINIO_ENDPOINT: &str = "http://localhost:19000";
const MINIO_ACCESS_KEY: &str = "object_storage_root_user";
const MINIO_SECRET_KEY: &str = "object_storage_root_password";
const TEST_BUCKET: &str = "test-kafka-deduplicator-e2e";

const TEST_TOPIC_BASE: &str = "kdedup-e2e-rebalance-test";

// ============================================================================
// Helper Functions
// ============================================================================

async fn create_minio_client() -> AwsS3Client {
    let config = aws_config::defaults(BehaviorVersion::latest())
        .endpoint_url(MINIO_ENDPOINT)
        .region(Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::new(
            MINIO_ACCESS_KEY,
            MINIO_SECRET_KEY,
            None,
            None,
            "test",
        ))
        .load()
        .await;

    let s3_config = aws_sdk_s3::config::Builder::from(&config)
        .force_path_style(true)
        .build();

    AwsS3Client::from_conf(s3_config)
}

async fn ensure_bucket_exists(client: &AwsS3Client) {
    let _ = client.create_bucket().bucket(TEST_BUCKET).send().await;
}

async fn cleanup_bucket(client: &AwsS3Client, prefix: &str) {
    let list_result = client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(prefix)
        .send()
        .await;

    if let Ok(response) = list_result {
        for object in response.contents() {
            if let Some(key) = object.key() {
                let _ = client
                    .delete_object()
                    .bucket(TEST_BUCKET)
                    .key(key)
                    .send()
                    .await;
            }
        }
    }
}

async fn create_topic_with_partitions(topic: &str, num_partitions: i32) -> Result<()> {
    let admin_client: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topic = NewTopic::new(topic, num_partitions, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(5)));

    let results = admin_client.create_topics(&[new_topic], &opts).await?;

    for result in results {
        match result {
            Ok(_) => {}
            Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((topic_name, err)) => {
                return Err(anyhow::anyhow!(
                    "Failed to create topic {topic_name}: {err:?}"
                ));
            }
        }
    }

    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(())
}

fn create_checkpoint_config(tmp_dir: &TempDir, topic: &str) -> CheckpointConfig {
    CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_dir.path().to_string_lossy().to_string(),
        s3_bucket: TEST_BUCKET.to_string(),
        s3_key_prefix: format!("checkpoints/{topic}"),
        aws_region: Some("us-east-1".to_string()),
        s3_endpoint: Some(MINIO_ENDPOINT.to_string()),
        s3_access_key_id: Some(MINIO_ACCESS_KEY.to_string()),
        s3_secret_access_key: Some(MINIO_SECRET_KEY.to_string()),
        s3_force_path_style: true,
        checkpoint_import_window_hours: 24,
        ..Default::default()
    }
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

    CapturedEvent {
        uuid: event_uuid,
        distinct_id: distinct_id.to_string(),
        session_id: None,
        ip: "127.0.0.1".to_string(),
        now: now_rfc3339.clone(),
        token: token.to_string(),
        data: data.to_string(),
        sent_at: Some(now_offset_datetime),
        event: event_name.to_string(),
        timestamp: chrono::Utc::now(),
        is_cookieless_mode: false,
        historical_migration: false,
    }
}

fn create_test_raw_event(distinct_id: &str, event_name: &str) -> RawEvent {
    RawEvent {
        uuid: Some(Uuid::now_v7()),
        event: event_name.to_string(),
        distinct_id: Some(serde_json::json!(distinct_id)),
        token: Some("test_token".to_string()),
        properties: std::collections::HashMap::new(),
        timestamp: Some(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs()
                .to_string(),
        ),
        ..Default::default()
    }
}

async fn send_test_messages(topic: &str, partition: i32, count: usize) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for i in 0..count {
        let payload = create_captured_event();
        let serialized = serde_json::to_string(&payload)?;
        let key = format!("key_{i}");

        let record = FutureRecord::to(topic)
            .key(&key)
            .payload(&serialized)
            .partition(partition);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;
    }

    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

// ============================================================================
// Test Processor
// ============================================================================

/// A processor that counts processed messages
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

// ============================================================================
// Integration Tests
// ============================================================================

/// Test: Full rebalance flow with checkpoint import from MinIO
///
/// This test verifies the complete flow:
/// 1. Create a checkpoint with test data and upload to MinIO
/// 2. Start a consumer that will be assigned the partition
/// 3. Verify checkpoint is imported during rebalance
/// 4. Verify messages are processed after resume
#[tokio::test]
async fn test_rebalance_with_checkpoint_import() -> Result<()> {
    let test_id = Uuid::now_v7();
    let test_topic = format!("{}-checkpoint-{}", TEST_TOPIC_BASE, test_id);
    let test_partition = 0;
    let group_id = format!("test-group-checkpoint-{}", test_id);

    info!("Starting test_rebalance_with_checkpoint_import");
    info!("Topic: {}, Group: {}", test_topic, group_id);

    // Setup MinIO
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client).await;

    let checkpoint_prefix = format!("checkpoints/{}", test_topic);
    cleanup_bucket(&minio_client, &checkpoint_prefix).await;

    // Create temp directories
    let tmp_store_dir = TempDir::new()?;
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_consumer_store_dir = TempDir::new()?;

    // Step 1: Create a checkpoint with test data
    info!("Step 1: Creating checkpoint with test data");

    let store_config = DeduplicationStoreConfig {
        path: tmp_store_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };
    let store = DeduplicationStore::new(store_config, test_topic.clone(), test_partition)?;

    // Add some test records to the store
    use kafka_deduplicator::store::{TimestampKey, TimestampMetadata};
    let test_events: Vec<RawEvent> = (0..5)
        .map(|i| create_test_raw_event(&format!("user_{i}"), &format!("event_{i}")))
        .collect();

    for event in &test_events {
        let key: TimestampKey = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata)?;
    }

    info!("Added {} test records to store", test_events.len());

    // Step 2: Upload checkpoint to MinIO
    info!("Step 2: Uploading checkpoint to MinIO");

    let checkpoint_config = create_checkpoint_config(&tmp_checkpoint_dir, &test_topic);
    let uploader = S3Uploader::new(checkpoint_config.clone()).await?;
    let exporter = Some(Arc::new(CheckpointExporter::new(Box::new(uploader))));

    let partition = Partition::new(test_topic.clone(), test_partition);
    let worker = CheckpointWorker::new_for_testing(
        1,
        std::path::Path::new(&checkpoint_config.local_checkpoint_dir),
        &checkpoint_config.s3_key_prefix,
        partition.clone(),
        Utc::now(),
        exporter.clone(),
    );

    let checkpoint_result = worker.checkpoint_partition(&store, None).await?;
    assert!(
        checkpoint_result.is_some(),
        "Checkpoint should be created and uploaded"
    );

    info!(
        "Checkpoint uploaded: {}",
        checkpoint_result.unwrap().get_remote_attempt_path()
    );

    // Drop the original store to release locks
    drop(store);

    // Step 3: Create Kafka topic and send messages
    info!("Step 3: Creating topic and sending messages");

    create_topic_with_partitions(&test_topic, 1).await?;
    let messages_to_send = 10;
    send_test_messages(&test_topic, test_partition, messages_to_send).await?;

    info!("Sent {} messages to topic", messages_to_send);

    // Step 4: Create consumer with checkpoint import enabled
    info!("Step 4: Starting consumer with checkpoint import");

    let consumer_store_config = DeduplicationStoreConfig {
        path: tmp_consumer_store_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };
    let store_manager = Arc::new(StoreManager::new(consumer_store_config));
    let offset_tracker = Arc::new(OffsetTracker::new());
    let processor = Arc::new(CountingProcessor::new());

    // Create checkpoint importer
    let import_config = create_checkpoint_config(&tmp_consumer_store_dir, &test_topic);
    let downloader = S3Downloader::new(&import_config).await?;
    let importer = Arc::new(CheckpointImporter::new(
        Box::new(downloader),
        tmp_consumer_store_dir.path().to_path_buf(),
        import_config.checkpoint_import_attempt_depth,
    ));

    // Create router and rebalance handler with checkpoint import
    let router = Arc::new(PartitionRouter::new(
        processor.clone(),
        offset_tracker.clone(),
        PartitionRouterConfig::default(),
    ));

    let rebalance_handler: Arc<ProcessorRebalanceHandler<CapturedEvent, CountingProcessor>> =
        Arc::new(ProcessorRebalanceHandler::with_router(
            store_manager.clone(),
            router.clone(),
            offset_tracker.clone(),
            Some(importer),
        ));

    // Create routing processor
    let routing_processor = Arc::new(RoutingProcessor::new(
        router.clone(),
        offset_tracker.clone(),
    ));

    // Create consumer config
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000");

    let (shutdown_tx, shutdown_rx) = oneshot::channel();

    let consumer = BatchConsumer::<CapturedEvent>::new(
        &config,
        rebalance_handler,
        routing_processor,
        offset_tracker.clone(),
        shutdown_rx,
        &test_topic,
        50,
        Duration::from_millis(100),
        Duration::from_millis(500),
    )?;

    // Start consumer in background
    let processor_clone = processor.clone();
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // Step 5: Wait for messages to be processed
    info!("Step 5: Waiting for messages to be processed");

    let start = std::time::Instant::now();
    let timeout = Duration::from_secs(30);

    while processor_clone.get_count() < messages_to_send {
        if start.elapsed() > timeout {
            panic!(
                "Timeout waiting for messages. Got {} of {}",
                processor_clone.get_count(),
                messages_to_send
            );
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    info!(
        "Processed {} messages in {:?}",
        processor_clone.get_count(),
        start.elapsed()
    );

    // Step 6: Verify checkpoint was imported (store should have pre-existing records)
    info!("Step 6: Verifying checkpoint import");

    let imported_store = store_manager.get(&test_topic, test_partition);
    assert!(
        imported_store.is_some(),
        "Store should exist after rebalance"
    );

    // The store should contain the records from the checkpoint
    let store = imported_store.unwrap();
    for event in &test_events {
        let key: TimestampKey = event.into();
        let record = store.get_timestamp_record(&key)?;
        assert!(
            record.is_some(),
            "Checkpoint record for {} should exist in imported store",
            event.event
        );
    }

    info!(
        "Checkpoint import verified - all {} records present",
        test_events.len()
    );

    // Cleanup
    let _ = shutdown_tx.send(());
    let _ = consumer_handle.await;
    cleanup_bucket(&minio_client, &checkpoint_prefix).await;

    info!("Test completed successfully");
    Ok(())
}

/// Test: Messages for revoked partitions are dropped
///
/// This test verifies that after a partition is revoked:
/// 1. The store is removed from the store manager
/// 2. Any messages that arrive for that partition are dropped (not processed)
#[tokio::test]
async fn test_messages_dropped_for_revoked_partition() -> Result<()> {
    let test_id = Uuid::now_v7();
    let test_topic = format!("{}-revoked-{}", TEST_TOPIC_BASE, test_id);

    info!("Starting test_messages_dropped_for_revoked_partition");

    // Create temp directory
    let tmp_store_dir = TempDir::new()?;

    // Create store manager and add a store
    let store_config = DeduplicationStoreConfig {
        path: tmp_store_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };
    let store_manager = Arc::new(StoreManager::new(store_config));
    let offset_tracker = Arc::new(OffsetTracker::new());

    // Create the ProcessorRebalanceHandler
    let handler: ProcessorRebalanceHandler<CapturedEvent, CountingProcessor> =
        ProcessorRebalanceHandler::new(store_manager.clone(), offset_tracker.clone(), None);

    // Assign partition 0
    let mut partitions = TopicPartitionList::new();
    partitions.add_partition_offset(&test_topic, 0, Offset::Beginning)?;

    // Sync setup (creates workers if router exists, marks as assigned)
    handler.setup_assigned_partitions(&partitions);

    // Create command channel for async setup
    let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

    // Async setup (creates stores, sends resume)
    handler
        .async_setup_assigned_partitions(&partitions, &tx)
        .await?;

    // Verify store exists
    assert!(
        store_manager.get(&test_topic, 0).is_some(),
        "Store should exist after assignment"
    );

    info!("Partition 0 assigned, store created");

    // Now revoke the partition
    handler.setup_revoked_partitions(&partitions);

    // Verify store is removed from map (sync step)
    assert!(
        store_manager.get(&test_topic, 0).is_none(),
        "Store should be removed after revocation"
    );

    info!("Partition 0 revoked, store removed");

    // Verify get_store returns error (this is what deduplicate_batch would call)
    let result = store_manager.get_store(&test_topic, 0);
    assert!(
        result.is_err(),
        "get_store should return error for revoked partition"
    );

    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.contains("No store registered"),
        "Error should indicate no store registered"
    );

    info!("Verified: messages for revoked partition would be dropped");

    // Cleanup async
    handler.cleanup_revoked_partitions(&partitions).await?;

    info!("Test completed successfully");
    Ok(())
}

/// Test: Rapid revoke-assign doesn't lose the new store
///
/// This test verifies that when a partition is rapidly revoked and re-assigned:
/// 1. The cleanup for the old assignment doesn't affect the new assignment
/// 2. The new store is properly created and available
#[tokio::test]
async fn test_rapid_revoke_assign_preserves_new_store() -> Result<()> {
    let test_id = Uuid::now_v7();
    let test_topic = format!("{}-rapid-{}", TEST_TOPIC_BASE, test_id);

    info!("Starting test_rapid_revoke_assign_preserves_new_store");

    // Create temp directory
    let tmp_store_dir = TempDir::new()?;

    // Create store manager
    let store_config = DeduplicationStoreConfig {
        path: tmp_store_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };
    let store_manager = Arc::new(StoreManager::new(store_config));
    let offset_tracker = Arc::new(OffsetTracker::new());

    let handler: ProcessorRebalanceHandler<CapturedEvent, CountingProcessor> =
        ProcessorRebalanceHandler::new(store_manager.clone(), offset_tracker.clone(), None);

    let mut partitions = TopicPartitionList::new();
    partitions.add_partition_offset(&test_topic, 0, Offset::Beginning)?;

    // Step 1: Initial assignment
    info!("Step 1: Initial assignment");
    handler.setup_assigned_partitions(&partitions);

    let (tx1, _rx1) = tokio::sync::mpsc::unbounded_channel();
    handler
        .async_setup_assigned_partitions(&partitions, &tx1)
        .await?;

    assert!(
        store_manager.get(&test_topic, 0).is_some(),
        "Store should exist after initial assignment"
    );

    // Step 2: Revoke (sync only - don't run async cleanup yet)
    info!("Step 2: Revoke (sync only)");
    handler.setup_revoked_partitions(&partitions);

    assert!(
        store_manager.get(&test_topic, 0).is_none(),
        "Store should be removed after revoke"
    );

    // Step 3: Immediate re-assignment (before async cleanup)
    info!("Step 3: Immediate re-assignment");
    handler.setup_assigned_partitions(&partitions);

    let (tx2, mut rx2) = tokio::sync::mpsc::unbounded_channel();
    handler
        .async_setup_assigned_partitions(&partitions, &tx2)
        .await?;

    // Step 4: Now run the stale cleanup from Step 2
    info!("Step 4: Run stale cleanup (should be no-op for re-assigned partition)");
    handler.cleanup_revoked_partitions(&partitions).await?;

    // Step 5: Verify store still exists (cleanup didn't remove it)
    info!("Step 5: Verify store still exists");
    assert!(
        store_manager.get(&test_topic, 0).is_some(),
        "Store should still exist after stale cleanup"
    );

    // Verify Resume was sent
    let command = rx2.try_recv();
    assert!(
        command.is_ok(),
        "Resume command should have been sent for re-assigned partition"
    );

    info!("Test completed successfully");
    Ok(())
}
