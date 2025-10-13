use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use super::CheckpointExporter;
use crate::kafka::types::Partition;
use crate::metrics_const::{
    CHECKPOINT_DURATION_HISTOGRAM, CHECKPOINT_FILE_COUNT_HISTOGRAM, CHECKPOINT_SIZE_HISTOGRAM,
    CHECKPOINT_WORKER_STATUS_COUNTER,
};
use crate::store::DeduplicationStore;

use anyhow::{Context, Result};
use metrics;
use tracing::{error, info, warn};

pub const CHECKPOINT_TOPIC_PREFIX: &str = "topic_";
pub const CHECKPOINT_PARTITION_PREFIX: &str = "part_";

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

/// encapsulates a single checkpoint attempt for a
/// given source topic and partition
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct CheckpointTarget {
    // source material (topic, partition, attempt timestamp in microseconds)
    pub partition: Partition,

    // local checkpoint path and observability tag
    pub local_path: PathBuf,
    pub local_path_tag: String,

    // remote storage checkpoint path
    pub remote_path: String,
}

impl CheckpointTarget {
    pub fn new(partition: Partition, local_checkpoint_base_dir: &Path) -> Result<Self> {
        let cp_epoch_micros_str = Self::format_checkpoint_timestamp(SystemTime::now())?;
        let cp_topic = format!("{}{}", CHECKPOINT_TOPIC_PREFIX, &partition.topic());
        let cp_partition = format!(
            "{}{}",
            CHECKPOINT_PARTITION_PREFIX,
            &partition.partition_number()
        );

        let remote_path = format!("{}/{}/{}", &cp_topic, &cp_partition, cp_epoch_micros_str);

        let local_path = PathBuf::from(local_checkpoint_base_dir)
            .join(cp_topic)
            .join(cp_partition)
            .join(cp_epoch_micros_str);
        let local_path_tag = local_path.to_string_lossy().to_string();

        Ok(Self {
            partition,
            local_path,
            local_path_tag,
            remote_path,
        })
    }

    // convert a SystemTime to a microsecond timestamp
    pub fn format_checkpoint_timestamp(st: SystemTime) -> Result<String> {
        Ok(format!(
            "{:020}",
            st.duration_since(UNIX_EPOCH)
                .context("failed to generate checkpoint timestamp")?
                .as_micros()
        ))
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
    ) -> Result<Option<String>> {
        info!(
            self.worker_id,
            local_path = self.target.local_path_tag,
            checkpoint_mode = mode.as_str(),
            "Checkpoint worker: initializing checkpoint"
        );

        // Ensure local checkpoint directory exists - results observed internally, safe to bubble up
        self.create_partition_checkpoint_directory(mode).await?;

        // this creates the local RocksDB checkpoint - results observed internally, safe to bubble up
        self.create_local_partition_checkpoint(mode, store).await?;

        // update store metrics - this can fail without blocking the checkpoint attempt
        if let Err(e) = store.update_metrics() {
            warn!(
                self.worker_id,
                local_path = self.target.local_path_tag,
                checkpoint_mode = mode.as_str(),
                "Checkpoint worker: failed store metrics update after local checkpoint: {}",
                e
            );
        }

        // export the checkpoint - observed internally, safe to return result
        self.export_checkpoint(mode).await
    }

    async fn create_partition_checkpoint_directory(&self, mode: CheckpointMode) -> Result<()> {
        // oddly, the RocksDB client likes to create the final directory in the
        // checkpoint path and will error if the parent dirs do not exist, or
        // full path exists ahead of the checkpoint attempt. Here, we only
        // create the directories above the final timestamp-based dir that
        // will house the checkpoint files
        let base_path = self
            .target
            .local_path
            .parent()
            .context("Checkpoint worker: failed to get parent directory")?;
        if let Err(e) = tokio::fs::create_dir_all(base_path).await {
            let tags = [
                ("mode", mode.as_str()),
                ("result", "error"),
                ("cause", "create_local_dir"),
            ];
            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
            error!(
                self.worker_id,
                local_path = self.target.local_path_tag,
                checkpoint_mode = mode.as_str(),
                "Checkpoint worker: failed to create local directory: {}",
                e
            );

            return Err(anyhow::anyhow!(e));
        }

        Ok(())
    }

    async fn create_local_partition_checkpoint(
        &self,
        mode: CheckpointMode,
        store: &DeduplicationStore,
    ) -> Result<()> {
        let start_time = Instant::now();

        // TODO: this should accept CheckpointMode argument to implement incremental local checkpoint step
        match store.create_checkpoint_with_metadata(&self.target.local_path) {
            Ok(sst_files) => {
                let checkpoint_duration = start_time.elapsed();
                metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
                    .record(checkpoint_duration.as_secs_f64());

                metrics::histogram!(CHECKPOINT_FILE_COUNT_HISTOGRAM).record(sst_files.len() as f64);
                if let Ok(checkpoint_size) = Self::get_directory_size(&self.target.local_path).await
                {
                    metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);
                }

                info!(
                    self.worker_id,
                    local_path = self.target.local_path_tag,
                    sst_file_count = sst_files.len(),
                    checkpoint_mode = mode.as_str(),
                    "Created local checkpoint",
                );

                Ok(())
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
                    local_path = self.target.local_path_tag,
                    checkpoint_mode = mode.as_str(),
                    "Local checkpoint failed: {}",
                    error_chain.join(" -> ")
                );

                Err(anyhow::anyhow!(error_chain.join(" -> ")))
            }
        }
    }

    async fn export_checkpoint(&self, mode: CheckpointMode) -> Result<Option<String>> {
        info!(
            self.worker_id,
            local_path = self.target.local_path_tag,
            checkpoint_mode = mode.as_str(),
            "Checkpoint worker: exporting remote checkpoint",
        );

        match self.exporter.as_ref() {
            Some(exporter) => {
                match exporter
                    .export_checkpoint(&self.target.local_path, &self.target.remote_path, mode)
                    .await
                {
                    Ok(remote_key_prefix) => {
                        let tags = [
                            ("mode", mode.as_str()),
                            ("result", "success"),
                            ("export", "success"),
                        ];
                        metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                        info!(
                            self.worker_id,
                            local_path = self.target.local_path_tag,
                            remote_path = remote_key_prefix,
                            checkpoint_mode = mode.as_str(),
                            "Checkpoint exported successfully"
                        );

                        Ok(Some(remote_key_prefix))
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
                            local_path = self.target.local_path_tag,
                            checkpoint_mode = mode.as_str(),
                            "Checkpoint failed to export: {}",
                            e
                        );

                        Err(e)
                    }
                }
            }

            None => {
                let tags = [
                    ("mode", mode.as_str()),
                    ("result", "success"),
                    ("export", "skipped"),
                ];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                warn!(
                    self.worker_id,
                    local_path = self.target.local_path_tag,
                    checkpoint_mode = mode.as_str(),
                    "Checkpoint upload skipped: no exporter configured",
                );

                Ok(None)
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
    use std::{collections::HashMap, path::PathBuf, time::Duration};

    use super::*;
    use crate::checkpoint::CheckpointConfig;
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
        let partition = Partition::new("some_test_topic".to_string(), 0);
        let target =
            CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir))
                .unwrap();

        // simulate how the manager's checkpoint loop thread constructs workers
        let worker = CheckpointWorker::new(1, target.clone(), None);

        let result = worker
            .checkpoint_partition(CheckpointMode::Full, &store)
            .await;
        assert!(result.is_ok());

        let expected_checkpoint_path = Path::new(&target.local_path);
        assert!(expected_checkpoint_path.exists());

        let checkpoint_files_found = find_local_checkpoint_files(expected_checkpoint_path).unwrap();
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

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // Create partition path object for this attempt, run checkpoint worker
        let target =
            CheckpointTarget::new(partition.clone(), Path::new(&config.local_checkpoint_dir))
                .unwrap();

        // simulate how the manager's checkpoint loop thread constructs workers
        let worker = CheckpointWorker::new(1, target.clone(), None);

        let result = worker
            .checkpoint_partition(CheckpointMode::Incremental, &store)
            .await;
        assert!(result.is_ok());

        let expected_checkpoint_path = Path::new(&target.local_path);
        assert!(expected_checkpoint_path.exists());

        let checkpoint_files_found = find_local_checkpoint_files(expected_checkpoint_path).unwrap();
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
