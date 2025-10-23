use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::Utc;

use kafka_deduplicator::checkpoint::{
    CheckpointConfig, CheckpointExporter, CheckpointMetadata, CheckpointPlan, CheckpointUploader,
    CheckpointWorker,
};
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{DeduplicationStore, DeduplicationStoreConfig, TimestampMetadata};

use common_types::RawEvent;

use anyhow::{Context, Result};
use tempfile::TempDir;
use tracing::info;

/// Mock uploader for testing that stores files in local filesystem
#[derive(Debug, Clone)]
pub struct MockUploader {
    /// Local directory where uploaded files are stored
    upload_dir: PathBuf,
    /// Whether the uploader should simulate being available
    available: bool,
}

impl MockUploader {
    pub fn new() -> Result<Self> {
        let temp_dir = TempDir::new()?;
        Ok(Self {
            upload_dir: temp_dir.path().to_path_buf(),
            available: true,
        })
    }

    pub fn new_unavailable() -> Result<Self> {
        let temp_dir = TempDir::new()?;
        Ok(Self {
            upload_dir: temp_dir.path().to_path_buf(),
            available: false,
        })
    }

    /// Get the stored files for testing
    pub async fn get_stored_files(&self) -> Result<HashMap<String, Vec<u8>>> {
        let mut files = HashMap::new();

        if !self.upload_dir.exists() {
            return Ok(files);
        }

        let mut stack = vec![self.upload_dir.clone()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_dir() {
                    stack.push(path);
                } else {
                    let relative_path = path.strip_prefix(&self.upload_dir)?;
                    let key = relative_path.to_string_lossy().replace('\\', "/");
                    let data = tokio::fs::read(&path).await?;
                    files.insert(key, data);
                }
            }
        }

        Ok(files)
    }

    /// Clear all stored files
    pub async fn clear(&self) -> Result<()> {
        if self.upload_dir.exists() {
            tokio::fs::remove_dir_all(&self.upload_dir).await?;
            tokio::fs::create_dir_all(&self.upload_dir).await?;
        }
        Ok(())
    }

    /// Get count of stored files
    pub async fn file_count(&self) -> Result<usize> {
        if !self.upload_dir.exists() {
            return Ok(0);
        }
        let files = self.get_stored_files().await?;
        Ok(files.len())
    }

    async fn upload_files(&self, files_to_upload: Vec<(PathBuf, String)>) -> Result<Vec<String>> {
        let mut uploaded_keys = Vec::new();

        for (local_file_path, remote_file_path_str) in files_to_upload {
            let remote_file_path = self.upload_dir.join(&remote_file_path_str);
            // Copy the file to the upload directory
            tokio::fs::copy(&local_file_path, &remote_file_path).await?;
            uploaded_keys.push(remote_file_path_str);
        }

        Ok(uploaded_keys)
    }
}

impl Default for MockUploader {
    fn default() -> Self {
        Self::new().unwrap()
    }
}

#[async_trait]
impl CheckpointUploader for MockUploader {
    async fn upload_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<Vec<String>> {
        info!(
            "Mock uploading checkpoint with plan: {} files to upload to remote path: {}",
            plan.files_to_upload.len(),
            plan.info.get_remote_attempt_path(),
        );

        let remote_parent_path = self.upload_dir.join(plan.info.get_remote_attempt_path());
        tokio::fs::create_dir_all(remote_parent_path).await?;

        let mut files_to_upload = Vec::new();
        for local_file in &plan.files_to_upload {
            files_to_upload.push((
                local_file.local_path.clone(),
                plan.info.get_file_key(&local_file.filename),
            ));
        }

        let mut uploaded_keys = self.upload_files(files_to_upload).await?;

        let metadata_key = self.upload_dir.join(plan.info.get_metadata_key());
        let metadata_json = &plan
            .info
            .metadata
            .to_json()
            .with_context(|| format!("Failed to serialize checkpoint metadata: {plan:?}"))?;
        tokio::fs::write(&metadata_key, metadata_json).await?;
        uploaded_keys.push(metadata_key.to_string_lossy().to_string());

        info!("Mock uploaded {} files with plan", uploaded_keys.len());
        Ok(uploaded_keys)
    }

    async fn is_available(&self) -> bool {
        self.available
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

#[tokio::test]
async fn test_checkpoint_exporter_creation() {
    let uploader = MockUploader::new().unwrap();
    let exporter = CheckpointExporter::new(Box::new(uploader));
    assert!(exporter.is_available().await);
}

#[tokio::test]
async fn test_unavailable_uploader() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_unavailable_uploader";
    let test_partition = 0;
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new_unavailable().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(uploader.clone())));

    let local_base_dir = Path::new(&config.local_checkpoint_dir);
    let remote_namespace = config.s3_key_prefix.clone();
    let attempt_timestamp = Utc::now();
    let partition = Partition::new(test_topic.to_string(), test_partition);

    let worker = CheckpointWorker::new(
        1,
        local_base_dir,
        remote_namespace,
        partition.clone(),
        attempt_timestamp,
        exporter.clone(),
    );

    // The wrapper thread closure that is spawned to run this in
    // production will catch and log/stat these errors
    let result = worker.checkpoint_partition(&store, None).await;
    assert!(result.is_err());

    // No files should be uploaded when the remote storage is unavailable
    let file_count = uploader.file_count().await.unwrap();
    assert_eq!(
        file_count, 0,
        "No files should be uploaded when uploader is unavailable"
    );
}

#[tokio::test]
async fn test_unpopulated_exporter() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_unpopulated_exporter";
    let test_partition = 0;
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let local_base_dir = Path::new(&config.local_checkpoint_dir);
    let remote_namespace = config.s3_key_prefix.clone();
    let attempt_timestamp = Utc::now();
    let partition = Partition::new(test_topic.to_string(), test_partition);

    // without an exporter supplied to the worker, the checkpoint will
    // succeed and be created locally but never uploaded to remote storage
    let worker = CheckpointWorker::new(
        1,
        local_base_dir,
        remote_namespace,
        partition.clone(),
        attempt_timestamp,
        None,
    );

    // Checkpoint should still succeed even if uploader is unavailable
    let result = worker.checkpoint_partition(&store, None).await;
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());
}

#[tokio::test]
async fn test_checkpoint_from_plan_with_no_previous_metadata() {
    let test_topic = "manual_cp_incremental";
    let test_partition = 0;
    let tmp_store_dir = TempDir::new().unwrap();
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(uploader.clone())));

    let local_base_dir = Path::new(&config.local_checkpoint_dir);
    let remote_namespace = config.s3_key_prefix.clone();
    let partition = Partition::new(test_topic.to_string(), test_partition);
    let attempt_timestamp = Utc::now();

    let worker = CheckpointWorker::new(
        1,
        local_base_dir,
        remote_namespace,
        partition.clone(),
        attempt_timestamp,
        exporter.clone(),
    );

    // Perform checkpoint without previous metadata
    let result = worker.checkpoint_partition(&store, None).await;
    assert!(result.is_ok());

    let result = result.unwrap();
    assert!(result.is_some());
    let info = result.unwrap();

    // manually construct expected remote attempt path as CheckpointInfo
    // would have to apply to all *new* files tracked in metadata.files
    let expected_remote_path = format!(
        "{}/{}/{}/{}",
        config.s3_key_prefix,
        partition.topic(),
        partition.partition_number(),
        CheckpointMetadata::generate_id(attempt_timestamp),
    );
    assert_eq!(info.get_remote_attempt_path(), expected_remote_path);

    let remote_checkpoint_files = uploader.get_stored_files().await.unwrap();
    assert!(!remote_checkpoint_files.is_empty());
    assert!(remote_checkpoint_files
        .keys()
        .all(|k| k.contains(&expected_remote_path)));

    // Verify exported files contain expected RocksDB checkpoint files
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with("CURRENT")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("MANIFEST-")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("OPTIONS-")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".sst")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".log")));
}

#[tokio::test]
async fn test_checkpoint_from_plan_with_previous_metadata() {
    // Note: detailed planner diffs are exercised in the planner test suite
    let test_topic = "test_cp_from_plan_with_prev_metadata";
    let test_partition = 0;
    let tmp_store_dir = TempDir::new().unwrap();
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        //create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(uploader.clone())));

    let local_base_dir = Path::new(&config.local_checkpoint_dir);
    let remote_namespace = config.s3_key_prefix.clone();
    let partition = Partition::new(test_topic.to_string(), test_partition);
    let attempt_timestamp = Utc::now();

    let worker = CheckpointWorker::new(
        1,
        local_base_dir,
        remote_namespace.clone(),
        partition.clone(),
        attempt_timestamp,
        exporter.clone(),
    );

    // Perform checkpoint without previous metadata
    let result = worker.checkpoint_partition(&store, None).await;
    assert!(result.is_ok());
    let result = result.unwrap();
    assert!(result.is_some());
    let orig_info = result.unwrap();

    // manually construct expected remote attempt path as CheckpointInfo
    // would have to apply to all *new* files tracked in metadata.files
    let orig_expected_remote_path = format!(
        "{}/{}/{}/{}",
        config.s3_key_prefix,
        partition.topic(),
        partition.partition_number(),
        CheckpointMetadata::generate_id(attempt_timestamp),
    );
    assert_eq!(
        orig_info.get_remote_attempt_path(),
        orig_expected_remote_path
    );

    let orig_remote_checkpoint_files = uploader.get_stored_files().await.unwrap();
    assert!(!orig_remote_checkpoint_files.is_empty());
    assert!(orig_remote_checkpoint_files
        .keys()
        .all(|k| k.contains(&orig_expected_remote_path)));

    // Verify exported files contain expected RocksDB checkpoint files, including SSTs
    assert!(orig_remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with(".sst")));
    assert!(orig_remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with("CURRENT")));
    assert!(orig_remote_checkpoint_files
        .keys()
        .any(|k| k.contains("MANIFEST-")));
    assert!(orig_remote_checkpoint_files
        .keys()
        .any(|k| k.contains("OPTIONS-")));
    assert!(orig_remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with(".log")));

    // Do not add more test data so SST files don't change across checkpoints.
    // Await > 1 second so timestamp attempt directory changes between checkpoints
    tokio::time::sleep(Duration::from_millis(1100)).await;

    let next_attempt_timestamp = Utc::now();
    let next_checkpoint_id = CheckpointMetadata::generate_id(next_attempt_timestamp);
    let next_expected_remote_path = format!(
        "{}/{}/{}/{}",
        config.s3_key_prefix,
        partition.topic(),
        partition.partition_number(),
        next_checkpoint_id,
    );

    assert!(uploader.clear().await.is_ok());

    let worker_next = CheckpointWorker::new(
        2,
        local_base_dir,
        remote_namespace,
        partition.clone(),
        next_attempt_timestamp,
        exporter.clone(),
    );
    let result = worker_next
        .checkpoint_partition(&store, Some(&orig_info.metadata))
        .await;
    assert!(result.is_ok());
    let result = result.unwrap();
    assert!(result.is_some());

    // The new checkpoint metadata should contain a mix of new and reused files
    let info = result.unwrap();
    assert_eq!(info.get_remote_attempt_path(), next_expected_remote_path);
    let next_remote_checkpoint_files = uploader.get_stored_files().await.unwrap();

    assert!(!next_remote_checkpoint_files.is_empty());
    assert!(next_remote_checkpoint_files
        .keys()
        .all(|k| k.contains(&next_expected_remote_path)));

    // there should be no new SST files uploaded in this checkpoint
    // because the original checkpoint uploaded them already
    assert!(next_remote_checkpoint_files
        .keys()
        .all(|k| !k.ends_with(".sst")));

    // Verify exported files contain expected RocksDB non-SST files
    // For now, we always upload the latest CURRENT, but
    // but this attempt, we don't upload new MANIFEST, OPTIONS,
    // or .log (WAL) files because the checksums will not be different
    assert!(next_remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with("CURRENT")));
    assert!(next_remote_checkpoint_files
        .keys()
        .all(|k| !k.contains("MANIFEST-")));
    assert!(next_remote_checkpoint_files
        .keys()
        .all(|k| !k.contains("OPTIONS-")));
    assert!(next_remote_checkpoint_files
        .keys()
        .all(|k| !k.ends_with(".log")));
}
