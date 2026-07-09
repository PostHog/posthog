use anyhow::Result;
use async_trait::async_trait;
use std::path::Path;
use tokio_util::sync::CancellationToken;

#[async_trait]
pub trait CheckpointDownloader: Send + Sync + std::fmt::Debug {
    /// List remote checkpoint-attempt metadata.json keys, sorted newest to oldest.
    async fn list_recent_checkpoints(&self) -> Result<Vec<String>>;

    /// Download a single remote file and return its bytes.
    async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>>;

    /// Download a single file and write it to `local_filepath`. Parent dirs must already exist.
    async fn download_and_store_file(&self, remote_key: &str, local_filepath: &Path) -> Result<()> {
        self.download_and_store_file_cancellable(remote_key, local_filepath, None)
            .await
    }

    /// Download and store a single file with optional cancellation. Cleans up any partial file on
    /// cancellation.
    async fn download_and_store_file_cancellable(
        &self,
        remote_key: &str,
        local_filepath: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()>;

    /// Download all files in parallel into `local_base_path`. Caller must create the directory.
    async fn download_files(&self, remote_keys: &[String], local_base_path: &Path) -> Result<()> {
        self.download_files_cancellable(remote_keys, local_base_path, None)
            .await
    }

    async fn download_files_cancellable(
        &self,
        remote_keys: &[String],
        local_base_path: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()>;

    async fn is_available(&self) -> bool;
}
