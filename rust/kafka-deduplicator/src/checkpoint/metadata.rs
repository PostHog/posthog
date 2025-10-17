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

/// Metadata about a checkpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointMetadata {
    /// Checkpoint ID (RFC3339-ish timestamp, e.g., "2025-10-14T16-00-05Z")
    pub id: String,
    /// Topic name
    pub topic: String,
    /// Partition number
    pub partition: i32,
    /// RocksDB sequence number at checkpoint time
    pub sequence: u64,
    /// Consumer offset at time of checkpoint
    pub consumer_offset: i64,
    /// Producer offset at time of checkpoint
    pub producer_offset: i64,
    /// Files with relative paths (can reference parent checkpoints)
    pub files: Vec<String>,
}

impl CheckpointMetadata {
    /// Create new checkpoint metadata with a given ID
    pub fn new(
        id: String,
        topic: String,
        partition: i32,
        sequence: u64,
        consumer_offset: i64,
        producer_offset: i64,
    ) -> Self {
        Self {
            id,
            topic,
            partition,
            sequence,
            consumer_offset,
            producer_offset,
            files: Vec::new(),
        }
    }

    /// Generate a checkpoint ID from the current timestamp
    pub fn generate_id() -> String {
        chrono::Utc::now().format("%Y-%m-%dT%H-%M-%SZ").to_string()
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

    /// Get S3 key prefix for this checkpoint (<topic>/<partition>/<id>/)
    pub fn get_s3_key_prefix(&self) -> String {
        format!("{}/{}/{}", self.topic, self.partition, self.id)
    }

    /// Get metadata filename
    pub fn get_metadata_filename(&self) -> String {
        "metadata.json".to_string()
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
        let id = "2025-10-14T16-00-05Z".to_string();
        let metadata =
            CheckpointMetadata::new(id.clone(), "test-topic".to_string(), 0, 1234567890, 100, 50);

        assert_eq!(metadata.id, id);
        assert_eq!(metadata.topic, "test-topic");
        assert_eq!(metadata.partition, 0);
        assert_eq!(metadata.sequence, 1234567890);
        assert_eq!(metadata.consumer_offset, 100);
        assert_eq!(metadata.producer_offset, 50);
        assert_eq!(metadata.files.len(), 0);
    }

    #[tokio::test]
    async fn test_add_files_to_metadata() {
        let mut metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-05Z".to_string(),
            "test-topic".to_string(),
            0,
            1234567890,
            100,
            50,
        );

        // Add files
        metadata.files.push("000001.sst".to_string());
        metadata
            .files
            .push("../2025-10-14T15-00-00Z/000002.sst".to_string());
        metadata.files.push("MANIFEST-000123".to_string());

        assert_eq!(metadata.files.len(), 3);
        assert_eq!(metadata.files[0], "000001.sst");
        assert_eq!(metadata.files[1], "../2025-10-14T15-00-00Z/000002.sst");
        assert_eq!(metadata.files[2], "MANIFEST-000123");
    }

    #[tokio::test]
    async fn test_save_and_load_metadata() {
        let temp_dir = TempDir::new().unwrap();
        let metadata_path = temp_dir.path().join("metadata.json");

        let mut metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-05Z".to_string(),
            "test-topic".to_string(),
            1,
            9876543210,
            200,
            150,
        );
        metadata.files.push("000001.sst".to_string());

        // Save metadata
        metadata.save_to_file(&metadata_path).await.unwrap();

        // Load metadata
        let loaded_metadata = CheckpointMetadata::load_from_file(&metadata_path)
            .await
            .unwrap();

        assert_eq!(loaded_metadata.id, metadata.id);
        assert_eq!(loaded_metadata.topic, metadata.topic);
        assert_eq!(loaded_metadata.partition, metadata.partition);
        assert_eq!(loaded_metadata.sequence, metadata.sequence);
        assert_eq!(loaded_metadata.consumer_offset, metadata.consumer_offset);
        assert_eq!(loaded_metadata.producer_offset, metadata.producer_offset);
        assert_eq!(loaded_metadata.files.len(), 1);
    }

    #[test]
    fn test_s3_key_prefix() {
        let metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-05Z".to_string(),
            "test-topic".to_string(),
            2,
            1234567890,
            100,
            50,
        );

        let prefix = metadata.get_s3_key_prefix();
        assert_eq!(prefix, "test-topic/2/2025-10-14T16-00-05Z");
    }

    #[test]
    fn test_checkpoint_info() {
        let metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-05Z".to_string(),
            "test-topic".to_string(),
            0,
            1234567890,
            100,
            50,
        );

        let info = CheckpointInfo::new(metadata.clone());

        assert_eq!(info.s3_key_prefix, metadata.get_s3_key_prefix());
        assert_eq!(
            info.get_metadata_key(),
            "test-topic/0/2025-10-14T16-00-05Z/metadata.json"
        );
        assert_eq!(
            info.get_file_key("000001.sst"),
            "test-topic/0/2025-10-14T16-00-05Z/000001.sst"
        );
    }

    #[test]
    fn test_metadata_filename() {
        let metadata = CheckpointMetadata::new(
            "2025-10-14T16-00-05Z".to_string(),
            "test".to_string(),
            0,
            1234567890,
            100,
            50,
        );

        assert_eq!(metadata.get_metadata_filename(), "metadata.json");
    }

    #[test]
    fn test_generate_id() {
        let id = CheckpointMetadata::generate_id();
        // Should be in format YYYY-MM-DDTHH-MM-SSZ
        assert!(id.contains('T'));
        assert!(id.ends_with('Z'));
        assert!(id.len() > 15); // Rough length check
    }
}
