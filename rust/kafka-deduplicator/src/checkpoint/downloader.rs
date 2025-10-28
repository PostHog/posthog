use anyhow::Result;
use async_trait::async_trait;
use std::path::Path;

/// Trait for downloading checkpoint data files from remote storage
#[async_trait]
pub trait CheckpointDownloader: Send + Sync + std::fmt::Debug {
    /// List the paths to the most recent checkpoint attempt metadata.json
    /// tracking files uploaded in remote storage, sorted newest to oldest
    async fn list_recent_checkpoints(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<Vec<String>>;

    /// Download a single file from remote storage and return the byte contents
    async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>>;

    // Download a single file from remote storage and store it in the given local file path.
    // The method assumes the local path parent directories were pre-created
    async fn download_and_store_file(&self, remote_key: &str, local_filepath: &Path) -> Result<()>;

    /// Given a list of fully-qualified remote file keys, download all
    /// files in parallel from remote storage and into the given local
    /// directory path, creating that base directory if it doesn't exist
    async fn download_files(&self, remote_keys: &[String], local_base_path: &Path) -> Result<()>;

    /// Check if the downloader is available and configured for use
    async fn is_available(&self) -> bool;
}
