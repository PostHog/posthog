use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3Client;
use chrono::Utc;

use kafka_deduplicator::checkpoint::{
    CheckpointConfig, CheckpointDownloader, CheckpointExporter, CheckpointImporter,
    CheckpointMetadata, CheckpointWorker, S3Downloader, S3Uploader,
};
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{
    DeduplicationStore, DeduplicationStoreConfig, TimestampKey, TimestampMetadata,
};

use common_types::RawEvent;

use anyhow::Result;
use tempfile::TempDir;
use tracing::info;

// MinIO configuration matching docker-compose.dev.yml
const MINIO_ENDPOINT: &str = "http://localhost:19000";
const MINIO_ACCESS_KEY: &str = "object_storage_root_user";
const MINIO_SECRET_KEY: &str = "object_storage_root_password";
const TEST_BUCKET: &str = "test-kafka-deduplicator-checkpoints";

fn create_test_checkpoint_config(tmp_checkpoint_dir: &TempDir) -> CheckpointConfig {
    CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: TEST_BUCKET.to_string(),
        s3_key_prefix: "checkpoints".to_string(),
        aws_region: "us-east-1".to_string(),
        test_s3_endpoint: Some(MINIO_ENDPOINT.to_string()),
        // Use a wide import window so our just-uploaded checkpoint is found
        checkpoint_import_window_hours: 24,
        ..Default::default()
    }
}

fn create_test_dedup_store(tmp_dir: &TempDir, topic: &str, partition: i32) -> DeduplicationStore {
    let config = DeduplicationStoreConfig {
        path: tmp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };

    DeduplicationStore::new(config, topic.to_string(), partition).unwrap()
}

fn create_test_raw_event(distinct_id: &str, token: &str, event_name: &str) -> RawEvent {
    RawEvent {
        uuid: None,
        event: event_name.to_string(),
        distinct_id: Some(serde_json::Value::String(distinct_id.to_string())),
        token: Some(token.to_string()),
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
    // Try to create bucket, ignore if it already exists
    let _ = client.create_bucket().bucket(TEST_BUCKET).send().await;
}

async fn cleanup_bucket(client: &AwsS3Client, prefix: &str) {
    // List and delete all objects with the given prefix
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

/// Integration test for checkpoint export and import via MinIO
#[tokio::test]
async fn test_checkpoint_export_import_via_minio() -> Result<()> {
    // Set up AWS credentials for MinIO
    std::env::set_var("AWS_ACCESS_KEY_ID", MINIO_ACCESS_KEY);
    std::env::set_var("AWS_SECRET_ACCESS_KEY", MINIO_SECRET_KEY);

    let test_topic = "test_checkpoint_integration";
    let test_partition = 0;

    // Create MinIO client and ensure bucket exists
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client).await;

    // Clean up any previous test data
    let test_prefix = format!("checkpoints/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, &test_prefix).await;

    // Create temp directories
    let tmp_store_dir = TempDir::new()?;
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_import_dir = TempDir::new()?;

    // Create dedup store and populate with test data
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
        create_test_raw_event("user3", "token1", "event3"),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata)?;
    }

    // Create checkpoint config
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    // Create S3Uploader for MinIO and wrap in exporter
    let uploader = S3Uploader::new_for_testing(config.clone()).await?;
    let exporter = Some(Arc::new(CheckpointExporter::new(Box::new(uploader))));

    // Create checkpoint worker and perform checkpoint
    let partition = Partition::new(test_topic.to_string(), test_partition);
    let attempt_timestamp = Utc::now();

    let worker = CheckpointWorker::new_for_testing(
        1,
        Path::new(&config.local_checkpoint_dir),
        &config.s3_key_prefix,
        partition.clone(),
        attempt_timestamp,
        exporter.clone(),
    );

    // Execute checkpoint - this creates local checkpoint and uploads to MinIO
    let checkpoint_result = worker.checkpoint_partition(&store, None).await?;
    assert!(
        checkpoint_result.is_some(),
        "Checkpoint should return CheckpointInfo"
    );
    let uploaded_info = checkpoint_result.unwrap();

    info!(
        remote_path = uploaded_info.get_remote_attempt_path(),
        file_count = uploaded_info.metadata.files.len(),
        "Uploaded checkpoint"
    );

    // Verify checkpoint was uploaded by listing objects
    let list_result = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&test_prefix)
        .send()
        .await?;

    let uploaded_keys: Vec<String> = list_result
        .contents()
        .iter()
        .filter_map(|obj| obj.key().map(String::from))
        .collect();

    info!(count = uploaded_keys.len(), "Found objects in MinIO");
    for key in &uploaded_keys {
        info!(key, "  - uploaded");
    }

    assert!(
        !uploaded_keys.is_empty(),
        "Should have uploaded files to MinIO"
    );
    assert!(
        uploaded_keys.iter().any(|k| k.ends_with("metadata.json")),
        "Should have uploaded metadata.json"
    );
    assert!(
        uploaded_keys.iter().any(|k| k.ends_with(".sst")),
        "Should have uploaded .sst files"
    );
    assert!(
        uploaded_keys.iter().any(|k| k.ends_with("CURRENT")),
        "Should have uploaded CURRENT file"
    );

    // Now test the import side - create S3Downloader and CheckpointImporter
    let downloader = S3Downloader::new_for_testing(&config).await?;

    // Test list_recent_checkpoints
    let recent_checkpoints = downloader
        .list_recent_checkpoints(test_topic, test_partition)
        .await?;

    info!(
        count = recent_checkpoints.len(),
        "Found recent checkpoint metadata files"
    );
    for cp in &recent_checkpoints {
        info!(checkpoint = cp, "  - found");
    }

    assert!(
        !recent_checkpoints.is_empty(),
        "Should find at least one checkpoint metadata file"
    );

    // Download and verify metadata
    let metadata_key = &recent_checkpoints[0];
    let metadata_bytes = downloader.download_file(metadata_key).await?;
    let downloaded_metadata = CheckpointMetadata::from_json_bytes(&metadata_bytes)?;

    info!(
        id = downloaded_metadata.id,
        topic = downloaded_metadata.topic,
        partition = downloaded_metadata.partition,
        sequence = downloaded_metadata.sequence,
        file_count = downloaded_metadata.files.len(),
        "Downloaded metadata"
    );

    // Verify metadata matches what we uploaded
    assert_eq!(downloaded_metadata.id, uploaded_info.metadata.id);
    assert_eq!(downloaded_metadata.topic, test_topic);
    assert_eq!(downloaded_metadata.partition, test_partition);
    assert_eq!(
        downloaded_metadata.files.len(),
        uploaded_info.metadata.files.len()
    );

    // Test full import via CheckpointImporter - downloads directly to store directory
    let importer = CheckpointImporter::new(
        Box::new(downloader),
        tmp_import_dir.path().to_path_buf(),
        config.checkpoint_import_attempt_depth,
    );
    assert!(
        importer.is_available().await,
        "Importer should be available"
    );

    let import_result = importer
        .import_checkpoint_for_topic_partition(test_topic, test_partition)
        .await?;

    info!(path = ?import_result, "Imported checkpoint");
    assert!(
        import_result.exists(),
        "Imported checkpoint directory should exist"
    );

    // Verify each file from metadata was imported
    let imported_files: Vec<_> = std::fs::read_dir(&import_result)?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();

    info!(
        imported = imported_files.len(),
        expected = downloaded_metadata.files.len(),
        "Verifying imported files match metadata"
    );

    for expected_file in &downloaded_metadata.files {
        let filename = expected_file
            .remote_filepath
            .rsplit('/')
            .next()
            .expect("remote_filepath should have filename");

        assert!(
            imported_files.contains(&filename.to_string()),
            "Expected file '{filename}' from metadata not found in imported files. Imported: {imported_files:?}",
        );
        info!(filename, "  - verified");
    }

    assert_eq!(
        imported_files.len(),
        downloaded_metadata.files.len(),
        "Imported file count should match metadata. Imported: {imported_files:?}, Expected: {:?}",
        downloaded_metadata
            .files
            .iter()
            .map(|f| f.remote_filepath.rsplit('/').next().unwrap())
            .collect::<Vec<_>>()
    );

    // Verify import result is within the store base directory
    assert!(
        import_result.starts_with(tmp_import_dir.path()),
        "Imported checkpoint should be within store base dir: {import_result:?} not in {:?}",
        tmp_import_dir.path()
    );

    // Verify store directory structure: <store_base>/<topic>_<partition>/<timestamp_millis>
    let expected_store_path = downloaded_metadata.get_store_path(tmp_import_dir.path());
    assert!(
        expected_store_path.exists(),
        "Store directory structure should exist: {expected_store_path:?}"
    );

    // Drop the original store to release RocksDB locks
    drop(store);

    // Open a new store from the imported checkpoint to verify it's a valid RocksDB
    info!(path = ?import_result, "Opening store from imported checkpoint");
    let restored_store_config = DeduplicationStoreConfig {
        // Checkpoint files are imported directly to the store directory
        path: import_result.clone(),
        max_capacity: 1_000_000,
    };
    let restored_store = DeduplicationStore::new(
        restored_store_config,
        test_topic.to_string(),
        test_partition,
    )?;

    // Verify we can read the data we originally stored
    info!("Verifying restored store contains original data");
    for event in &events {
        let key: TimestampKey = event.into();
        let record = restored_store.get_timestamp_record(&key)?;
        assert!(
            record.is_some(),
            "Restored store should contain record for event: {:?}",
            event.distinct_id
        );
        let metadata = record.unwrap();
        let stored_event = metadata.get_original_event().unwrap();
        assert_eq!(
            stored_event.distinct_id, event.distinct_id,
            "Restored event should match original"
        );
        assert_eq!(
            stored_event.event, event.event,
            "Restored event name should match original"
        );
        info!(distinct_id = ?event.distinct_id, "  - verified event");
    }
    info!(
        count = events.len(),
        "All events verified in restored store"
    );

    // Cleanup S3 bucket
    cleanup_bucket(&minio_client, &test_prefix).await;

    Ok(())
}
