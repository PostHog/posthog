use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use kafka_deduplicator::checkpoint::{
    CheckpointConfig, CheckpointExporter, CheckpointMode, CheckpointPlan, CheckpointTarget,
    CheckpointUploader, CheckpointWorker,
};
use kafka_deduplicator::checkpoint_manager::CheckpointManager;
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{DeduplicationStore, DeduplicationStoreConfig, TimestampMetadata};
use kafka_deduplicator::store_manager::StoreManager;

use common_types::RawEvent;

use anyhow::Result;
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

    fn collect_files_to_upload(
        &self,
        base_path: &Path,
        key_prefix: &str,
    ) -> Result<Vec<(PathBuf, String)>> {
        let mut files_to_upload = Vec::new();
        let mut stack = vec![base_path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_dir() {
                    stack.push(path);
                } else {
                    let relative_path = path.strip_prefix(base_path)?;
                    let key = format!(
                        "{}/{}",
                        key_prefix,
                        relative_path.to_string_lossy().replace('\\', "/")
                    );
                    files_to_upload.push((path, key));
                }
            }
        }

        Ok(files_to_upload)
    }

    async fn upload_files(&self, files_to_upload: Vec<(PathBuf, String)>) -> Result<Vec<String>> {
        let mut uploaded_keys = Vec::new();

        for (local_path, key) in files_to_upload {
            let target_path = self.upload_dir.join(&key);

            // Create parent directories if they don't exist
            if let Some(parent) = target_path.parent() {
                tokio::fs::create_dir_all(parent).await?;
            }

            // Copy the file to the upload directory
            tokio::fs::copy(&local_path, &target_path).await?;
            uploaded_keys.push(key.clone());

            info!(
                "Mock uploaded file {:?} with key {} to {:?}",
                local_path, key, target_path
            );
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
    async fn upload_checkpoint_dir(
        &self,
        local_path: &Path,
        key_prefix: &str,
    ) -> Result<Vec<String>> {
        if !local_path.exists() {
            return Err(anyhow::anyhow!(
                "Local checkpoint path does not exist: {:?}",
                local_path
            ));
        }

        info!(
            "Mock uploading checkpoint directory: {:?} with prefix {}",
            local_path, key_prefix
        );

        let files_to_upload = self.collect_files_to_upload(local_path, key_prefix)?;
        let uploaded_keys = self.upload_files(files_to_upload).await?;

        info!("Mock uploaded {} files", uploaded_keys.len());
        Ok(uploaded_keys)
    }

    async fn upload_checkpoint_with_plan(
        &self,
        plan: &CheckpointPlan,
        key_prefix: &str,
    ) -> Result<Vec<String>> {
        info!(
            "Mock uploading checkpoint with plan: {} files to upload, prefix {}",
            plan.files_to_upload.len(),
            key_prefix
        );

        let mut files_to_upload = Vec::new();
        for (filename, local_path) in &plan.files_to_upload {
            let key = format!("{key_prefix}/{filename}");
            files_to_upload.push((PathBuf::from(local_path), key));
        }

        let mut uploaded_keys = self.upload_files(files_to_upload).await?;

        let metadata_key = format!("{key_prefix}/metadata.json");
        let metadata_path = self.upload_dir.join(&metadata_key);
        if let Some(parent) = metadata_path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let metadata_json = serde_json::to_string_pretty(&plan.metadata)?;
        tokio::fs::write(&metadata_path, metadata_json).await?;
        uploaded_keys.push(metadata_key);

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
    let temp_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: temp_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = MockUploader::new().unwrap();
    let exporter = CheckpointExporter::new(config, Box::new(uploader));
    assert!(exporter.is_available().await);
}

#[tokio::test]
async fn test_manual_checkpoint_export_incremental() {
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
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new(test_topic.to_string(), test_partition);
    let target =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    let worker = CheckpointWorker::new(1, target.clone(), exporter.clone());

    // Perform checkpoint
    let result = worker
        .checkpoint_partition(CheckpointMode::Incremental, &store, None)
        .await;
    assert!(result.is_ok());

    let result = result.unwrap();
    assert!(result.is_some());

    // the expected remote path will include the bucket prefix
    let expected = format!("test-prefix/{}", &target.remote_path);
    let (remote_path, _metadata) = result.as_ref().unwrap();
    assert!(
        remote_path == &expected,
        "remote path should match {expected}, got: {remote_path:?}",
    );

    let remote_checkpoint_files = uploader.get_stored_files().await.unwrap();
    assert!(!remote_checkpoint_files.is_empty());
    assert!(remote_checkpoint_files
        .keys()
        .all(|k| k.contains("test-prefix/")));

    // Verify exported files contain expected RocksDB checkpoint files
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with("CURRENT")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("MANIFEST")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("OPTIONS")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".sst")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".log")));
}

#[tokio::test]
async fn test_checkpoint_manual_export_full() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_checkpoint_manual_full";
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
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new(test_topic.to_string(), test_partition);
    let target =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    let worker = CheckpointWorker::new(1, target.clone(), exporter.clone());

    let result = worker
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
    assert!(
        result.is_ok(),
        "checkpoint should succeed: {:?}",
        result.err()
    );

    let remote_checkpoint_files = uploader.get_stored_files().await.unwrap();
    assert!(!remote_checkpoint_files.is_empty());
    assert!(remote_checkpoint_files
        .keys()
        .all(|k| k.contains("test-prefix/")));

    // Verify exported files contain expected RocksDB checkpoint files
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.ends_with("CURRENT")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("MANIFEST")));
    assert!(remote_checkpoint_files
        .keys()
        .any(|k| k.contains("OPTIONS")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".sst")));
    assert!(remote_checkpoint_files.keys().any(|k| k.ends_with(".log")));
}

// TODO: incremental snapshot and export is not implemented yet, but
// the manager is wired up to track and perform N incrementals per
// full snapshot. This test case exercises the config and staging logic
#[tokio::test]
async fn test_incremental_vs_full_upload_serial() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_incremental_vs_full_upload_serial";
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
        checkpoint_interval: Duration::from_millis(50),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        full_upload_interval: 2,
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: tmp_store_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let mut manager = CheckpointManager::new(config, store_manager, exporter);

    // let the checkpoint worker loop run long enough to perform some checkpoints
    manager.start();
    tokio::time::sleep(Duration::from_millis(250)).await;
    manager.stop().await;

    // eval if multiple uploads were performed
    let stored_files = uploader.get_stored_files().await.unwrap();

    assert!(
        stored_files.len() >= 4,
        "Should have performed at least four checkpoints, got {}",
        stored_files.len()
    );

    assert!(
        stored_files.keys().all(|k| k.contains("test-prefix/")),
        "All uploads should be under test-prefix/"
    );
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
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new_unavailable().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new("test_topic".to_string(), 0);
    let target =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    let worker = CheckpointWorker::new(1, target, exporter.clone());

    // The wrapper thread closure that is spawned to run this in
    // production will catch and log/stat these errors
    let result = worker
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
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
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let partition = Partition::new("test_topic".to_string(), 0);
    let target =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    // without an exporter supplied to the worker, the checkpoint will
    // succeed and be created locally but never uploaded to remote storage
    let worker = CheckpointWorker::new(1, target, None);

    // Checkpoint should still succeed even if uploader is unavailable
    let result = worker
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());
}

#[tokio::test]
async fn test_incremental_checkpoint_with_no_changes() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_incremental_no_changes";
    let test_partition = 0;
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

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
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new(test_topic.to_string(), test_partition);
    let target1 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    let worker1 = CheckpointWorker::new(1, target1.clone(), exporter.clone());

    let result1 = worker1
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
    assert!(result1.is_ok());

    let (remote_path1, metadata1) = result1.unwrap().unwrap();
    let files_before = uploader.get_stored_files().await.unwrap();
    let file_count_checkpoint1 = files_before.len();

    tokio::time::sleep(Duration::from_millis(1100)).await;

    let target2 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    let worker2 = CheckpointWorker::new(2, target2.clone(), exporter.clone());

    let result2 = worker2
        .checkpoint_partition(CheckpointMode::Incremental, &store, Some(&metadata1))
        .await;
    assert!(result2.is_ok());

    let (remote_path2, metadata2) = result2.unwrap().unwrap();
    let files_after = uploader.get_stored_files().await.unwrap();

    assert_ne!(remote_path1, remote_path2);

    let new_files_count = files_after.len() - file_count_checkpoint1;
    assert!(
        new_files_count <= 2,
        "Expected only metadata.json and maybe one other file, got {new_files_count} new files",
    );

    let reused_file_count = metadata2
        .files
        .iter()
        .filter(|f| f.starts_with("../"))
        .count();
    assert!(
        reused_file_count > 0,
        "Expected some files to be reused with relative paths"
    );

    let total_files = metadata2.files.len();
    assert!(
        reused_file_count >= total_files - 5,
        "Expected most files to be reused: {reused_file_count}/{total_files} reused",
    );
}

#[tokio::test]
async fn test_incremental_checkpoint_with_new_data() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_incremental_with_changes";
    let test_partition = 0;
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    let events1 = vec![create_test_raw_event("user1", "token1", "event1")];
    for event in &events1 {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new(test_topic.to_string(), test_partition);
    let target1 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();

    let worker1 = CheckpointWorker::new(1, target1.clone(), exporter.clone());

    let result1 = worker1
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
    assert!(result1.is_ok());

    let (remote_path1, metadata1) = result1.unwrap().unwrap();
    let files_before = uploader.get_stored_files().await.unwrap();
    let file_count_checkpoint1 = files_before.len();

    let events2 = vec![
        create_test_raw_event("user2", "token1", "event2"),
        create_test_raw_event("user3", "token1", "event3"),
        create_test_raw_event("user4", "token1", "event4"),
    ];
    for event in &events2 {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    tokio::time::sleep(Duration::from_millis(1100)).await;

    let target2 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    let worker2 = CheckpointWorker::new(2, target2.clone(), exporter.clone());

    let result2 = worker2
        .checkpoint_partition(CheckpointMode::Incremental, &store, Some(&metadata1))
        .await;
    assert!(result2.is_ok());

    let (remote_path2, metadata2) = result2.unwrap().unwrap();
    let files_after = uploader.get_stored_files().await.unwrap();

    assert_ne!(remote_path1, remote_path2);

    let new_files_count = files_after.len() - file_count_checkpoint1;
    assert!(
        new_files_count >= 1,
        "Expected at least metadata.json to be uploaded, got {new_files_count} new files",
    );

    let reused_file_count = metadata2
        .files
        .iter()
        .filter(|f| f.starts_with("../"))
        .count();
    assert!(
        reused_file_count > 0,
        "Expected some files to be reused with relative paths"
    );

    let new_file_count = metadata2
        .files
        .iter()
        .filter(|f| !f.starts_with("../"))
        .count();
    assert!(
        new_file_count > 0,
        "Expected some new files to be created due to new data"
    );

    assert!(
        files_after.keys().any(|k| k.contains("metadata.json")),
        "Expected metadata.json to be uploaded"
    );
}

#[tokio::test]
async fn test_chained_incremental_checkpoints() {
    let tmp_store_dir = TempDir::new().unwrap();
    let test_topic = "test_chained_incremental";
    let test_partition = 0;
    let store = create_test_dedup_store(&tmp_store_dir, test_topic, test_partition);

    let events1 = vec![create_test_raw_event("user1", "token1", "event1")];
    for event in &events1 {
        let key = event.into();
        let metadata = TimestampMetadata::new(event);
        store.put_timestamp_record(&key, &metadata).unwrap();
    }

    let tmp_checkpoint_dir = TempDir::new().unwrap();
    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        aws_region: "us-east-1".to_string(),
        ..Default::default()
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    let partition = Partition::new(test_topic.to_string(), test_partition);

    let target1 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    let worker1 = CheckpointWorker::new(1, target1, exporter.clone());
    let result1 = worker1
        .checkpoint_partition(CheckpointMode::Full, &store, None)
        .await;
    assert!(result1.is_ok());
    let (remote_path1, metadata1) = result1.unwrap().unwrap();

    tokio::time::sleep(Duration::from_millis(1100)).await;

    let target2 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    let worker2 = CheckpointWorker::new(2, target2, exporter.clone());
    let result2 = worker2
        .checkpoint_partition(CheckpointMode::Incremental, &store, Some(&metadata1))
        .await;
    assert!(result2.is_ok());
    let (remote_path2, metadata2) = result2.unwrap().unwrap();

    tokio::time::sleep(Duration::from_millis(1100)).await;

    let target3 =
        CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    let worker3 = CheckpointWorker::new(3, target3, exporter.clone());
    let result3 = worker3
        .checkpoint_partition(CheckpointMode::Incremental, &store, Some(&metadata2))
        .await;
    assert!(result3.is_ok());
    let (remote_path3, metadata3) = result3.unwrap().unwrap();

    assert_ne!(remote_path1, remote_path2);
    assert_ne!(remote_path2, remote_path3);
    assert_ne!(remote_path1, remote_path3);

    let files_referencing_checkpoint1 = metadata3
        .files
        .iter()
        .filter(|f| f.contains(&metadata1.id))
        .count();
    assert!(
        files_referencing_checkpoint1 > 0,
        "Expected some files in checkpoint 3 to reference checkpoint 1"
    );
}
