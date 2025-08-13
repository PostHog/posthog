use serde::{Deserialize, Serialize};

/// Type of checkpoint - full contains all data, partial contains incremental changes
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum CheckpointType {
    Full,
    Partial,
}

/// Metadata for a checkpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointMetadata {
    /// Type of checkpoint (full or partial)
    pub checkpoint_type: CheckpointType,

    /// Timestamp when the checkpoint was created
    pub timestamp: u64,

    /// Topic this checkpoint belongs to
    pub topic: String,

    /// Partition this checkpoint belongs to
    pub partition: i32,

    /// Consumer offset at the time of checkpoint
    pub consumer_offset: i64,

    /// Producer topic partition offset for output topic
    pub producer_offset: i64,

    /// List of files that belong to this checkpoint
    /// Includes files from previous checkpoints if this is a partial checkpoint
    pub files: Vec<CheckpointFile>,

    /// Previous checkpoint timestamp (if this is a partial checkpoint)
    pub previous_checkpoint: Option<u64>,

    /// Total size of all files in bytes
    pub total_size_bytes: u64,

    /// Number of keys in the deduplication store at checkpoint time
    pub key_count: u64,
}

/// Information about a file in a checkpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointFile {
    /// Relative path of the file within the checkpoint
    pub path: String,

    /// Size of the file in bytes
    pub size_bytes: u64,

    /// Whether this file is new in this checkpoint or inherited from previous
    pub is_new: bool,

    /// Checksum/hash of the file for integrity verification
    pub checksum: Option<String>,
}

impl CheckpointMetadata {
    /// Create a new checkpoint metadata
    pub fn new(
        checkpoint_type: CheckpointType,
        topic: String,
        partition: i32,
        consumer_offset: i64,
        producer_offset: i64,
        key_count: u64,
    ) -> Self {
        Self {
            checkpoint_type,
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs(),
            topic,
            partition,
            consumer_offset,
            producer_offset,
            files: Vec::new(),
            previous_checkpoint: None,
            total_size_bytes: 0,
            key_count,
        }
    }

    /// Add a file to the checkpoint
    pub fn add_file(
        &mut self,
        path: String,
        size_bytes: u64,
        is_new: bool,
        checksum: Option<String>,
    ) {
        self.files.push(CheckpointFile {
            path,
            size_bytes,
            is_new,
            checksum,
        });
        self.total_size_bytes += size_bytes;
    }

    /// Generate S3 key for this checkpoint using the new format: topic/{partition}/{timestamp}/
    pub fn s3_key_prefix(&self, base_prefix: &str) -> String {
        format!(
            "{}/{}/{}/{}",
            base_prefix, self.topic, self.partition, self.timestamp
        )
    }

    /// Generate S3 key for the metadata file
    pub fn metadata_s3_key(&self, base_prefix: &str) -> String {
        format!("{}/metadata.json", self.s3_key_prefix(base_prefix))
    }

    /// Generate local checkpoint directory path
    pub fn local_checkpoint_dir(&self, base_dir: &str) -> String {
        format!(
            "{}/{}/{}/{}",
            base_dir, self.topic, self.partition, self.timestamp
        )
    }

    /// Serialize metadata to JSON
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string_pretty(self)
    }

    /// Deserialize metadata from JSON
    pub fn from_json(json: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(json)
    }
}

/// Helper for listing and finding checkpoints
#[derive(Debug, Clone)]
pub struct CheckpointInfo {
    pub metadata: CheckpointMetadata,
    pub s3_key_prefix: String,
}

impl CheckpointInfo {
    /// Parse S3 key to extract checkpoint information
    /// Expected format: base_prefix/topic/partition/timestamp/
    pub fn parse_s3_key(s3_key: &str, base_prefix: &str) -> Option<(String, i32, u64)> {
        let prefix_len = base_prefix.len() + 1; // +1 for trailing slash
        if s3_key.len() <= prefix_len {
            return None;
        }

        let remainder = &s3_key[prefix_len..];
        let parts: Vec<&str> = remainder.split('/').collect();

        if parts.len() >= 3 {
            let topic = parts[0].to_string();
            let partition = parts[1].parse::<i32>().ok()?;
            let timestamp = parts[2].parse::<u64>().ok()?;
            Some((topic, partition, timestamp))
        } else {
            None
        }
    }

    /// Get the latest checkpoint for a given topic and partition
    pub fn find_latest_checkpoint(
        checkpoints: Vec<CheckpointInfo>,
        topic: &str,
        partition: i32,
    ) -> Option<CheckpointInfo> {
        checkpoints
            .into_iter()
            .filter(|cp| cp.metadata.topic == topic && cp.metadata.partition == partition)
            .max_by_key(|cp| cp.metadata.timestamp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_checkpoint_metadata_creation() {
        let metadata = CheckpointMetadata::new(
            CheckpointType::Full,
            "test-topic".to_string(),
            0,
            1000,
            500,
            12345,
        );

        assert_eq!(metadata.checkpoint_type, CheckpointType::Full);
        assert_eq!(metadata.topic, "test-topic");
        assert_eq!(metadata.partition, 0);
        assert_eq!(metadata.consumer_offset, 1000);
        assert_eq!(metadata.producer_offset, 500);
        assert_eq!(metadata.key_count, 12345);
        assert!(metadata.files.is_empty());
        assert_eq!(metadata.total_size_bytes, 0);
    }

    #[test]
    fn test_s3_key_generation() {
        let mut metadata = CheckpointMetadata::new(
            CheckpointType::Partial,
            "events".to_string(),
            2,
            2000,
            1000,
            67890,
        );
        metadata.timestamp = 1640995200; // Fixed timestamp for testing

        let base_prefix = "dedup-checkpoints";
        let expected_prefix = "dedup-checkpoints/events/2/1640995200";
        let expected_metadata_key = "dedup-checkpoints/events/2/1640995200/metadata.json";

        assert_eq!(metadata.s3_key_prefix(base_prefix), expected_prefix);
        assert_eq!(metadata.metadata_s3_key(base_prefix), expected_metadata_key);
    }

    #[test]
    fn test_add_files() {
        let mut metadata =
            CheckpointMetadata::new(CheckpointType::Full, "test".to_string(), 0, 100, 50, 1000);

        metadata.add_file(
            "file1.sst".to_string(),
            1024,
            true,
            Some("hash1".to_string()),
        );
        metadata.add_file(
            "file2.sst".to_string(),
            2048,
            false,
            Some("hash2".to_string()),
        );

        assert_eq!(metadata.files.len(), 2);
        assert_eq!(metadata.total_size_bytes, 3072);
        assert_eq!(metadata.files[0].path, "file1.sst");
        assert!(metadata.files[0].is_new);
        assert_eq!(metadata.files[1].path, "file2.sst");
        assert!(!metadata.files[1].is_new);
    }

    #[test]
    fn test_json_serialization() {
        let mut metadata =
            CheckpointMetadata::new(CheckpointType::Full, "test".to_string(), 0, 100, 50, 1000);
        metadata.add_file("test.sst".to_string(), 1024, true, None);

        let json = metadata.to_json().unwrap();
        let deserialized = CheckpointMetadata::from_json(&json).unwrap();

        assert_eq!(metadata.checkpoint_type, deserialized.checkpoint_type);
        assert_eq!(metadata.topic, deserialized.topic);
        assert_eq!(metadata.files.len(), deserialized.files.len());
    }

    #[test]
    fn test_s3_key_parsing() {
        let base_prefix = "checkpoints";
        let s3_key = "checkpoints/events/0/1640995200/metadata.json";

        let parsed = CheckpointInfo::parse_s3_key(s3_key, base_prefix);
        assert_eq!(parsed, Some(("events".to_string(), 0, 1640995200)));

        // Test invalid formats
        assert_eq!(CheckpointInfo::parse_s3_key("invalid", base_prefix), None);
        assert_eq!(
            CheckpointInfo::parse_s3_key("checkpoints/", base_prefix),
            None
        );
        assert_eq!(
            CheckpointInfo::parse_s3_key("checkpoints/topic", base_prefix),
            None
        );
    }

    #[test]
    fn test_find_latest_checkpoint() {
        let checkpoints = vec![
            CheckpointInfo {
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
            },
            CheckpointInfo {
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
            },
        ];

        let latest = CheckpointInfo::find_latest_checkpoint(checkpoints, "test", 0);
        assert!(latest.is_some());
        assert_eq!(latest.unwrap().metadata.timestamp, 2000);
    }
}
