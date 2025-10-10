use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use super::{CheckpointExporter, CheckpointMetadata, CheckpointTarget, CheckpointType};
use crate::metrics_const::{
    CHECKPOINT_DURATION_HISTOGRAM, CHECKPOINT_FILE_COUNT_HISTOGRAM, CHECKPOINT_SIZE_HISTOGRAM,
    CHECKPOINT_WORKER_METADATA_EXPORTED_COUNTER, CHECKPOINT_WORKER_META_EXPORT_DURATION_HISTOGRAM,
    CHECKPOINT_WORKER_STATUS_COUNTER,
};
use crate::store::DeduplicationStore;

use anyhow::{Context, Result};
use metrics;
use tracing::{error, info, warn};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Copy)]
pub enum CheckpointMode {
    Full,
    Incremental,
}

impl CheckpointMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            CheckpointMode::Full => "full",
            CheckpointMode::Incremental => "incremental",
        }
    }
}

impl From<CheckpointType> for CheckpointMode {
    fn from(ct: CheckpointType) -> Self {
        match ct {
            CheckpointType::Full => CheckpointMode::Full,
            CheckpointType::Partial => CheckpointMode::Incremental,
        }
    }
}

/// Worker that handles checkpoint processing for individual partitions
pub struct CheckpointWorker {
    /// Worker ID for logging
    worker_id: u32,

    /// Target partition checkpoint path helper
    target: CheckpointTarget,

    /// Checkpoint export module
    exporter: Option<Arc<CheckpointExporter>>,
}

impl CheckpointWorker {
    pub fn new(
        worker_id: u32,
        target: CheckpointTarget,
        exporter: Option<Arc<CheckpointExporter>>,
    ) -> Self {
        Self {
            worker_id,
            target,
            exporter,
        }
    }

    /// Perform a checkpoint for the given (assumed active) partition and store
    pub async fn checkpoint_partition(
        &self,
        mode: CheckpointMode,
        store: &DeduplicationStore,
    ) -> Result<Option<CheckpointMetadata>> {
        let local_path_tag = self.target.local_path_tag();

        info!(
            self.worker_id,
            local_path = local_path_tag,
            checkpoint_mode = mode.as_str(),
            "Checkpoint worker: initializing checkpoint"
        );

        // Ensure local checkpoint directory exists - results observed internally, safe to bubble up
        self.create_partition_checkpoint_directory(mode).await?;

        // this creates the local RocksDB checkpoint - results observed internally, safe to bubble up
        let sst_files = self
            .create_local_partition_checkpoint(mode, store)
            .await
            .context("In checkpoint_partition")?;

        let metadata = self
            .create_local_metadata_file(sst_files, mode)
            .await
            .context("In checkpoint_partition")?;

        // update store metrics - this can fail without blocking the checkpoint attempt
        if let Err(e) = store.update_metrics() {
            warn!(
                self.worker_id,
                local_path = local_path_tag,
                checkpoint_mode = mode.as_str(),
                "Checkpoint worker: failed store metrics update after local checkpoint: {}",
                e
            );
        }

        // export the checkpoint and metadata file - observed internally, safe to return result
        match self.export_checkpoint(&metadata).await {
            Ok(true) => {}
            Ok(false) => return Ok(None),
            Err(e) => return Err(anyhow::anyhow!(e)),
        };

        // the checkpoint upload was successful so now upload
        // the metadata file. ensures future import attempts
        // will see this attempt as successful
        match self.export_metadata(&metadata).await {
            Ok(true) => Ok(Some(metadata)),
            Ok(false) => Ok(None),
            Err(e) => Err(anyhow::anyhow!(e)),
        }
    }

    async fn create_partition_checkpoint_directory(&self, mode: CheckpointMode) -> Result<()> {
        // NOTE: the RocksDB client likes to create the final directory in the
        // checkpoint path and will error if the parent dirs do not exist, *or*
        // the full path exists ahead of the checkpoint attempt. Here, we only
        // create the *parent directories* above the attempt-scoped timestamp
        // directory that will house the RocksDB files for export
        if let Err(e) = tokio::fs::create_dir_all(&self.target.local_base_path()).await {
            let tags = [
                ("mode", mode.as_str()),
                ("result", "error"),
                ("cause", "create_local_chkpt_dir"),
            ];
            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
            error!(
                self.worker_id,
                local_base_path = self.target.local_base_path().to_string_lossy().to_string(),
                checkpoint_mode = mode.as_str(),
                "Checkpoint worker: failed to create local directory: {}",
                e
            );
            return Err(anyhow::anyhow!(e));
        }

        Ok(())
    }

    async fn create_local_metadata_file(
        &self,
        sst_files: Vec<String>,
        mode: CheckpointMode,
    ) -> Result<CheckpointMetadata> {
        let mut metadata = CheckpointMetadata::new(
            mode.into(),
            self.target.clone(),
            0,
            0,
            sst_files.len() as u64,
        );

        metadata
            .add_files(&sst_files)
            .await
            .context("In create_local_metadata_file")?;
        metadata
            .save_to_file()
            .await
            .context("In create_local_metadata_file")?;

        Ok(metadata)
    }

    async fn create_local_partition_checkpoint(
        &self,
        mode: CheckpointMode,
        store: &DeduplicationStore,
    ) -> Result<Vec<String>> {
        let start_time = Instant::now();
        let local_path_tag = self.target.local_path_tag();
        let local_attempt_path = self
            .target
            .local_attempt_path()
            .context("In create_local_partition_checkpoint")?;

        match store.create_local_checkpoint(&local_attempt_path, mode) {
            Ok(sst_files) => {
                let checkpoint_duration = start_time.elapsed();
                metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
                    .record(checkpoint_duration.as_secs_f64());

                metrics::histogram!(CHECKPOINT_FILE_COUNT_HISTOGRAM).record(sst_files.len() as f64);
                if let Ok(checkpoint_size) = Self::get_directory_size(&local_attempt_path).await {
                    metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);
                }

                info!(
                    self.worker_id,
                    local_path = &local_path_tag,
                    sst_file_count = sst_files.len(),
                    checkpoint_mode = mode.as_str(),
                    "Created local checkpoint",
                );

                Ok(sst_files)
            }

            Err(e) => {
                // Build the complete error chain
                let mut error_chain = vec![format!("{:?}", e)];
                let mut source = e.source();
                while let Some(err) = source {
                    error_chain.push(format!("Caused by: {err:?}"));
                    source = err.source();
                }

                let tags = [
                    ("mode", mode.as_str()),
                    ("result", "error"),
                    ("cause", "local_checkpoint"),
                ];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                error!(
                    self.worker_id,
                    local_path = &local_path_tag,
                    checkpoint_mode = mode.as_str(),
                    "Local checkpoint failed: {}",
                    error_chain.join(" -> ")
                );

                Err(anyhow::anyhow!(error_chain.join(" -> ")))
            }
        }
    }

    async fn export_metadata(&self, metadata: &CheckpointMetadata) -> Result<bool> {
        let start_time = Instant::now();
        let local_path_tag = self.target.local_path_tag();
        let mode: CheckpointMode = metadata.checkpoint_type.into();

        info!(
            self.worker_id,
            local_path = local_path_tag,
            checkpoint_mode = mode.as_str(),
            "Checkpoint worker: exporting remote metadata",
        );

        match self.exporter.as_ref() {
            Some(exporter) => match exporter.export_metadata(metadata).await {
                Ok(()) => {
                    let tags = [("mode", mode.as_str()), ("result", "success")];
                    metrics::counter!(CHECKPOINT_WORKER_METADATA_EXPORTED_COUNTER, &tags)
                        .increment(1);
                    let export_duration = start_time.elapsed();
                    metrics::histogram!(CHECKPOINT_WORKER_META_EXPORT_DURATION_HISTOGRAM)
                        .record(export_duration.as_secs_f64());
                    Ok(true)
                }
                Err(e) => {
                    let tags = [("mode", mode.as_str()), ("result", "error")];
                    metrics::counter!(CHECKPOINT_WORKER_METADATA_EXPORTED_COUNTER, &tags)
                        .increment(1);
                    error!(
                        self.worker_id,
                        local_path = local_path_tag,
                        checkpoint_mode = mode.as_str(),
                        "Checkpoint worker: failed to export metadata: {}",
                        e
                    );

                    Err(anyhow::anyhow!(e))
                }
            },
            None => {
                let tags = [("mode", mode.as_str()), ("result", "skipped")];
                metrics::counter!(CHECKPOINT_WORKER_METADATA_EXPORTED_COUNTER, &tags).increment(1);

                Ok(false)
            }
        }
    }

    async fn export_checkpoint(&self, metadata: &CheckpointMetadata) -> Result<bool> {
        let local_path_tag = self.target.local_path_tag();
        let mode: CheckpointMode = metadata.checkpoint_type.into();

        info!(
            self.worker_id,
            local_path = local_path_tag,
            checkpoint_mode = mode.as_str(),
            "Checkpoint worker: exporting remote checkpoint",
        );

        match self.exporter.as_ref() {
            Some(exporter) => match exporter.export_checkpoint(metadata).await {
                Ok(remote_key_prefix) => {
                    let tags = [
                        ("mode", mode.as_str()),
                        ("result", "success"),
                        ("export", "success"),
                    ];
                    metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                    info!(
                        self.worker_id,
                        local_path = local_path_tag,
                        remote_path = remote_key_prefix,
                        checkpoint_mode = mode.as_str(),
                        "Checkpoint exported successfully"
                    );

                    Ok(true)
                }

                Err(e) => {
                    let tags = [
                        ("mode", mode.as_str()),
                        ("result", "error"),
                        ("cause", "export"),
                    ];
                    metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                    error!(
                        self.worker_id,
                        local_path = local_path_tag,
                        checkpoint_mode = mode.as_str(),
                        "Checkpoint failed to export: {}",
                        e
                    );

                    Err(e)
                }
            },

            None => {
                let tags = [
                    ("mode", mode.as_str()),
                    ("result", "success"),
                    ("export", "skipped"),
                ];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                warn!(
                    self.worker_id,
                    local_path = local_path_tag,
                    checkpoint_mode = mode.as_str(),
                    "Checkpoint upload skipped: no exporter configured",
                );

                Ok(false)
            }
        }
    }

    async fn get_directory_size(path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .context("Failed to read directory")?;

            while let Some(entry) = entries.next_entry().await? {
                let entry_path = entry.path();
                if entry_path.is_dir() {
                    stack.push(entry_path);
                } else {
                    let metadata = entry.metadata().await?;
                    total_size += metadata.len();
                }
            }
        }

        Ok(total_size)
    }
}

#[cfg(test)]
mod tests {
    use crate::kafka::types::Partition;
    use std::time::SystemTime;
    use std::{collections::HashMap, path::PathBuf, time::Duration};

    use super::*;
    use crate::checkpoint::{
        CheckpointConfig, CHECKPOINT_PARTITION_PREFIX, CHECKPOINT_TOPIC_PREFIX,
    };
    use crate::store::{
        DeduplicationStore, DeduplicationStoreConfig, TimestampKey, TimestampMetadata,
    };

    use common_types::RawEvent;
    use tempfile::TempDir;

    fn create_test_store(topic: &str, partition: i32) -> DeduplicationStore {
        let config = DeduplicationStoreConfig {
            path: TempDir::new().unwrap().path().to_path_buf(),
            max_capacity: 1_000_000,
        };
        DeduplicationStore::new(config.clone(), topic.to_string(), partition).unwrap()
    }

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: None,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("test_token".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        }
    }

    fn find_local_checkpoint_files(base_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut checkpoint_files = Vec::new();
        let mut stack = vec![base_dir.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_file() {
                    checkpoint_files.push(path);
                } else if path.is_dir() {
                    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                        if name.starts_with(CHECKPOINT_TOPIC_PREFIX)
                            || name.starts_with(CHECKPOINT_PARTITION_PREFIX)
                            || name.chars().filter(|c| c.is_ascii_digit()).count() == name.len()
                        {
                            stack.push(path);
                        }
                    }
                }
            }
        }

        Ok(checkpoint_files)
    }

    #[tokio::test]
    async fn test_worker_local_checkpoint_partition_full() {
        let store = create_test_store("some_test_topic", 0);

        // Add an event to the store
        let event = create_test_event();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata).unwrap();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // Create target partition and attempt path objects, run checkpoint worker
        let attempt_timestamp = Some(SystemTime::now());
        let partition = Partition::new("some_test_topic".to_string(), 0);
        let target = CheckpointTarget::new(
            partition.clone(),
            attempt_timestamp,
            Path::new(&config.local_checkpoint_dir),
        );

        // simulate how the manager's checkpoint loop thread constructs workers
        let worker = CheckpointWorker::new(1, target.clone(), None);

        let result = worker
            .checkpoint_partition(CheckpointMode::Full, &store)
            .await;
        assert!(result.is_ok(), "Checkpoint failed: {result:?}");

        let expected_checkpoint_path = target.local_attempt_path().unwrap();
        assert!(expected_checkpoint_path.exists());

        let checkpoint_files_found =
            find_local_checkpoint_files(&expected_checkpoint_path).unwrap();
        assert!(!checkpoint_files_found.is_empty());

        // there should be lots of checkpoint files collected from
        // various attempt directories of form /<base_path>/topic/partition/timestamp
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with("CURRENT")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("MANIFEST")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("OPTIONS")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".sst")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".log")));
    }

    // TODO: incremental mode is wired up but not implemented yet.
    // this test case exercises the config and staging logic
    // and smoke tests the local checkpoint behavior for now
    #[tokio::test]
    async fn test_worker_local_checkpoint_partition_incremental() {
        let store = create_test_store("some_test_topic", 0);

        // Add an event to the store
        let event = create_test_event();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata).unwrap();

        let partition = Partition::new("some_test_topic".to_string(), 0);
        let attempt_timestamp = Some(SystemTime::now());

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // Create partition path object for this attempt, run checkpoint worker
        let target = CheckpointTarget::new(
            partition.clone(),
            attempt_timestamp,
            Path::new(&config.local_checkpoint_dir),
        );

        // simulate how the manager's checkpoint loop thread constructs workers
        let worker = CheckpointWorker::new(1, target.clone(), None);

        let result = worker
            .checkpoint_partition(CheckpointMode::Incremental, &store)
            .await;
        assert!(result.is_ok(), "Checkpoint failed: {result:?}");

        let expected_checkpoint_path = target.local_attempt_path().unwrap();
        assert!(expected_checkpoint_path.exists());

        let checkpoint_files_found =
            find_local_checkpoint_files(&expected_checkpoint_path).unwrap();
        assert!(!checkpoint_files_found.is_empty());

        // there should be lots of checkpoint files collected from
        // various attempt directories of form /<base_path>/topic/partition/timestamp
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with("CURRENT")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("MANIFEST")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("OPTIONS")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".sst")));
        assert!(checkpoint_files_found
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".log")));
    }
}
