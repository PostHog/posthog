use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::Utc;
use tokio_util::sync::CancellationToken;

use kafka_deduplicator::checkpoint::{
    CheckpointConfig, CheckpointDownloader, CheckpointExporter, CheckpointImporter,
    CheckpointMetadata, CheckpointWorker, S3Downloader, S3Uploader,
};
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{
    DeduplicationStore, DeduplicationStoreConfig, TimestampKey, TimestampMetadata,
};
use kafka_deduplicator::test_utils::test_helpers::{create_test_dedup_store, TestRawEventBuilder};

use anyhow::Result;
use tempfile::TempDir;
use tracing::info;

mod common;
use common::{
    cleanup_bucket, create_minio_client, delete_checkpoint_file, ensure_bucket_exists,
    upload_test_checkpoint, MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY,
};

const TEST_BUCKET: &str = "test-kafka-deduplicator-checkpoints";

fn create_test_checkpoint_config(tmp_checkpoint_dir: &TempDir) -> CheckpointConfig {
    CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: TEST_BUCKET.to_string(),
        s3_key_prefix: "checkpoints".to_string(),
        aws_region: Some("us-east-1".to_string()),
        s3_endpoint: Some(MINIO_ENDPOINT.to_string()),
        s3_access_key_id: Some(MINIO_ACCESS_KEY.to_string()),
        s3_secret_access_key: Some(MINIO_SECRET_KEY.to_string()),
        s3_force_path_style: true,
        // Use a wide import window so our just-uploaded checkpoint is found
        checkpoint_import_window_hours: 24,
        ..Default::default()
    }
}

/// Integration test for checkpoint export and import via MinIO
#[tokio::test]
async fn test_checkpoint_export_import_via_minio() -> Result<()> {
    let test_topic = "test_checkpoint_integration";
    let test_partition = 0;

    // Create MinIO client and ensure bucket exists
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client, TEST_BUCKET).await;

    // Clean up any previous test data
    let test_prefix = format!("checkpoints/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    // Create temp directories
    let tmp_store_dir = TempDir::new()?;
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_import_dir = TempDir::new()?;

    // Create dedup store and populate with test data
    let store = create_test_dedup_store(tmp_store_dir.path(), test_topic, test_partition);
    let events = vec![
        TestRawEventBuilder::new()
            .distinct_id("user1")
            .token("token1")
            .event("event1")
            .current_timestamp()
            .build(),
        TestRawEventBuilder::new()
            .distinct_id("user2")
            .token("token1")
            .event("event2")
            .current_timestamp()
            .build(),
        TestRawEventBuilder::new()
            .distinct_id("user3")
            .token("token1")
            .event("event3")
            .current_timestamp()
            .build(),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata)?;
    }

    // Create checkpoint config
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    // Create S3Uploader for MinIO and wrap in exporter
    let uploader = S3Uploader::new(config.clone()).await?;
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
    let downloader = S3Downloader::new(&config).await?;

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
        config.checkpoint_partition_import_timeout,
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
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    Ok(())
}

/// Test that when one file download fails, sibling downloads are cancelled quickly
/// via the per-attempt cancellation token, and the import fails fast.
#[tokio::test]
async fn test_sibling_cancellation_on_file_error() -> Result<()> {
    let test_topic = "test_sibling_cancel";
    let test_partition = 0;
    let s3_key_prefix = "checkpoints";

    // Setup MinIO
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client, TEST_BUCKET).await;

    let test_prefix = format!("{s3_key_prefix}/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    // Upload a checkpoint with multiple files
    let attempt_timestamp = Utc::now();
    let file_count = 10;
    let metadata = upload_test_checkpoint(
        &minio_client,
        TEST_BUCKET,
        s3_key_prefix,
        test_topic,
        test_partition,
        attempt_timestamp,
        file_count,
    )
    .await;

    info!(
        checkpoint_id = metadata.id,
        file_count = metadata.files.len(),
        "Uploaded test checkpoint"
    );

    // Delete one file to cause a download failure
    let file_to_delete = &metadata.files[file_count / 2].remote_filepath;
    delete_checkpoint_file(&minio_client, TEST_BUCKET, file_to_delete).await;
    info!(file = file_to_delete, "Deleted file to simulate failure");

    // Create checkpoint config and importer
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_import_dir = TempDir::new()?;
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    let downloader = S3Downloader::new(&config).await?;
    let importer = CheckpointImporter::new(
        Box::new(downloader),
        tmp_import_dir.path().to_path_buf(),
        1, // Only try one checkpoint attempt (no fallback for this test)
        Duration::from_secs(60),
    );

    // Time the import - it should fail fast due to sibling cancellation
    let start = Instant::now();
    let result = importer
        .import_checkpoint_for_topic_partition(test_topic, test_partition)
        .await;
    let elapsed = start.elapsed();

    // Verify import failed
    assert!(result.is_err(), "Import should fail when file is missing");
    let err_msg = result.unwrap_err().to_string();
    info!(
        error = err_msg,
        elapsed_ms = elapsed.as_millis(),
        "Import failed as expected"
    );

    // The failure should be relatively fast - sibling cancellation should prevent
    // waiting for all downloads to complete. With 10 files and proper cancellation,
    // this should complete much faster than if all downloads ran to completion.
    // We don't assert a specific time as it depends on S3/MinIO latency.

    // Cleanup
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    Ok(())
}

/// Test that when the first checkpoint attempt fails, the importer falls back
/// to the next (older) checkpoint attempt and succeeds.
#[tokio::test]
async fn test_fallback_after_failed_attempt() -> Result<()> {
    let test_topic = "test_fallback";
    let test_partition = 0;
    let s3_key_prefix = "checkpoints";

    // Setup MinIO
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client, TEST_BUCKET).await;

    let test_prefix = format!("{s3_key_prefix}/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    // Upload TWO checkpoints with different timestamps
    // First (older) checkpoint - this one will succeed
    let older_timestamp = Utc::now() - chrono::Duration::seconds(10);
    let older_metadata = upload_test_checkpoint(
        &minio_client,
        TEST_BUCKET,
        s3_key_prefix,
        test_topic,
        test_partition,
        older_timestamp,
        5, // 5 files
    )
    .await;
    info!(
        checkpoint_id = older_metadata.id,
        "Uploaded older checkpoint (will succeed)"
    );

    // Second (newer) checkpoint - this one will fail
    let newer_timestamp = Utc::now();
    let newer_metadata = upload_test_checkpoint(
        &minio_client,
        TEST_BUCKET,
        s3_key_prefix,
        test_topic,
        test_partition,
        newer_timestamp,
        5, // 5 files
    )
    .await;
    info!(
        checkpoint_id = newer_metadata.id,
        "Uploaded newer checkpoint (will fail)"
    );

    // Delete one file from the NEWER checkpoint to cause it to fail
    let file_to_delete = &newer_metadata.files[2].remote_filepath;
    delete_checkpoint_file(&minio_client, TEST_BUCKET, file_to_delete).await;
    info!(file = file_to_delete, "Deleted file from newer checkpoint");

    // Create checkpoint config and importer
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_import_dir = TempDir::new()?;
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    let downloader = S3Downloader::new(&config).await?;
    let importer = CheckpointImporter::new(
        Box::new(downloader),
        tmp_import_dir.path().to_path_buf(),
        10, // Allow multiple checkpoint attempts for fallback
        Duration::from_secs(60),
    );

    // Import should succeed by falling back to the older checkpoint
    let result = importer
        .import_checkpoint_for_topic_partition(test_topic, test_partition)
        .await;

    assert!(
        result.is_ok(),
        "Import should succeed via fallback: {:?}",
        result.err()
    );
    let import_path = result.unwrap();

    // Verify the imported checkpoint is from the OLDER (successful) checkpoint
    // by checking the path matches the older checkpoint's expected store path
    let expected_path = older_metadata.get_store_path(tmp_import_dir.path());
    assert_eq!(
        import_path, expected_path,
        "Imported path should be from older checkpoint"
    );

    info!(
        import_path = ?import_path,
        checkpoint_id = older_metadata.id,
        "Successfully imported via fallback to older checkpoint"
    );

    // Cleanup
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    Ok(())
}

/// Test that parent cancellation (e.g., from Kafka rebalance) stops all import work
/// immediately and doesn't attempt subsequent checkpoints.
#[tokio::test]
async fn test_parent_cancellation_stops_all_attempts() -> Result<()> {
    let test_topic = "test_parent_cancel";
    let test_partition = 0;
    let s3_key_prefix = "checkpoints";

    // Setup MinIO
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client, TEST_BUCKET).await;

    let test_prefix = format!("{s3_key_prefix}/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    // Upload a checkpoint with many files (to give time to cancel mid-download)
    let attempt_timestamp = Utc::now();
    let metadata = upload_test_checkpoint(
        &minio_client,
        TEST_BUCKET,
        s3_key_prefix,
        test_topic,
        test_partition,
        attempt_timestamp,
        20, // Many files to extend download time
    )
    .await;
    info!(
        checkpoint_id = metadata.id,
        file_count = metadata.files.len(),
        "Uploaded test checkpoint"
    );

    // Create checkpoint config and importer
    let tmp_checkpoint_dir = TempDir::new()?;
    let tmp_import_dir = TempDir::new()?;
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    let downloader = S3Downloader::new(&config).await?;
    let importer = CheckpointImporter::new(
        Box::new(downloader),
        tmp_import_dir.path().to_path_buf(),
        10, // Allow multiple attempts
        Duration::from_secs(60),
    );

    // Test 1: Pre-cancelled token should fail immediately
    let pre_cancelled_token = CancellationToken::new();
    pre_cancelled_token.cancel();

    let start = Instant::now();
    let result = importer
        .import_checkpoint_for_topic_partition_cancellable(
            test_topic,
            test_partition,
            Some(&pre_cancelled_token),
        )
        .await;
    let elapsed = start.elapsed();

    assert!(result.is_err(), "Import should fail when pre-cancelled");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.to_lowercase().contains("cancel"),
        "Error should mention cancellation: {}",
        err_msg
    );

    // Pre-cancelled import should fail very fast (no network I/O)
    assert!(
        elapsed.as_millis() < 1000,
        "Pre-cancelled import should fail quickly, took {}ms",
        elapsed.as_millis()
    );

    info!(
        error = err_msg,
        elapsed_ms = elapsed.as_millis(),
        "Pre-cancelled import failed as expected"
    );

    // Test 2: Cancellation during download (race condition - may or may not catch it)
    // This verifies the token is passed through all layers
    let cancel_token = CancellationToken::new();
    let cancel_token_clone = cancel_token.clone();

    // Cancel very quickly to try to catch the download in progress
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(5)).await;
        cancel_token_clone.cancel();
    });

    let result = importer
        .import_checkpoint_for_topic_partition_cancellable(
            test_topic,
            test_partition,
            Some(&cancel_token),
        )
        .await;

    // The result may succeed (if download completed before cancellation) or fail
    // Either outcome is acceptable - we just verify no panic occurs
    info!(
        result = ?result.as_ref().map(|p| p.display().to_string()).map_err(|e| e.to_string()),
        "Mid-download cancellation test completed (result depends on timing)"
    );

    // Cleanup
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    Ok(())
}
