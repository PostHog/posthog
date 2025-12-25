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

// MinIO configuration matching docker-compose.dev.yml
const MINIO_ENDPOINT: &str = "http://localhost:19000";
const MINIO_ACCESS_KEY: &str = "object_storage_root_user";
const MINIO_SECRET_KEY: &str = "object_storage_root_password";
const TEST_BUCKET: &str = "test-kafka-deduplicator-checkpoints";

fn create_test_checkpoint_config(
    tmp_checkpoint_dir: &TempDir,
    tmp_import_dir: &TempDir,
) -> CheckpointConfig {
    CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        local_checkpoint_import_dir: tmp_import_dir.path().to_string_lossy().to_string(),
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
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir, &tmp_import_dir);

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

    println!(
        "Uploaded checkpoint to: {}",
        uploaded_info.get_remote_attempt_path()
    );
    println!(
        "Checkpoint metadata has {} files",
        uploaded_info.metadata.files.len()
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

    println!("Found {} objects in MinIO:", uploaded_keys.len());
    for key in &uploaded_keys {
        println!("  - {key}");
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

    // Verify local checkpoint export directory has files (test_mode=true skips cleanup)
    let local_checkpoint_path = tmp_checkpoint_dir
        .path()
        .join(test_topic)
        .join(test_partition.to_string());
    assert!(
        local_checkpoint_path.exists(),
        "Local checkpoint directory should exist after export: {local_checkpoint_path:?}"
    );
    let local_export_files: Vec<_> = std::fs::read_dir(&local_checkpoint_path)?
        .filter_map(|e| e.ok())
        .flat_map(|e| std::fs::read_dir(e.path()).ok())
        .flatten()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    println!(
        "Local export directory has {} files:",
        local_export_files.len()
    );
    for f in &local_export_files {
        println!("  - {f}");
    }
    assert!(
        !local_export_files.is_empty(),
        "Local export directory should have checkpoint files"
    );

    // Now test the import side - create S3Downloader and CheckpointImporter
    let downloader = S3Downloader::new_for_testing(&config).await?;

    // Test list_recent_checkpoints
    let recent_checkpoints = downloader
        .list_recent_checkpoints(test_topic, test_partition)
        .await?;

    println!(
        "Found {} recent checkpoint metadata files",
        recent_checkpoints.len()
    );
    for cp in &recent_checkpoints {
        println!("  - {cp}");
    }

    assert!(
        !recent_checkpoints.is_empty(),
        "Should find at least one checkpoint metadata file"
    );

    // Download and verify metadata
    let metadata_key = &recent_checkpoints[0];
    let metadata_bytes = downloader.download_file(metadata_key).await?;
    let downloaded_metadata = CheckpointMetadata::from_json_bytes(&metadata_bytes)?;

    println!("Downloaded metadata:");
    println!("  - id: {}", downloaded_metadata.id);
    println!("  - topic: {}", downloaded_metadata.topic);
    println!("  - partition: {}", downloaded_metadata.partition);
    println!("  - sequence: {}", downloaded_metadata.sequence);
    println!("  - files: {}", downloaded_metadata.files.len());

    // Verify metadata matches what we uploaded
    assert_eq!(downloaded_metadata.id, uploaded_info.metadata.id);
    assert_eq!(downloaded_metadata.topic, test_topic);
    assert_eq!(downloaded_metadata.partition, test_partition);
    assert_eq!(
        downloaded_metadata.files.len(),
        uploaded_info.metadata.files.len()
    );

    // Test full import via CheckpointImporter
    let importer = CheckpointImporter::new(Box::new(downloader), &config);
    assert!(
        importer.is_available().await,
        "Importer should be available"
    );

    let import_result = importer
        .import_checkpoint_for_topic_partition(test_topic, test_partition)
        .await?;

    println!("Imported checkpoint to: {import_result:?}");
    assert!(
        import_result.exists(),
        "Imported checkpoint directory should exist"
    );

    // Verify imported files
    let imported_files: Vec<_> = std::fs::read_dir(&import_result)?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();

    println!("Imported {} files:", imported_files.len());
    for f in &imported_files {
        println!("  - {f}");
    }

    assert!(
        imported_files.iter().any(|f| f.ends_with(".sst")),
        "Should have imported .sst files"
    );
    assert!(
        imported_files.iter().any(|f| f == "CURRENT"),
        "Should have imported CURRENT file"
    );
    assert!(
        imported_files.iter().any(|f| f.starts_with("MANIFEST-")),
        "Should have imported MANIFEST file"
    );
    assert!(
        imported_files.iter().any(|f| f.starts_with("OPTIONS-")),
        "Should have imported OPTIONS file"
    );

    // Verify file count matches metadata
    assert_eq!(
        imported_files.len(),
        downloaded_metadata.files.len(),
        "Imported file count should match metadata file count"
    );

    // Verify import result is within the configured import directory
    assert!(
        import_result.starts_with(tmp_import_dir.path()),
        "Imported checkpoint should be within tmp_import_dir: {:?} not in {:?}",
        import_result,
        tmp_import_dir.path()
    );

    // Verify import directory structure: <import_dir>/<topic>/<partition>/<checkpoint_id>/
    let expected_import_parent = tmp_import_dir
        .path()
        .join(test_topic)
        .join(test_partition.to_string());
    assert!(
        expected_import_parent.exists(),
        "Import directory structure should exist: {expected_import_parent:?}"
    );

    // Drop the original store to release RocksDB locks
    drop(store);

    // Open a new store from the imported checkpoint to verify it's a valid RocksDB
    println!("Opening store from imported checkpoint: {import_result:?}");
    let restored_store_config = DeduplicationStoreConfig {
        path: import_result.clone(),
        max_capacity: 1_000_000,
    };
    let restored_store =
        DeduplicationStore::new(restored_store_config, test_topic.to_string(), test_partition)?;

    // Verify we can read the data we originally stored
    println!("Verifying restored store contains original data...");
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
        println!(
            "  - Verified event for distinct_id: {:?}",
            event.distinct_id
        );
    }
    println!("All {} events verified in restored store!", events.len());

    // Cleanup S3 bucket
    cleanup_bucket(&minio_client, &test_prefix).await;

    // Note: TempDirs (tmp_store_dir, tmp_checkpoint_dir, tmp_import_dir) are
    // automatically cleaned up when dropped at end of test

    Ok(())
}
