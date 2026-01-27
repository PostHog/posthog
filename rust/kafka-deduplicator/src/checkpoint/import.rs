use std::path::{Path, PathBuf};

use super::{CheckpointDownloader, CheckpointMetadata};

use anyhow::{Context, Result};
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
    // Base path for local RocksDB stores - checkpoint files are downloaded directly here
    store_base_path: PathBuf,
    // Number of historical checkpoint attempts to import as fallbacks
    import_attempt_depth: usize,
}

impl CheckpointImporter {
    pub fn new(
        downloader: Box<dyn CheckpointDownloader>,
        store_base_path: PathBuf,
        import_attempt_depth: usize,
    ) -> Self {
        Self {
            downloader,
            store_base_path,
            import_attempt_depth,
        }
    }

    /// Import checkpoint files directly into the store directory for a topic/partition.
    ///
    /// This method will:
    /// 1. Fetch checkpoint metadata.json files from the most recent N checkpoints for the topic+partition
    /// 2. For each metadata file (newest to oldest), attempt to download all tracked files directly
    ///    to the store directory: `<store_base_path>/<topic>/<partition>/`
    /// 3. If a checkpoint import fails, fall back to the next most recent (up to import_attempt_depth)
    /// 4. If successful, return the store path where files were imported
    pub async fn import_checkpoint_for_topic_partition(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<PathBuf> {
        self.import_checkpoint_for_topic_partition_cancellable(topic, partition_number, None)
            .await
    }

    /// Import checkpoint files with optional cancellation support.
    /// If cancel_token is provided and cancelled during download, returns an error early.
    pub async fn import_checkpoint_for_topic_partition_cancellable(
        &self,
        topic: &str,
        partition_number: i32,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<PathBuf> {
        let mut checkpoint_metadata = self
            .fetch_checkpoint_metadata(topic, partition_number)
            .await?;

        info!(
            "Found {} checkpoint attempts for topic:{} partition:{}",
            checkpoint_metadata.len(),
            topic,
            partition_number
        );

        // Slice to at most the most-recent N checkpoints
        // we'll attempt to import according to import_limit
        checkpoint_metadata.truncate(self.import_attempt_depth);
        info!("Attempting recovery from the most recent {} checkpoints for topic:{topic} partition:{partition_number}",
            checkpoint_metadata.len());

        // checkpoints iterated in order of recency; we keep the first good one we fetch
        for attempt in checkpoint_metadata {
            // Check cancellation before each attempt
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    warn!(
                        topic = topic,
                        partition = partition_number,
                        "Checkpoint import cancelled before attempt"
                    );
                    return Err(anyhow::anyhow!("Checkpoint import cancelled"));
                }
            }

            let local_attempt_path = attempt.get_store_path(&self.store_base_path);
            let local_path_tag = local_attempt_path.to_string_lossy().to_string();
            let attempt_tag = attempt.get_attempt_path();

            // Defensive cleanup: remove any existing directory from a previous failed attempt.
            // Since the path is deterministic (based on checkpoint timestamp), a crash loop
            // could leave corrupted partial downloads that would break the retry.
            // We call remove unconditionally and ignore NotFound to avoid TOCTOU races.
            match tokio::fs::remove_dir_all(&local_attempt_path).await {
                Ok(_) => info!(
                    checkpoint = attempt_tag,
                    local_attempt_path = local_path_tag,
                    "Removed existing directory before checkpoint import"
                ),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(e) => {
                    return Err(e).with_context(|| {
                        format!(
                            "Failed to remove existing directory before import: {}",
                            local_path_tag
                        )
                    })
                }
            }

            // Create the directory for this import attempt
            tokio::fs::create_dir_all(&local_attempt_path)
                .await
                .with_context(|| {
                    format!(
                        "Failed to create local directory for import: {}",
                        local_path_tag
                    )
                })?;

            match self
                .fetch_checkpoint_files_cancellable(&attempt, &local_attempt_path, cancel_token)
                .await
            {
                Ok(_) => {
                    info!(
                        checkpoint = attempt_tag,
                        local_attempt_path = local_path_tag,
                        "Successfully imported checkpoint to local directory"
                    );
                    return Ok(local_attempt_path);
                }
                Err(e) => {
                    error!(
                        checkpoint = attempt_tag,
                        local_attempt_path = local_path_tag,
                        error = e.to_string(),
                        "Failed to import checkpoint files"
                    );
                    if local_attempt_path.exists() {
                        match tokio::fs::remove_dir_all(&local_attempt_path).await {
                            Ok(_) => {
                                info!(
                                    checkpoint = attempt_tag,
                                    local_attempt_path = local_path_tag,
                                    "Removed local directory after checkpoint import failure"
                                );
                            }
                            Err(e) => {
                                error!(
                                    checkpoint = attempt_tag,
                                    local_attempt_path = local_path_tag,
                                    error = e.to_string(),
                                    "Failed to remove local directory after checkpoint import failure");
                            }
                        }
                    }
                    continue;
                }
            }
        }

        let err_msg = format!(
            "No usable checkpoints identified in recovery window for topic:{topic} partition:{partition_number}"
        );
        error!(err_msg);
        Err(anyhow::anyhow!(err_msg))
    }

    pub async fn fetch_checkpoint_metadata(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<Vec<CheckpointMetadata>> {
        let remote_metadata_files = self
            .downloader
            .list_recent_checkpoints(topic, partition_number)
            .await
            .context("In fetch_checkpoint_metadata")?;

        let mut fetched_metadata_files = Vec::new();
        for remote_key in remote_metadata_files {
            match self.downloader.download_file(&remote_key).await {
                Ok(content) => match CheckpointMetadata::from_json_bytes(&content) {
                    Ok(metadata) => {
                        fetched_metadata_files.push(metadata);
                    }
                    Err(e) => {
                        error!("Failed to parse metadata from file bytes: {remote_key}: {e}");
                    }
                },
                Err(e) => {
                    error!("Failed to download metadata file: {remote_key}: {e}");
                }
            }
        }

        if fetched_metadata_files.is_empty() {
            return Err(anyhow::anyhow!("No checkpoint metadata files downloaded successfully for topic:{topic} partition:{partition_number}"));
        }

        Ok(fetched_metadata_files)
    }

    pub async fn fetch_checkpoint_files(
        &self,
        checkpoint_metadata: &CheckpointMetadata,
        local_attempt_path: &Path,
    ) -> Result<()> {
        self.fetch_checkpoint_files_cancellable(checkpoint_metadata, local_attempt_path, None)
            .await
    }

    pub async fn fetch_checkpoint_files_cancellable(
        &self,
        checkpoint_metadata: &CheckpointMetadata,
        local_attempt_path: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        let target_files = checkpoint_metadata
            .files
            .iter()
            .map(|f| f.remote_filepath.clone())
            .collect::<Vec<_>>();

        info!(
            metadata = checkpoint_metadata.get_metadata_filepath(),
            file_count = checkpoint_metadata.files.len(),
            "Fetching checkpoint files from metadata tracking list",
        );

        match self
            .downloader
            .download_files_cancellable(&target_files, local_attempt_path, cancel_token)
            .await
        {
            Ok(_) => {
                info!(
                    "Successfully downloaded {} checkpoint files to: {local_attempt_path:?}",
                    target_files.len()
                );
                Ok(())
            }
            Err(e) => {
                error!("Failed to download checkpoint files to: {local_attempt_path:?}: {e}");
                Err(e)
            }
        }
    }

    pub async fn is_available(&self) -> bool {
        self.downloader.is_available().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use chrono::{TimeZone, Utc};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use tempfile::TempDir;

    /// Mock downloader for testing checkpoint import behavior
    #[derive(Debug)]
    struct MockDownloader {
        metadata: CheckpointMetadata,
        download_count: Arc<AtomicUsize>,
    }

    impl MockDownloader {
        fn new(metadata: CheckpointMetadata) -> Self {
            Self {
                metadata,
                download_count: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for MockDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(vec![self.metadata.get_metadata_filepath()])
        }

        async fn download_file(&self, _remote_key: &str) -> Result<Vec<u8>> {
            let json = self.metadata.to_json()?;
            Ok(json.into_bytes())
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(anyhow::anyhow!("Download cancelled"));
                }
            }
            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            self.download_count.fetch_add(1, Ordering::SeqCst);
            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file_cancellable(key, &local_path, cancel_token)
                    .await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    /// Mock downloader that can simulate failures and delays for cancellation testing
    #[derive(Debug)]
    struct CancellationTestDownloader {
        /// Checkpoints to return from list_recent_checkpoints (multiple for multi-attempt tests)
        checkpoints: Vec<CheckpointMetadata>,
        /// Number of attempts that should fail before succeeding (for multi-attempt tests)
        fail_count: AtomicUsize,
        /// Delay to add during download (to simulate slow downloads)
        download_delay: Option<Duration>,
    }

    impl CancellationTestDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>) -> Self {
            Self {
                checkpoints,
                fail_count: AtomicUsize::new(0),
                download_delay: None,
            }
        }

        fn with_fail_count(mut self, count: usize) -> Self {
            self.fail_count = AtomicUsize::new(count);
            self
        }

        fn with_download_delay(mut self, delay: Duration) -> Self {
            self.download_delay = Some(delay);
            self
        }
    }

    #[async_trait]
    impl CheckpointDownloader for CancellationTestDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(self
                .checkpoints
                .iter()
                .map(|m| m.get_metadata_filepath())
                .collect())
        }

        async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
            // Find the matching checkpoint metadata
            for checkpoint in &self.checkpoints {
                if checkpoint.get_metadata_filepath() == remote_key {
                    return Ok(checkpoint.to_json()?.into_bytes());
                }
            }
            Err(anyhow::anyhow!("Metadata not found: {remote_key}"))
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            // Check cancellation before starting
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(anyhow::anyhow!("Download cancelled"));
                }
            }

            // Simulate slow download if configured
            if let Some(delay) = self.download_delay {
                tokio::time::sleep(delay).await;
            }

            // Check cancellation after delay (simulates mid-stream cancellation)
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(anyhow::anyhow!("Download cancelled mid-stream"));
                }
            }

            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            // Apply delay first (simulates slow network/S3 response)
            if let Some(delay) = self.download_delay {
                tokio::time::sleep(delay).await;
            }

            // Check cancellation after delay
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(anyhow::anyhow!("Download cancelled"));
                }
            }

            // Check if this attempt should fail
            let remaining_fails = self.fail_count.load(Ordering::SeqCst);
            if remaining_fails > 0 {
                self.fail_count.fetch_sub(1, Ordering::SeqCst);
                return Err(anyhow::anyhow!("Simulated download failure"));
            }

            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file_cancellable(key, &local_path, cancel_token)
                    .await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    fn create_test_metadata(topic: &str, partition: i32, hour: u32) -> CheckpointMetadata {
        let timestamp = Utc.with_ymd_and_hms(2025, 6, 15, hour, 0, 0).unwrap();
        let mut metadata =
            CheckpointMetadata::new(topic.to_string(), partition, timestamp, 12345, 100, 50);
        metadata.track_file(
            format!("checkpoints/{topic}/{partition}/2025-06-15T{hour:02}-00-00Z/000001.sst",),
            "checksum1".to_string(),
        );
        metadata
    }

    #[tokio::test]
    async fn test_download_files_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        let result = downloader
            .download_files_cancellable(
                &["checkpoints/test-topic/0/file.sst".to_string()],
                tmp_dir.path(),
                Some(&token),
            )
            .await;

        assert!(result.is_err());
        assert!(
            result.unwrap_err().to_string().contains("cancelled"),
            "Error should mention cancellation"
        );
    }

    #[tokio::test]
    async fn test_import_checkpoint_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);
        let importer =
            CheckpointImporter::new(Box::new(downloader), tmp_dir.path().to_path_buf(), 3);

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        let result = importer
            .import_checkpoint_for_topic_partition_cancellable("test-topic", 0, Some(&token))
            .await;

        assert!(result.is_err());
        assert!(
            result.unwrap_err().to_string().contains("cancelled"),
            "Error should mention cancellation"
        );
    }

    #[tokio::test]
    async fn test_import_checkpoint_cancelled_between_attempts() {
        let tmp_dir = TempDir::new().unwrap();

        // Create two checkpoint attempts
        let metadata1 = create_test_metadata("test-topic", 0, 14); // Most recent
        let metadata2 = create_test_metadata("test-topic", 0, 12); // Older

        // First attempt will fail after 50ms delay, second would succeed
        let downloader = CancellationTestDownloader::new(vec![metadata1, metadata2])
            .with_fail_count(1) // First attempt fails
            .with_download_delay(Duration::from_millis(50)); // Delay before failure

        let importer =
            CheckpointImporter::new(Box::new(downloader), tmp_dir.path().to_path_buf(), 3);

        let token = CancellationToken::new();

        // Cancel after 20ms - during first attempt's delay, before failure check
        let token_clone = token.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(20)).await;
            token_clone.cancel();
        });

        let result = importer
            .import_checkpoint_for_topic_partition_cancellable("test-topic", 0, Some(&token))
            .await;

        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        // Cancellation should be detected during the download delay
        assert!(
            err_msg.contains("cancelled"),
            "Error should mention cancellation, got: {err_msg}"
        );
    }

    #[tokio::test]
    async fn test_download_cancelled_mid_stream() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);

        // Add a delay to simulate slow download
        let downloader = CancellationTestDownloader::new(vec![metadata])
            .with_download_delay(Duration::from_millis(100));

        let token = CancellationToken::new();

        // Cancel after 20ms (before the 100ms download completes)
        let token_clone = token.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(20)).await;
            token_clone.cancel();
        });

        let result = downloader
            .download_files_cancellable(
                &["checkpoints/test-topic/0/file.sst".to_string()],
                tmp_dir.path(),
                Some(&token),
            )
            .await;

        assert!(result.is_err());
        assert!(
            result.unwrap_err().to_string().contains("cancelled"),
            "Error should mention cancellation"
        );
    }

    #[tokio::test]
    async fn test_import_cleans_up_existing_directory_from_crashed_attempt() {
        let tmp_dir = TempDir::new().unwrap();
        let store_base_path = tmp_dir.path().to_path_buf();

        let topic = "test-topic";
        let partition = 0;
        // Use a fixed timestamp so we know exactly what path will be used
        let attempt_timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();

        let mut metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition,
            attempt_timestamp,
            12345,
            100,
            50,
        );
        metadata.track_file(
            "checkpoints/test-topic/0/2025-06-15T12-00-00Z/000001.sst".to_string(),
            "checksum1".to_string(),
        );

        // Calculate the exact path that import will use
        let expected_import_path = metadata.get_store_path(&store_base_path);

        // Simulate a crashed previous attempt: create the directory with a "corrupted" file
        std::fs::create_dir_all(&expected_import_path).unwrap();
        let corrupted_file = expected_import_path.join("CORRUPTED_FROM_CRASH");
        std::fs::write(&corrupted_file, b"this simulates leftover corrupted data").unwrap();
        assert!(
            corrupted_file.exists(),
            "Corrupted file should exist before import"
        );

        // Create importer with mock downloader
        let downloader = MockDownloader::new(metadata);
        let importer = CheckpointImporter::new(Box::new(downloader), store_base_path, 3);

        // Run import - should succeed after cleaning up the corrupted directory
        let result = importer
            .import_checkpoint_for_topic_partition(topic, partition)
            .await;

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        let import_path = result.unwrap();
        assert_eq!(import_path, expected_import_path);

        // Verify the corrupted file is gone (directory was pre-deleted and recreated)
        assert!(
            !corrupted_file.exists(),
            "Corrupted file should have been removed by defensive pre-deletion"
        );

        // Verify the imported file exists
        let imported_file = import_path.join("000001.sst");
        assert!(
            imported_file.exists(),
            "Imported SST file should exist after successful import"
        );
    }
}
