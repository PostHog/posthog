use anyhow::Result;
use async_trait::async_trait;
use std::path::Path;

/// Trait for downloading checkpoint data files from remote storage
#[async_trait]
pub trait CheckpointDownloader: Send + Sync + std::fmt::Debug {
    /// Download all files associated with a particular checkpoint attempt
    /// as scoped by s3_key_prefix into the local_base_path parent directory
    /// typically scoped by (topic, partition, attempt_timestamp) as during
    /// the attempts' original export
    async fn download_checkpoint(
        &self,
        s3_key_prefix: &str,
        local_base_path: &Path,
    ) -> Result<Vec<String>>;

    /// Download a metadata file from remote storage, and return the raw bytes
    /// for the higher-level CheckpointImporter to parse and hydrate. TBD whether
    /// it makes sense to store these in a local file when importing a checkpoint
    async fn download_metadata_file(&self, s3_file_key: &str) -> Result<Vec<u8>>;

    /// List remote paths to all checkpoint metadata files associated with a particular
    /// topic and partition, sorted by filename-embedded timestamp (newest first)
    async fn list_checkpoint_metadata(&self, s3_key_prefix: &str) -> Result<Vec<String>>;

    /// Check if a particular checkpoint attempt file set exists in remote storage
    /// based on the given s3 key prefix. Typically, s3_key_prefix will be derived
    /// from the CheckpointMetadata associated with a particular checkpoint attempt
    /// that was previously exported successfully
    async fn checkpoint_exists(&self, s3_key_prefix: &str) -> Result<bool>;

    /// Check if the downloader is available/configured
    async fn is_available(&self) -> bool;
}
