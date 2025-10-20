use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;

use chrono::{DateTime, Utc};
use tracing::info;

pub const METADATA_FILENAME: &str = "metadata.json";
pub const TIMESTAMP_FORMAT: &str = "%Y-%m-%dT%H-%M-%SZ";

/// Metadata about a checkpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointMetadata {
    /// Checkpoint ID (RFC3339-ish timestamp, e.g., "2025-10-14T16-00-05Z")
    pub id: String,
    /// Topic name
    pub topic: String,
    /// Partition number
    pub partition: i32,
    /// Timestamp of this checkpoint's attempt
    pub attempt_timestamp: DateTime<Utc>,
    /// RocksDB sequence number at checkpoint time
    pub sequence: u64,
    /// Consumer offset at time of checkpoint
    pub consumer_offset: i64,
    /// Producer offset at time of checkpoint
    pub producer_offset: i64,
    /// Remote file path (minus app-level bucket namespace) to each file
    /// required to reconsitute a local RocksDB store across all relevant
    /// checkpoint attempts. A relative path of the form:
    /// <topic_name>/<partition_number>/<checkpoint_id>/<filename>
    pub files: Vec<String>,
}

impl CheckpointMetadata {
    /// Create new metadata representing a single checkpoint attempt
    pub fn new(
        topic: String,
        partition: i32,
        attempt_timestamp: DateTime<Utc>,
        sequence: u64,
        consumer_offset: i64,
        producer_offset: i64,
    ) -> Self {
        Self {
            id: CheckpointMetadata::generate_id(attempt_timestamp),
            topic,
            partition,
            attempt_timestamp,
            sequence,
            consumer_offset,
            producer_offset,
            files: Vec::new(),
        }
    }

    /// Generate a checkpoint ID from the current timestamp
    pub fn generate_id(attempt_timestamp: DateTime<Utc>) -> String {
        attempt_timestamp.format(TIMESTAMP_FORMAT).to_string()
    }

    /// Save metadata to a JSON file
    pub async fn save_to_file(&self, local_base_path: &Path) -> Result<()> {
        let json = self.to_json().context("In save_to_file")?;
        let metadata_file_path = local_base_path.join(self.get_metadata_filepath());

        if let Some(parent) = metadata_file_path.parent() {
            tokio::fs::create_dir_all(parent)
                .await
                .with_context(|| format!("Failed to create directory: {parent:?}"))?;
        }

        tokio::fs::write(&metadata_file_path, json)
            .await
            .with_context(|| format!("Failed to write metadata to file: {metadata_file_path:?}"))?;

        info!("Saved checkpoint metadata file to {:?}", metadata_file_path);
        Ok(())
    }

    /// Load metadata from a JSON file
    pub async fn load_from_file(path: &Path) -> Result<Self> {
        let json = tokio::fs::read_to_string(path).await?;
        let metadata: Self = serde_json::from_str(&json)?;
        Ok(metadata)
    }

    /// Generate attempt-scoped path elements for this checkpoint, not including
    /// app-level bucket namespace or local base path. Result is of the form:
    /// <topic_name>/<partition_number>/<checkpoint_id>
    pub fn get_attempt_path(&self) -> String {
        format!("{}/{}/{}", self.topic, self.partition, self.id)
    }

    /// Get relative path to metadata file for this checkpoint attempt,
    /// not including remote bucket namespace or local base path
    pub fn get_metadata_filepath(&self) -> String {
        format!("{}/{}", self.get_attempt_path(), METADATA_FILENAME)
    }

    pub fn to_json(&self) -> Result<String> {
        serde_json::to_string_pretty(self).context("Failed to serialize checkpoint metadata")
    }
}

/// Information about a checkpoint stored in S3
#[derive(Debug, Clone)]
pub struct CheckpointInfo {
    /// Checkpoint metadata
    pub metadata: CheckpointMetadata,
    /// App-level S3 bucket namespace under which all checkpoint attempts are stored remotely
    pub s3_key_prefix: String,
}

impl CheckpointInfo {
    /// Create new checkpoint info that wraps in the app-level bucket
    /// namespace under which all checkpoint attempts are stored remotely
    pub fn new(metadata: CheckpointMetadata, s3_key_prefix: String) -> Self {
        Self {
            metadata,
            s3_key_prefix,
        }
    }

    /// Get the fully-qualified remote metadata file path for this checkpoint attempt
    pub fn get_metadata_key(&self) -> String {
        format!(
            "{}/{}",
            self.s3_key_prefix,
            self.metadata.get_metadata_filepath()
        )
    }

    /// Get fully-qualified remote file path for a specific file
    /// to be uploaded as part of this checkpoint attempt. the
    /// relative_file_path is assumed to have been stripped of all
    /// local path elements common to a checkpoint attempt dir tree
    ///
    /// NOTE! Files tracked in metadata.files that were not uploaded
    /// as part of this attempt already contain their fully-qualified
    /// remote paths as of time of original upload attempt, and can be
    /// used directly in import/DR flows.
    pub fn get_file_key(&self, relative_file_path: &str) -> String {
        format!("{}/{}", self.get_remote_attempt_path(), relative_file_path)
    }

    // The fully qualified remote base path for this checkpoint attempt
    pub fn get_remote_attempt_path(&self) -> String {
        format!(
            "{}/{}",
            self.s3_key_prefix,
            self.metadata.get_attempt_path(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_checkpoint_metadata_creation() {
        let attempt_timestamp = Utc::now();
        let metadata = CheckpointMetadata::new(
            "test-topic".to_string(),
            0,
            attempt_timestamp,
            1234567890,
            100,
            50,
        );

        assert_eq!(
            metadata.id,
            CheckpointMetadata::generate_id(attempt_timestamp)
        );
        assert_eq!(metadata.topic, "test-topic");
        assert_eq!(metadata.partition, 0);
        assert_eq!(metadata.sequence, 1234567890);
        assert_eq!(metadata.consumer_offset, 100);
        assert_eq!(metadata.producer_offset, 50);
        assert_eq!(metadata.files.len(), 0);
    }

    #[tokio::test]
    async fn test_add_files_to_metadata() {
        let remote_namespace = "checkpoints";
        let attempt_timestamp = Utc::now();

        let mut metadata = CheckpointMetadata::new(
            "test-topic".to_string(),
            0,
            attempt_timestamp,
            1234567890,
            100,
            50,
        );

        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let remote_base_path = format!(
            "{}/{}/{}/{}",
            remote_namespace, metadata.topic, metadata.partition, checkpoint_id,
        );

        // Add files - assume planner has already resolved full S3 remote paths
        metadata
            .files
            .push(format!("{remote_base_path}/000001.sst"));
        metadata
            .files
            .push(format!("{remote_base_path}/000002.sst"));
        metadata
            .files
            .push(format!("{remote_base_path}/MANIFEST-000123"));

        assert_eq!(metadata.files.len(), 3);
        assert_eq!(
            metadata.files[0],
            format!("checkpoints/test-topic/0/{checkpoint_id}/000001.sst")
        );
        assert_eq!(
            metadata.files[1],
            format!("checkpoints/test-topic/0/{checkpoint_id}/000002.sst")
        );
        assert_eq!(
            metadata.files[2],
            format!("checkpoints/test-topic/0/{checkpoint_id}/MANIFEST-000123")
        );
    }

    #[tokio::test]
    async fn test_save_and_load_metadata() {
        let local_base_path = TempDir::new().unwrap();

        let bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition = "1";
        let attempt_timestamp = Utc::now();
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata_file_path = local_base_path
            .path()
            .join(topic)
            .join(partition)
            .join(&checkpoint_id)
            .join(METADATA_FILENAME);

        let mut metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition.parse::<i32>().unwrap(),
            attempt_timestamp,
            9876543210,
            200,
            150,
        );
        // simulate what planner will do to format remote path for upload
        // files retained from a planner diff will retained and remote path already fully qualified
        metadata.files.push(format!(
            "{}/{}/000001.sst",
            bucket_namespace,
            metadata.get_attempt_path()
        ));

        // Save metadata
        metadata.save_to_file(local_base_path.path()).await.unwrap();

        // Load metadata
        let loaded_metadata = CheckpointMetadata::load_from_file(&metadata_file_path)
            .await
            .unwrap();

        assert_eq!(loaded_metadata.id, metadata.id);
        assert_eq!(loaded_metadata.topic, metadata.topic);
        assert_eq!(loaded_metadata.partition, metadata.partition);
        assert_eq!(
            loaded_metadata.attempt_timestamp,
            metadata.attempt_timestamp
        );
        assert_eq!(loaded_metadata.sequence, metadata.sequence);
        assert_eq!(loaded_metadata.consumer_offset, metadata.consumer_offset);
        assert_eq!(loaded_metadata.producer_offset, metadata.producer_offset);

        let expected_remote_file_path =
            format!("{bucket_namespace}/{topic}/{partition}/{checkpoint_id}/000001.sst");
        assert_eq!(loaded_metadata.files.len(), 1);
        assert_eq!(loaded_metadata.files[0], expected_remote_file_path);
    }

    #[test]
    fn test_get_attempt_path() {
        let attempt_timestamp = Utc::now();
        let topic = "test-topic";
        let partition = 0;
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);

        let metadata = CheckpointMetadata::new(
            "test-topic".to_string(),
            0,
            attempt_timestamp,
            1234567890,
            100,
            50,
        );

        let prefix = metadata.get_attempt_path();
        let expected_attempt_path = format!("{topic}/{partition}/{checkpoint_id}");
        assert_eq!(prefix, expected_attempt_path);
    }

    #[test]
    fn test_checkpoint_info() {
        let attempt_timestamp = Utc::now();
        let bucket_namespace = "checkpoints";
        let topic = "test-topic";
        let partition = 0;
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition,
            attempt_timestamp,
            1234567890,
            100,
            50,
        );

        let info = CheckpointInfo::new(metadata.clone(), bucket_namespace.to_string());

        assert_eq!(
            info.get_metadata_key(),
            format!("{bucket_namespace}/{topic}/{partition}/{checkpoint_id}/{METADATA_FILENAME}")
        );

        // turns checkpoint filename into a fully qualified remote file path
        // for tracking in metadata.files and for upload during this attempt
        let local_file_relative_path = "000001.sst";
        assert_eq!(
            info.get_file_key(local_file_relative_path),
            format!("{bucket_namespace}/{topic}/{partition}/{checkpoint_id}/000001.sst")
        );
    }

    #[test]
    fn test_metadata_filename() {
        let attempt_timestamp = Utc::now();
        let topic = "test-topic";
        let partition = 0;
        let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
        let metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition,
            attempt_timestamp,
            1234567890,
            100,
            50,
        );

        let expected_metadata_filepath =
            format!("{topic}/{partition}/{checkpoint_id}/{METADATA_FILENAME}");
        assert_eq!(metadata.get_metadata_filepath(), expected_metadata_filepath);
    }

    #[test]
    fn test_generate_id() {
        let attempt_timestamp = Utc::now();
        let id = CheckpointMetadata::generate_id(attempt_timestamp);
        let expected_id = attempt_timestamp.format(TIMESTAMP_FORMAT).to_string();

        // Should be in format YYYY-MM-DDTHH-MM-SSZ
        assert!(id.contains('T'));
        assert!(id.ends_with('Z'));
        assert!(id.len() > 15); // Rough length check
        assert_eq!(id, expected_id);
    }
}
