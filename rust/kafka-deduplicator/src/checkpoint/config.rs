use std::time::Duration;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointConfig {
    /// How often to trigger a checkpoint
    pub checkpoint_interval: Duration,
    
    /// Base directory for local checkpoints
    pub local_checkpoint_dir: String,
    
    /// S3 bucket for checkpoint uploads
    pub s3_bucket: String,
    
    /// S3 key prefix for checkpoints
    pub s3_key_prefix: String,
    
    /// How many incremental checkpoints before doing a full upload
    pub full_upload_interval: u32,
    
    /// AWS region for S3
    pub aws_region: String,
    
    /// Maximum number of local checkpoints to keep
    pub max_local_checkpoints: usize,
    
    /// Timeout for S3 operations
    pub s3_timeout: Duration,
}

impl Default for CheckpointConfig {
    fn default() -> Self {
        Self {
            checkpoint_interval: Duration::from_secs(300), // 5 minutes
            local_checkpoint_dir: "./checkpoints".to_string(),
            s3_bucket: "".to_string(),
            s3_key_prefix: "deduplication-checkpoints".to_string(),
            full_upload_interval: 10, // Every 10 incremental checkpoints
            aws_region: "us-east-1".to_string(),
            max_local_checkpoints: 5,
            s3_timeout: Duration::from_secs(300), // 5 minutes
        }
    }
}