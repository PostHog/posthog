use anyhow::{Context, Result};
use std::path::PathBuf;
use tracing::{info, warn};

use super::client::CheckpointClient;
use super::metadata::CheckpointInfo;

/// Handles loading checkpoints from remote storage
#[derive(Debug)]
pub struct CheckpointLoader<C: CheckpointClient> {
    client: C,
    local_base_dir: String,
}

impl<C: CheckpointClient> CheckpointLoader<C> {
    pub fn new(client: C, local_base_dir: String) -> Self {
        Self {
            client,
            local_base_dir,
        }
    }

    /// Load the latest checkpoint for a partition
    /// Returns the loaded checkpoint info and local path, or None if no checkpoint exists
    pub async fn load_latest_checkpoint(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Option<(CheckpointInfo, PathBuf)>> {
        info!(
            "Loading latest checkpoint for topic {} partition {}",
            topic, partition
        );

        // List available checkpoints
        let checkpoint_infos = self
            .client
            .list_checkpoint_metadata(topic, partition)
            .await
            .context("Failed to list checkpoint metadata")?;

        if checkpoint_infos.is_empty() {
            info!(
                "No checkpoints found for topic {} partition {}",
                topic, partition
            );
            return Ok(None);
        }

        // Get the latest checkpoint (list is already sorted newest first)
        let latest_checkpoint = &checkpoint_infos[0];
        info!(
            "Found latest checkpoint: timestamp {}, type {:?}, {} files",
            latest_checkpoint.metadata.timestamp,
            latest_checkpoint.metadata.checkpoint_type,
            latest_checkpoint.metadata.files.len()
        );

        // Create local directory for this checkpoint
        let local_checkpoint_dir = PathBuf::from(&self.local_base_dir)
            .join(topic)
            .join(partition.to_string())
            .join(latest_checkpoint.metadata.timestamp.to_string());

        // Download the checkpoint
        self.client
            .download_checkpoint(latest_checkpoint, &local_checkpoint_dir)
            .await
            .context("Failed to download checkpoint")?;

        info!(
            "Successfully loaded checkpoint to {:?}",
            local_checkpoint_dir
        );

        Ok(Some((latest_checkpoint.clone(), local_checkpoint_dir)))
    }

    /// Load a specific checkpoint by timestamp
    pub async fn load_checkpoint_by_timestamp(
        &self,
        topic: &str,
        partition: i32,
        timestamp: u64,
    ) -> Result<Option<(CheckpointInfo, PathBuf)>> {
        info!(
            "Loading checkpoint for topic {} partition {} timestamp {}",
            topic, partition, timestamp
        );

        // List available checkpoints
        let checkpoint_infos = self
            .client
            .list_checkpoint_metadata(topic, partition)
            .await
            .context("Failed to list checkpoint metadata")?;

        // Find the specific checkpoint
        let target_checkpoint = checkpoint_infos
            .into_iter()
            .find(|cp| cp.metadata.timestamp == timestamp);

        let Some(checkpoint_info) = target_checkpoint else {
            warn!("Checkpoint not found for timestamp {}", timestamp);
            return Ok(None);
        };

        // Create local directory for this checkpoint
        let local_checkpoint_dir = PathBuf::from(&self.local_base_dir)
            .join(topic)
            .join(partition.to_string())
            .join(timestamp.to_string());

        // Download the checkpoint
        self.client
            .download_checkpoint(&checkpoint_info, &local_checkpoint_dir)
            .await
            .context("Failed to download checkpoint")?;

        info!(
            "Successfully loaded checkpoint timestamp {} to {:?}",
            timestamp, local_checkpoint_dir
        );

        Ok(Some((checkpoint_info, local_checkpoint_dir)))
    }

    /// Check if a checkpoint exists locally and is complete
    pub async fn is_checkpoint_complete(&self, checkpoint_info: &CheckpointInfo) -> Result<bool> {
        let local_checkpoint_dir = PathBuf::from(&self.local_base_dir)
            .join(&checkpoint_info.metadata.topic)
            .join(checkpoint_info.metadata.partition.to_string())
            .join(checkpoint_info.metadata.timestamp.to_string());

        // Check if metadata file exists
        let metadata_path = local_checkpoint_dir.join("metadata.json");
        if !metadata_path.exists() {
            return Ok(false);
        }

        // Check if all expected files exist
        for file in &checkpoint_info.metadata.files {
            let file_path = local_checkpoint_dir.join(&file.path);
            if !file_path.exists() {
                return Ok(false);
            }

            // Optionally verify file size
            let file_metadata = tokio::fs::metadata(&file_path)
                .await
                .context("Failed to get file metadata")?;

            if file_metadata.len() != file.size_bytes {
                warn!(
                    "File size mismatch for {}: expected {}, got {}",
                    file.path,
                    file.size_bytes,
                    file_metadata.len()
                );
                return Ok(false);
            }
        }

        Ok(true)
    }

    /// Get local checkpoint directory path for a checkpoint
    pub fn get_local_checkpoint_path(&self, checkpoint_info: &CheckpointInfo) -> PathBuf {
        PathBuf::from(&self.local_base_dir)
            .join(&checkpoint_info.metadata.topic)
            .join(checkpoint_info.metadata.partition.to_string())
            .join(checkpoint_info.metadata.timestamp.to_string())
    }

    /// List all available checkpoints for a topic/partition
    pub async fn list_available_checkpoints(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Vec<CheckpointInfo>> {
        self.client
            .list_checkpoint_metadata(topic, partition)
            .await
            .context("Failed to list checkpoint metadata")
    }

    /// Cleanup old local checkpoints, keeping only the specified count
    pub async fn cleanup_local_checkpoints(
        &self,
        topic: &str,
        partition: i32,
        keep_count: usize,
    ) -> Result<()> {
        let partition_dir = PathBuf::from(&self.local_base_dir)
            .join(topic)
            .join(partition.to_string());

        if !partition_dir.exists() {
            return Ok(());
        }

        // Read all checkpoint directories (they should be named by timestamp)
        let mut entries = tokio::fs::read_dir(&partition_dir)
            .await
            .context("Failed to read partition directory")?;

        let mut checkpoint_dirs = Vec::new();
        while let Some(entry) = entries.next_entry().await? {
            if entry.file_type().await?.is_dir() {
                if let Some(name) = entry.file_name().to_str() {
                    if let Ok(timestamp) = name.parse::<u64>() {
                        checkpoint_dirs.push((timestamp, entry.path()));
                    }
                }
            }
        }

        // Sort by timestamp (newest first)
        checkpoint_dirs.sort_by(|a, b| b.0.cmp(&a.0));

        // Remove old directories
        if checkpoint_dirs.len() > keep_count {
            let dirs_to_remove: Vec<_> = checkpoint_dirs.into_iter().skip(keep_count).collect();

            for (_timestamp, path) in dirs_to_remove {
                info!("Removing old local checkpoint: {:?}", path);
                if let Err(e) = tokio::fs::remove_dir_all(&path).await {
                    warn!("Failed to remove checkpoint directory {:?}: {}", path, e);
                }
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::checkpoint::metadata::{CheckpointMetadata, CheckpointType};
    use crate::kafka::types::Partition;
    use async_trait::async_trait;
    use std::collections::HashMap;
    use std::path::Path;
    use tempfile::TempDir;

    #[derive(Debug, Clone)]
    struct MockClient {
        checkpoints: HashMap<Partition, Vec<CheckpointInfo>>,
    }

    impl MockClient {
        fn new() -> Self {
            Self {
                checkpoints: HashMap::new(),
            }
        }

        fn add_checkpoint(&mut self, topic: &str, partition: i32, checkpoint: CheckpointInfo) {
            self.checkpoints
                .entry(Partition::new(topic.to_string(), partition))
                .or_default()
                .push(checkpoint);
        }
    }

    #[async_trait]
    impl CheckpointClient for MockClient {
        async fn list_checkpoint_metadata(
            &self,
            topic: &str,
            partition: i32,
        ) -> Result<Vec<CheckpointInfo>> {
            let mut checkpoints = self
                .checkpoints
                .get(&Partition::new(topic.to_string(), partition))
                .cloned()
                .unwrap_or_default();

            // Sort by timestamp (newest first)
            checkpoints.sort_by(|a, b| b.metadata.timestamp.cmp(&a.metadata.timestamp));
            Ok(checkpoints)
        }

        async fn download_checkpoint(
            &self,
            _checkpoint_info: &CheckpointInfo,
            local_path: &Path,
        ) -> Result<()> {
            tokio::fs::create_dir_all(local_path).await?;

            // Create a dummy metadata.json file
            let metadata_path = local_path.join("metadata.json");
            tokio::fs::write(&metadata_path, "{}").await?;

            Ok(())
        }

        async fn get_checkpoint_metadata(&self, _metadata_key: &str) -> Result<CheckpointMetadata> {
            Ok(CheckpointMetadata::new(
                CheckpointType::Full,
                "test".to_string(),
                0,
                100,
                50,
                1000,
            ))
        }

        async fn checkpoint_exists(&self, _checkpoint_info: &CheckpointInfo) -> Result<bool> {
            Ok(true)
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn test_load_latest_checkpoint() {
        let mut mock_client = MockClient::new();

        // Add some test checkpoints
        let checkpoint1 = CheckpointInfo {
            metadata: CheckpointMetadata {
                timestamp: 1000,
                topic: "test".to_string(),
                partition: 0,
                checkpoint_type: CheckpointType::Full,
                consumer_offset: 100,
                producer_offset: 50,
                files: vec![],
                previous_checkpoint: None,
                total_size_bytes: 0,
                key_count: 100,
            },
            s3_key_prefix: "test/0/1000".to_string(),
        };

        let checkpoint2 = CheckpointInfo {
            metadata: CheckpointMetadata {
                timestamp: 2000,
                topic: "test".to_string(),
                partition: 0,
                checkpoint_type: CheckpointType::Partial,
                consumer_offset: 200,
                producer_offset: 100,
                files: vec![],
                previous_checkpoint: Some(1000),
                total_size_bytes: 0,
                key_count: 200,
            },
            s3_key_prefix: "test/0/2000".to_string(),
        };

        mock_client.add_checkpoint("test", 0, checkpoint1);
        mock_client.add_checkpoint("test", 0, checkpoint2);

        let temp_dir = TempDir::new().unwrap();
        let loader =
            CheckpointLoader::new(mock_client, temp_dir.path().to_string_lossy().to_string());

        let result = loader.load_latest_checkpoint("test", 0).await.unwrap();
        assert!(result.is_some());

        let (checkpoint_info, local_path) = result.unwrap();
        assert_eq!(checkpoint_info.metadata.timestamp, 2000); // Should get the newest
        assert!(local_path.exists());
    }

    #[tokio::test]
    async fn test_no_checkpoints_available() {
        let mock_client = MockClient::new();
        let temp_dir = TempDir::new().unwrap();
        let loader =
            CheckpointLoader::new(mock_client, temp_dir.path().to_string_lossy().to_string());

        let result = loader
            .load_latest_checkpoint("nonexistent", 0)
            .await
            .unwrap();
        assert!(result.is_none());
    }
}
