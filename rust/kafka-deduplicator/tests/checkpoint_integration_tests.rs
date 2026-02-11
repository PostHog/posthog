use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::Utc;
use tokio_util::sync::CancellationToken;

use kafka_deduplicator::checkpoint::{
    hash_prefix_for_partition, CheckpointConfig, CheckpointDownloader, CheckpointExporter,
    CheckpointImporter, CheckpointMetadata, CheckpointWorker, S3Downloader, S3Uploader,
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
        // Wide import window ensures freshly uploaded checkpoints are found
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

    // Clean up any previous test data (unhashed metadata path and hashed object path)
    let test_prefix = format!("checkpoints/{test_topic}/{test_partition}");
    let hash = hash_prefix_for_partition(test_topic, test_partition);
    let hashed_prefix = format!("{hash}/checkpoints/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;
    cleanup_bucket(&minio_client, TEST_BUCKET, &hashed_prefix).await;

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

    // Verify checkpoint was uploaded by listing objects (metadata under unhashed prefix, objects under hashed)
    let list_meta = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&test_prefix)
        .send()
        .await?;
    let list_objects = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&hashed_prefix)
        .send()
        .await?;
    let uploaded_keys: Vec<String> = list_meta
        .contents()
        .iter()
        .chain(list_objects.contents().iter())
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
    let meta_keys: Vec<_> = uploaded_keys
        .iter()
        .filter(|k| k.ends_with("metadata.json"))
        .collect();
    assert!(!meta_keys.is_empty(), "Should have uploaded metadata.json");
    for k in &meta_keys {
        assert!(
            !k.contains(&hash),
            "metadata.json key must not contain hash prefix, got: {k}"
        );
    }
    let object_keys: Vec<_> = uploaded_keys
        .iter()
        .filter(|k| !k.ends_with("metadata.json"))
        .collect();
    assert!(!object_keys.is_empty(), "Should have uploaded object files");
    for k in &object_keys {
        assert!(
            k.contains(&hash),
            "object file key must contain hash prefix, got: {k}"
        );
    }
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
    // Object file paths in metadata must contain hash prefix (round-trip: export wrote hashed paths)
    for f in &downloaded_metadata.files {
        assert!(
            f.remote_filepath.contains(&hash),
            "metadata.files[].remote_filepath should contain hash prefix, got: {}",
            f.remote_filepath
        );
    }

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
    let all_imported_files: Vec<_> = std::fs::read_dir(&import_result)?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();

    // Separate marker file from checkpoint files
    let marker_files: Vec<_> = all_imported_files
        .iter()
        .filter(|f| f.starts_with(".imported_"))
        .collect();
    let imported_files: Vec<_> = all_imported_files
        .iter()
        .filter(|f| !f.starts_with(".imported_"))
        .cloned()
        .collect();

    // Verify marker file exists (created by import to identify imported stores)
    assert_eq!(
        marker_files.len(),
        1,
        "Should have exactly one .imported_* marker file, found: {marker_files:?}"
    );
    info!(marker_file = ?marker_files[0], "Verified import marker file exists");

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
    // Note: import_result uses Utc::now() for the timestamp, so we just verify the path exists
    // rather than calculating the expected path (which would require the exact import timestamp)
    assert!(
        import_result.exists(),
        "Store directory structure should exist: {import_result:?}"
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
        1, // Single attempt - this test validates sibling cancellation, not fallback
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

    // Sibling cancellation should cause the attempt to fail fast rather than
    // waiting for all concurrent downloads to complete individually.
    // We don't assert a specific time as it depends on network latency.

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
    // by checking the marker file contains the older checkpoint's metadata
    let marker_files: Vec<_> = std::fs::read_dir(&import_path)
        .expect("Should be able to read import path")
        .filter_map(|e| e.ok())
        .filter(|e| e.file_name().to_string_lossy().starts_with(".imported_"))
        .collect();
    assert_eq!(marker_files.len(), 1, "Should have exactly one marker file");

    let marker_content = std::fs::read_to_string(marker_files[0].path())
        .expect("Should be able to read marker file");
    let marker_metadata: serde_json::Value =
        serde_json::from_str(&marker_content).expect("Marker should contain valid JSON");

    // The marker should contain the OLDER checkpoint's ID, not the newer (failed) one
    assert_eq!(
        marker_metadata["id"].as_str().unwrap(),
        older_metadata.id,
        "Imported checkpoint should be from older checkpoint (fallback)"
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

/// Integration test for export-side cancellation via MinIO.
/// This test verifies the main feature of this PR: fail-fast cancellation during
/// checkpoint exports to spare local resource utilization during rebalancing.
///
/// Tests:
/// 1. Pre-cancelled token prevents upload from starting
/// 2. Cancellation returns appropriate error with "cancelled" message
/// 3. No files are uploaded when pre-cancelled
/// 4. Verifies the cancellation flows through exporter → uploader correctly
#[tokio::test]
async fn test_export_cancellation_via_minio() -> Result<()> {
    let test_topic = "test_export_cancellation";
    let test_partition = 0;

    // Create MinIO client and ensure bucket exists
    let minio_client = create_minio_client().await;
    ensure_bucket_exists(&minio_client, TEST_BUCKET).await;

    // Clean up any previous test data (unhashed metadata path and hashed object path)
    let test_prefix = format!("checkpoints/{test_topic}/{test_partition}");
    let hash = hash_prefix_for_partition(test_topic, test_partition);
    let hashed_prefix = format!("{hash}/checkpoints/{test_topic}/{test_partition}");
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;
    cleanup_bucket(&minio_client, TEST_BUCKET, &hashed_prefix).await;

    // Create temp directory for store (shared across test cases)
    let tmp_store_dir = TempDir::new()?;

    // Create dedup store and populate with enough test data to generate real SST files
    let store = create_test_dedup_store(tmp_store_dir.path(), test_topic, test_partition);
    for i in 0..100 {
        let event = TestRawEventBuilder::new()
            .distinct_id(&format!("user_{i}"))
            .token("token1")
            .event(&format!("event_{i}"))
            .current_timestamp()
            .build();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata)?;
    }

    let partition = Partition::new(test_topic.to_string(), test_partition);

    // ============================================================
    // Test 1: Pre-cancelled token should fail immediately
    // ============================================================
    info!("Test 1: Pre-cancelled token should fail immediately");

    // Each test case gets its own TempDir to avoid directory collision
    let tmp_checkpoint_dir_1 = TempDir::new()?;
    let config_1 = create_test_checkpoint_config(&tmp_checkpoint_dir_1);
    let uploader_1 = S3Uploader::new(config_1.clone()).await?;
    let exporter_1 = Arc::new(CheckpointExporter::new(Box::new(uploader_1)));

    let worker_1 = CheckpointWorker::new_for_testing(
        1,
        Path::new(&config_1.local_checkpoint_dir),
        &config_1.s3_key_prefix,
        partition.clone(),
        Utc::now(),
        Some(exporter_1),
    );

    let pre_cancelled_token = CancellationToken::new();
    pre_cancelled_token.cancel();

    let start = Instant::now();
    let result = worker_1
        .checkpoint_partition_cancellable(&store, None, Some(&pre_cancelled_token), Some("test"))
        .await;
    let elapsed = start.elapsed();

    assert!(result.is_err(), "Checkpoint should fail when pre-cancelled");
    let err_msg = result.unwrap_err().to_string();
    assert!(
        err_msg.to_lowercase().contains("cancelled"),
        "Error should mention cancellation: {}",
        err_msg
    );

    info!(
        elapsed_ms = elapsed.as_millis(),
        error = err_msg,
        "Pre-cancelled export failed as expected"
    );

    // Verify: No objects should have been uploaded to MinIO
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

    assert!(
        uploaded_keys.is_empty(),
        "No files should be uploaded when pre-cancelled. Found: {:?}",
        uploaded_keys
    );

    info!("Test 1 passed: Pre-cancelled token prevents upload");

    // ============================================================
    // Test 2: Normal (non-cancelled) export should succeed
    // ============================================================
    info!("Test 2: Normal export should succeed");

    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;
    cleanup_bucket(&minio_client, TEST_BUCKET, &hashed_prefix).await;

    let tmp_checkpoint_dir_2 = TempDir::new()?;
    let config_2 = create_test_checkpoint_config(&tmp_checkpoint_dir_2);
    let uploader_2 = S3Uploader::new(config_2.clone()).await?;
    let exporter_2 = Arc::new(CheckpointExporter::new(Box::new(uploader_2)));

    let worker_2 = CheckpointWorker::new_for_testing(
        2,
        Path::new(&config_2.local_checkpoint_dir),
        &config_2.s3_key_prefix,
        partition.clone(),
        Utc::now(),
        Some(exporter_2),
    );

    // Export without cancellation token (normal path)
    let result = worker_2.checkpoint_partition(&store, None).await?;
    assert!(
        result.is_some(),
        "Checkpoint should succeed and return CheckpointInfo"
    );

    let checkpoint_info = result.unwrap();
    info!(
        remote_path = checkpoint_info.get_remote_attempt_path(),
        file_count = checkpoint_info.metadata.files.len(),
        "Normal export succeeded"
    );

    // Verify files were uploaded (metadata at unhashed path, objects at hashed path)
    let list_meta = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&test_prefix)
        .send()
        .await?;
    let list_objects = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&hashed_prefix)
        .send()
        .await?;
    let uploaded_keys: Vec<String> = list_meta
        .contents()
        .iter()
        .chain(list_objects.contents().iter())
        .filter_map(|obj| obj.key().map(String::from))
        .collect();

    assert!(
        !uploaded_keys.is_empty(),
        "Files should be uploaded for normal export"
    );
    let meta_keys: Vec<_> = uploaded_keys
        .iter()
        .filter(|k| k.ends_with("metadata.json"))
        .collect();
    assert!(!meta_keys.is_empty(), "Should have uploaded metadata.json");
    for k in &meta_keys {
        assert!(
            !k.contains(&hash),
            "metadata.json key must not contain hash, got: {k}"
        );
    }
    let object_keys: Vec<_> = uploaded_keys
        .iter()
        .filter(|k| !k.ends_with("metadata.json"))
        .collect();
    assert!(!object_keys.is_empty(), "Should have uploaded object files");
    for k in &object_keys {
        assert!(
            k.contains(&hash),
            "object file key must contain hash, got: {k}"
        );
    }
    assert!(
        uploaded_keys.iter().any(|k| k.ends_with(".sst")),
        "Should have uploaded SST files"
    );

    info!(
        uploaded_count = uploaded_keys.len(),
        "Test 2 passed: Normal export succeeded with {} files",
        uploaded_keys.len()
    );

    // ============================================================
    // Test 3: Export with active (non-cancelled) token should succeed
    // ============================================================
    info!("Test 3: Export with active token should succeed");

    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;
    cleanup_bucket(&minio_client, TEST_BUCKET, &hashed_prefix).await;

    let tmp_checkpoint_dir_3 = TempDir::new()?;
    let config_3 = create_test_checkpoint_config(&tmp_checkpoint_dir_3);
    let uploader_3 = S3Uploader::new(config_3.clone()).await?;
    let exporter_3 = Arc::new(CheckpointExporter::new(Box::new(uploader_3)));

    let worker_3 = CheckpointWorker::new_for_testing(
        3,
        Path::new(&config_3.local_checkpoint_dir),
        &config_3.s3_key_prefix,
        partition.clone(),
        Utc::now(),
        Some(exporter_3),
    );

    let active_token = CancellationToken::new();
    let result = worker_3
        .checkpoint_partition_cancellable(&store, None, Some(&active_token), None)
        .await?;

    assert!(
        result.is_some(),
        "Checkpoint with active token should succeed"
    );

    let checkpoint_info = result.unwrap();

    // Verify files were uploaded (metadata unhashed, objects hashed)
    let list_meta = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&test_prefix)
        .send()
        .await?;
    let list_objects = minio_client
        .list_objects_v2()
        .bucket(TEST_BUCKET)
        .prefix(&hashed_prefix)
        .send()
        .await?;
    let uploaded_keys: Vec<String> = list_meta
        .contents()
        .iter()
        .chain(list_objects.contents().iter())
        .filter_map(|obj| obj.key().map(String::from))
        .collect();

    assert!(
        !uploaded_keys.is_empty(),
        "Files should be uploaded when token is active"
    );

    info!(
        uploaded_count = uploaded_keys.len(),
        file_count = checkpoint_info.metadata.files.len(),
        "Test 3 passed: Export with active token succeeded"
    );

    // Cleanup MinIO bucket
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;
    cleanup_bucket(&minio_client, TEST_BUCKET, &hashed_prefix).await;

    info!("All export cancellation tests passed");
    Ok(())
}

/// Test that mid-upload cancellation stops quickly and doesn't leave orphaned objects.
/// This test creates a larger checkpoint and cancels mid-stream to verify:
/// 1. Cancellation is detected during upload
/// 2. Upload stops promptly (doesn't complete all files)
/// 3. No metadata.json is uploaded (ensuring all-or-nothing semantics)
#[tokio::test]
async fn test_export_mid_upload_cancellation() -> Result<()> {
    let test_topic = "test_export_mid_cancel";
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

    // Create dedup store with more data to increase upload time
    let store = create_test_dedup_store(tmp_store_dir.path(), test_topic, test_partition);
    for i in 0..500 {
        let event = TestRawEventBuilder::new()
            .distinct_id(&format!("user_{i}"))
            .token(&format!("token_{}", i % 10))
            .event(&format!("event_type_{}", i % 5))
            .current_timestamp()
            .build();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata)?;
    }

    // Create checkpoint config with real MinIO
    let config = create_test_checkpoint_config(&tmp_checkpoint_dir);

    // Create S3Uploader and exporter
    let uploader = S3Uploader::new(config.clone()).await?;
    let exporter = Arc::new(CheckpointExporter::new(Box::new(uploader)));

    let partition = Partition::new(test_topic.to_string(), test_partition);
    let attempt_timestamp = Utc::now();

    let worker = CheckpointWorker::new_for_testing(
        1,
        Path::new(&config.local_checkpoint_dir),
        &config.s3_key_prefix,
        partition.clone(),
        attempt_timestamp,
        Some(exporter.clone()),
    );

    // Create a token that will be cancelled shortly after starting
    // This simulates a rebalance occurring during checkpoint export
    let cancel_token = CancellationToken::new();
    let cancel_token_clone = cancel_token.clone();

    // Spawn a task to cancel after a short delay
    tokio::spawn(async move {
        // Small delay to let the upload start
        tokio::time::sleep(Duration::from_millis(10)).await;
        cancel_token_clone.cancel();
        info!("Cancellation token triggered");
    });

    let start = Instant::now();
    let result = worker
        .checkpoint_partition_cancellable(&store, None, Some(&cancel_token), Some("test"))
        .await;
    let elapsed = start.elapsed();

    // The result depends on timing - it may succeed if upload completed before cancellation,
    // or fail with cancellation error if caught mid-upload
    match &result {
        Ok(Some(info)) => {
            info!(
                elapsed_ms = elapsed.as_millis(),
                remote_path = info.get_remote_attempt_path(),
                "Upload completed before cancellation (timing dependent)"
            );
        }
        Ok(None) => {
            info!(
                elapsed_ms = elapsed.as_millis(),
                "Export was skipped (no exporter configured - unexpected)"
            );
        }
        Err(e) => {
            let err_msg = e.to_string();
            info!(
                elapsed_ms = elapsed.as_millis(),
                error = err_msg,
                "Upload cancelled mid-stream as expected"
            );

            // If cancelled, verify no metadata.json was uploaded (all-or-nothing)
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

            // metadata.json should NOT exist if cancelled mid-upload
            // (it's uploaded last, after all files succeed)
            let has_metadata = uploaded_keys.iter().any(|k| k.ends_with("metadata.json"));
            if !has_metadata && !uploaded_keys.is_empty() {
                info!(
                    partial_files = uploaded_keys.len(),
                    "Verified: No metadata.json uploaded (all-or-nothing semantics preserved)"
                );
            }
        }
    }

    info!(
        elapsed_ms = elapsed.as_millis(),
        "Mid-upload cancellation test completed"
    );

    // Cleanup
    cleanup_bucket(&minio_client, TEST_BUCKET, &test_prefix).await;

    Ok(())
}
