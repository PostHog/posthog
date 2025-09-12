use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use kafka_deduplicator::checkpoint::{CheckpointConfig, CheckpointExporter, CheckpointUploader};
use kafka_deduplicator::checkpoint_manager::{
    CheckpointMode, CheckpointPath, CheckpointWorker, CHECKPOINT_NAME_PREFIX,
};
use kafka_deduplicator::kafka::types::Partition;
use kafka_deduplicator::store::{DeduplicationStore, DeduplicationStoreConfig};
use kafka_deduplicator::store_manager::StoreManager;

use common_types::RawEvent;

use anyhow::Result;
use tempfile::TempDir;
use tokio::sync::Mutex;
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

    async fn is_available(&self) -> bool {
        self.available
    }
}

fn create_test_dedup_store() -> (DeduplicationStore, TempDir) {
    let temp_dir = TempDir::new().unwrap();
    let config = DeduplicationStoreConfig {
        path: temp_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    };
    let store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();
    (store, temp_dir)
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
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = MockUploader::new().unwrap();
    let exporter = CheckpointExporter::new(config, Box::new(uploader));
    assert!(exporter.is_available().await);
}

#[tokio::test]
async fn test_manual_checkpoint() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = MockUploader::new().unwrap();
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        Box::new(uploader),
    )));
    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());
    let worker = CheckpointWorker::new(
        1,
        CheckpointMode::Full,
        paths.clone(),
        store.clone(),
        exporter.clone(),
    );

    // Perform checkpoint
    let result = worker.checkpoint_partition().await;
    assert!(result.is_ok());

    let result = result.unwrap();
    assert!(result.is_some());
    assert!(result.unwrap() == paths.remote_path);

}

#[tokio::test]
async fn test_checkpoint_skips_when_in_progress() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    // TODO(eli): convert test to use CheckpointManager and worker loop
    let checkpoint_counters = Arc::new(Mutex::new(HashMap::<Partition, u32>::new()));
    let is_checkpointing = Arc::new(Mutex::new(HashSet::new()));

    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let worker1 = CheckpointWorker::new(
        1,
        CheckpointMode::Full,
        paths.clone(),
        store.clone(),
        exporter.clone(),
    );
    let worker2 = CheckpointWorker::new(
        2,
        CheckpointMode::Full,
        paths.clone(),
        store.clone(),
        exporter.clone(),
    );

    let (result1, result2) = tokio::join!(
        worker1.checkpoint_partition(),
        worker2.checkpoint_partition(),
    );

    // Both should succeed
    assert!(result1.is_ok(), "First checkpoint should succeed");
    assert!(result2.is_ok(), "Second checkpoint should succeed");

    let first_completed = result1.unwrap();
    let second_completed = result2.unwrap();

    println!("First checkpoint completed: {}", first_completed.is_some());
    println!(
        "Second checkpoint completed: {}",
        second_completed.is_some()
    );

    // Exactly one should have completed the checkpoint, one should have been skipped
    assert!(
        (first_completed.is_some() && second_completed.is_none())
            || (first_completed.is_none() && second_completed.is_some()),
        "Exactly one checkpoint should complete, the other should be skipped"
    );

    // Verify only one set of files was uploaded (one checkpoint worth)
    let uploaded_files = uploader.get_stored_files().await.unwrap();
    let file_count = uploaded_files.len();

    // Should have the typical checkpoint files: CURRENT, MANIFEST, OPTIONS, SST files
    assert!(file_count > 0, "Should have uploaded checkpoint files");

    // All files should have the same checkpoint timestamp (same directory)
    let checkpoint_dirs: std::collections::HashSet<_> = uploaded_files
        .keys()
        .filter_map(|key| {
            if let Some(start) = key.find(CHECKPOINT_NAME_PREFIX) {
                let end = key[start..].find('/').map(|i| start + i)?;
                Some(&key[start..end])
            } else {
                None
            }
        })
        .collect();

    assert_eq!(
        checkpoint_dirs.len(),
        1,
        "All files should belong to exactly one checkpoint directory, found: {checkpoint_dirs:?}"
    );
}

#[tokio::test]
async fn test_checkpoint_with_mock_uploader() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    // TODO(eli): convert test to use CheckpointManager and worker loop
    let checkpoint_counters = Arc::new(Mutex::new(HashMap::<Partition, u32>::new()));
    let is_checkpointing = Arc::new(Mutex::new(HashSet::new()));

    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let worker = CheckpointWorker::new(
        1,
        CheckpointMode::Full,
        paths,
        store.clone(),
        exporter.clone(),
    );

    let result = worker.checkpoint_partition().await;
    assert!(result.is_ok());
    assert!(result.unwrap().is_some());
    assert!(result.unwrap().unwrap() == paths.remote_path);

    // Verify files were "uploaded" to mock storage
    let file_count = uploader.file_count().await.unwrap();
    assert!(file_count > 0, "Should have uploaded some files");

    let stored_files = uploader.get_stored_files().await.unwrap();
    assert!(
        !stored_files.is_empty(),
        "Should have stored files in mock uploader"
    );
}

#[tokio::test]
async fn test_incremental_vs_full_upload() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 3,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 6,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = Box::new(MockUploader::new().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));

    // TODO(eli): convert test to use CheckpointManager and worker loop
    let checkpoint_counters = Arc::new(Mutex::new(HashMap::<Partition, u32>::new()));
    let is_checkpointing = Arc::new(Mutex::new(HashSet::new()));

    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let worker = CheckpointWorker::new(
        1,
        CheckpointMode::Full,
        paths,
        store.clone(),
        exporter.clone(),
    );

    // Perform multiple checkpoints
    for i in 0..=config.max_local_checkpoints {
        let result = worker.checkpoint_partition().await;
        assert!(
            result.is_ok(),
            "Checkpoint {i} should succeed, got: {:?}",
            result.err()
        );
        assert!(
            result.unwrap().is_some(),
            "Checkpoint {i} should return a checkpoint's remote path prefix",
        );

        let stored_files = uploader.get_stored_files().await.unwrap();

        // Check if this was a full upload (every 3rd checkpoint)
        let should_be_full = i % (config.full_upload_interval as usize) == 0;
        let has_full_uploads = stored_files.keys().any(|k| k.contains("/full/"));
        let has_incremental_uploads = stored_files.keys().any(|k| k.contains("/incremental/"));

        println!(
            "Checkpoint {i}: should_be_full={should_be_full}, has_full={has_full_uploads}, has_incremental={has_incremental_uploads}"
        );
        println!("Keys: {:?}", stored_files.keys().collect::<Vec<_>>());

        // Clear the mock uploader between checks to isolate each checkpoint's uploads
        uploader.clear().await.unwrap();

        if should_be_full {
            assert!(
                has_full_uploads,
                "Checkpoint {i} should create full uploads"
            );
        } else {
            assert!(
                has_incremental_uploads,
                "Checkpoint {i} should create incremental uploads"
            );
        }
    }
}

#[tokio::test]
async fn test_unavailable_uploader() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let uploader = Box::new(MockUploader::new_unavailable().unwrap());
    let exporter = Some(Arc::new(CheckpointExporter::new(
        config.clone(),
        uploader.clone(),
    )));
    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let worker = CheckpointWorker::new(
        1,
        CheckpointMode::Full,
        paths,
        store.clone(),
        exporter.clone(),
    );

    // Now that we report (log/stat) the successful local checkpoint and
    // the unavailable uploader without failing the run or bubbling up
    // and crashing the worker, feels like erroring is the right output
    // for this? We will want to monitor + alert on it when frequent enough
    let result = worker.checkpoint_partition().await;
    assert!(result.is_err());

    // No files should be uploaded
    let file_count = uploader.file_count().await.unwrap();
    assert_eq!(
        file_count, 0,
        "No files should be uploaded when uploader is unavailable"
    );
}

#[tokio::test]
async fn test_unpopulated_exporter() {
    let checkpoint_dir = TempDir::new().unwrap();
    let (store, _store_temp) = create_test_dedup_store();

    // Add some test data
    let events = vec![
        create_test_raw_event("user1", "token1", "event1"),
        create_test_raw_event("user2", "token1", "event2"),
    ];
    for event in &events {
        let result = store.handle_event_with_raw(event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // All events should be new
    }

    let config = CheckpointConfig {
        checkpoint_interval: Duration::from_secs(60),
        cleanup_interval: Duration::from_secs(60),
        local_checkpoint_dir: checkpoint_dir.path().to_string_lossy().to_string(),
        s3_bucket: "test-bucket".to_string(),
        s3_key_prefix: "test-prefix".to_string(),
        full_upload_interval: 5,
        aws_region: "us-east-1".to_string(),
        max_local_checkpoints: 3,
        max_concurrent_checkpoints: 1,
        s3_timeout: Duration::from_secs(30),
    };

    let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
        path: checkpoint_dir.path().to_path_buf(),
        max_capacity: 1_000_000,
    }));

    let partition = Partition::new("test_topic".to_string(), 0);
    let paths =
        CheckpointPath::new(partition.clone(), Path::new(&config.local_checkpoint_dir)).unwrap();
    store_manager
        .stores()
        .insert(partition.clone(), store.clone());

    let worker = CheckpointWorker::new(1, CheckpointMode::Full, paths, store.clone(), None);

    // Checkpoint should still succeed even if uploader is unavailable
    let result = worker.checkpoint_partition().await;
    assert!(result.is_ok()); // Should return OK result
    assert!(result.unwrap().is_none()); // Should return false for non-existent partition
}
