use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;
use tracing::info;

/// Type of checkpoint
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum CheckpointType {
    /// Full checkpoint containing all current state
    Full,
    /// Partial checkpoint containing only changes since last checkpoint
    Partial,
}

/// Information about a checkpoint file
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointFile {
    /// Path relative to checkpoint root
    pub path: String,
    /// Size of file in bytes
    pub size_bytes: u64,
    /// SHA256 hash of file contents
    pub checksum: Option<String>,
}

/// Metadata about a checkpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointMetadata {
    /// Unix timestamp when checkpoint was created
    pub timestamp: u64,
    /// Topic name
    pub topic: String,
    /// Partition number
    pub partition: i32,
    /// Type of checkpoint
    pub checkpoint_type: CheckpointType,
    /// Consumer offset at time of checkpoint
    pub consumer_offset: i64,
    /// Producer offset at time of checkpoint
    pub producer_offset: i64,
    /// List of files in this checkpoint
    pub files: Vec<CheckpointFile>,
    /// Timestamp of previous checkpoint if this is a partial checkpoint
    pub previous_checkpoint: Option<u64>,
    /// Total size of all files in bytes
    pub total_size_bytes: u64,
    /// Number of keys in the checkpoint
    pub key_count: u64,
}

impl CheckpointMetadata {
    /// Create new checkpoint metadata
    pub fn new(
        checkpoint_type: CheckpointType,
        topic: String,
        partition: i32,
        consumer_offset: i64,
        producer_offset: i64,
        key_count: u64,
    ) -> Self {
        Self {
            timestamp: chrono::Utc::now().timestamp() as u64,
            topic,
            partition,
            checkpoint_type,
            consumer_offset,
            producer_offset,
            files: Vec::new(),
            previous_checkpoint: None,
            total_size_bytes: 0,
            key_count,
        }
    }

    /// Add a file to the checkpoint metadata
    pub fn add_file(&mut self, path: String, size_bytes: u64, checksum: Option<String>) {
        self.total_size_bytes += size_bytes;
        self.files.push(CheckpointFile {
            path,
            size_bytes,
            checksum,
        });
    }

    /// Save metadata to a JSON file
    pub async fn save_to_file(&self, path: &Path) -> Result<()> {
        let json = serde_json::to_string_pretty(self)?;
        tokio::fs::write(path, json).await?;
        info!("Saved checkpoint metadata to {:?}", path);
        Ok(())
    }

    /// Load metadata from a JSON file
    pub async fn load_from_file(path: &Path) -> Result<Self> {
        let json = tokio::fs::read_to_string(path).await?;
        let metadata: Self = serde_json::from_str(&json)?;
        Ok(metadata)
    }

    /// Get S3 key prefix for this checkpoint
    pub fn get_s3_key_prefix(&self) -> String {
        format!("{}/{}/{}", self.topic, self.partition, self.timestamp)
    }

    /// Get metadata filename
    pub fn get_metadata_filename(&self) -> String {
        format!("metadata-{}.json", self.timestamp)
    }
}

/// Information about a checkpoint stored in S3
#[derive(Debug, Clone)]
pub struct CheckpointInfo {
    /// Checkpoint metadata
    pub metadata: CheckpointMetadata,
    /// S3 key prefix for this checkpoint
    pub s3_key_prefix: String,
}

impl CheckpointInfo {
    /// Create new checkpoint info
    pub fn new(metadata: CheckpointMetadata) -> Self {
        let s3_key_prefix = metadata.get_s3_key_prefix();
        Self {
            metadata,
            s3_key_prefix,
        }
    }

    /// Get the metadata S3 key for this checkpoint
    pub fn get_metadata_key(&self) -> String {
        format!("{}/metadata.json", self.s3_key_prefix)
    }

    /// Get S3 key for a specific file in this checkpoint
    pub fn get_file_key(&self, file_path: &str) -> String {
        format!("{}/{}", self.s3_key_prefix, file_path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_checkpoint_metadata_creation() {
        let metadata = CheckpointMetadata::new(
            CheckpointType::Full,
            "test-topic".to_string(),
            0,
            100,
            50,
            1000,
        );

        assert_eq!(metadata.topic, "test-topic");
        assert_eq!(metadata.partition, 0);
        assert_eq!(metadata.checkpoint_type, CheckpointType::Full);
        assert_eq!(metadata.consumer_offset, 100);
        assert_eq!(metadata.producer_offset, 50);
        assert_eq!(metadata.key_count, 1000);
        assert_eq!(metadata.files.len(), 0);
        assert_eq!(metadata.total_size_bytes, 0);
    }

    #[tokio::test]
    async fn test_add_file_to_metadata() {
        let mut metadata = CheckpointMetadata::new(
            CheckpointType::Full,
            "test-topic".to_string(),
            0,
            100,
            50,
            1000,
        );

        metadata.add_file("sst/000001.sst".to_string(), 1024, None);
        metadata.add_file(
            "sst/000002.sst".to_string(),
            2048,
            Some("abcd1234".to_string()),
        );

        assert_eq!(metadata.files.len(), 2);
        assert_eq!(metadata.total_size_bytes, 3072);
        assert_eq!(metadata.files[0].path, "sst/000001.sst");
        assert_eq!(metadata.files[0].size_bytes, 1024);
        assert!(metadata.files[0].checksum.is_none());
        assert_eq!(metadata.files[1].checksum, Some("abcd1234".to_string()));
    }

    #[tokio::test]
    async fn test_save_and_load_metadata() {
        let temp_dir = TempDir::new().unwrap();
        let metadata_path = temp_dir.path().join("metadata.json");

        let mut metadata = CheckpointMetadata::new(
            CheckpointType::Partial,
            "test-topic".to_string(),
            1,
            200,
            150,
            2000,
        );
        metadata.previous_checkpoint = Some(1000);
        metadata.add_file("sst/000001.sst".to_string(), 1024, None);

        // Save metadata
        metadata.save_to_file(&metadata_path).await.unwrap();

        // Load metadata
        let loaded_metadata = CheckpointMetadata::load_from_file(&metadata_path)
            .await
            .unwrap();

        assert_eq!(loaded_metadata.topic, metadata.topic);
        assert_eq!(loaded_metadata.partition, metadata.partition);
        assert_eq!(loaded_metadata.checkpoint_type, CheckpointType::Partial);
        assert_eq!(loaded_metadata.consumer_offset, metadata.consumer_offset);
        assert_eq!(loaded_metadata.producer_offset, metadata.producer_offset);
        assert_eq!(loaded_metadata.key_count, metadata.key_count);
        assert_eq!(loaded_metadata.files.len(), 1);
        assert_eq!(loaded_metadata.previous_checkpoint, Some(1000));
    }

    #[test]
    fn test_s3_key_prefix() {
        let metadata = CheckpointMetadata::new(
            CheckpointType::Full,
            "test-topic".to_string(),
            2,
            100,
            50,
            1000,
        );

        let prefix = metadata.get_s3_key_prefix();
        assert!(prefix.starts_with("test-topic/2/"));
        assert!(prefix.split('/').count() == 3);
    }

    #[test]
    fn test_checkpoint_info() {
        let metadata = CheckpointMetadata::new(
            CheckpointType::Full,
            "test-topic".to_string(),
            0,
            100,
            50,
            1000,
        );

        let info = CheckpointInfo::new(metadata.clone());

        assert_eq!(info.s3_key_prefix, metadata.get_s3_key_prefix());
        assert!(info.get_metadata_key().ends_with("/metadata.json"));
        assert_eq!(
            info.get_file_key("sst/000001.sst"),
            format!("{}/sst/000001.sst", info.s3_key_prefix)
        );
    }

    #[test]
    fn test_metadata_filename() {
        let metadata = CheckpointMetadata {
            timestamp: 1234567890,
            topic: "test".to_string(),
            partition: 0,
            checkpoint_type: CheckpointType::Full,
            consumer_offset: 100,
            producer_offset: 50,
            files: vec![],
            previous_checkpoint: None,
            total_size_bytes: 0,
            key_count: 0,
        };

        assert_eq!(metadata.get_metadata_filename(), "metadata-1234567890.json");
    }
}
