use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use super::error::{DownloadCancelledError, ImportTimeoutError};
use super::{CheckpointDownloader, CheckpointMetadata};
use crate::metrics_const::{
    CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, CHECKPOINT_IMPORT_DURATION_HISTOGRAM,
};

use anyhow::{Context, Result};
use chrono::Utc;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

/// Cleanup guard that removes the import directory on drop unless defused.
/// Handles: failures, timeouts, cancellations, panics during import.
struct ImportCleanupGuard {
    path: PathBuf,
    topic: String,
    partition: i32,
    defused: bool,
}

impl ImportCleanupGuard {
    fn new(path: PathBuf, topic: String, partition: i32) -> Self {
        Self {
            path,
            topic,
            partition,
            defused: false,
        }
    }

    /// Defuse the guard - directory will NOT be cleaned up on drop.
    /// Call this when import succeeds and path should be kept.
    fn defuse(mut self) -> PathBuf {
        self.defused = true;
        std::mem::take(&mut self.path)
    }
}

impl Drop for ImportCleanupGuard {
    fn drop(&mut self) {
        if !self.defused && self.path.exists() {
            match std::fs::remove_dir_all(&self.path) {
                Ok(_) => {
                    info!(
                        topic = %self.topic,
                        partition = self.partition,
                        path = %self.path.display(),
                        "Import cleanup guard: removed incomplete import directory"
                    );
                }
                Err(e) => {
                    warn!(
                        topic = %self.topic,
                        partition = self.partition,
                        path = %self.path.display(),
                        error = %e,
                        "Import cleanup guard: failed to remove directory, orphan cleaner will handle it"
                    );
                }
            }
        }
    }
}

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
    // Base path for local RocksDB stores - checkpoint files are downloaded directly here
    store_base_path: PathBuf,
    // Number of historical checkpoint attempts to import as fallbacks
    import_attempt_depth: usize,
    // Maximum time allowed for a complete checkpoint import operation
    import_timeout: Duration,
}

impl CheckpointImporter {
    pub fn new(
        downloader: Box<dyn CheckpointDownloader>,
        store_base_path: PathBuf,
        import_attempt_depth: usize,
        import_timeout: Duration,
    ) -> Self {
        Self {
            downloader,
            store_base_path,
            import_attempt_depth,
            import_timeout,
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
    /// The import is wrapped with a timeout to prevent exceeding Kafka max poll interval.
    pub async fn import_checkpoint_for_topic_partition_cancellable(
        &self,
        topic: &str,
        partition_number: i32,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<PathBuf> {
        let start_time = Instant::now();

        // Wrap the entire import with a timeout to prevent exceeding Kafka max poll interval
        match tokio::time::timeout(
            self.import_timeout,
            self.import_checkpoint_inner(topic, partition_number, cancel_token, start_time),
        )
        .await
        {
            Ok(result) => result,
            Err(_elapsed) => {
                error!(
                    topic = topic,
                    partition = partition_number,
                    timeout_secs = self.import_timeout.as_secs(),
                    elapsed_secs = start_time.elapsed().as_secs_f64(),
                    "Checkpoint import timed out"
                );
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "timeout")
                    .record(start_time.elapsed().as_secs_f64());
                Err(ImportTimeoutError {
                    topic: topic.to_string(),
                    partition: partition_number,
                    timeout_secs: self.import_timeout.as_secs(),
                }
                .into())
            }
        }
    }

    /// Inner implementation of checkpoint import, called with a timeout wrapper.
    async fn import_checkpoint_inner(
        &self,
        topic: &str,
        partition_number: i32,
        cancel_token: Option<&CancellationToken>,
        start_time: Instant,
    ) -> Result<PathBuf> {
        let mut checkpoint_metadata = match self
            .fetch_checkpoint_metadata(topic, partition_number)
            .await
        {
            Ok(metadata) => metadata,
            Err(e) => {
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e);
            }
        };

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
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "cancelled")
                        .record(start_time.elapsed().as_secs_f64());
                    return Err(DownloadCancelledError {
                        reason: "import cancelled before attempt".to_string(),
                    }
                    .into());
                }
            }

            let attempt_start = Instant::now();
            let import_timestamp = Utc::now();
            let local_attempt_path =
                attempt.get_store_path(&self.store_base_path, import_timestamp);
            let local_path_tag = local_attempt_path.to_string_lossy().to_string();
            let attempt_tag = attempt.get_attempt_path();

            // Create the directory for this import attempt
            if let Err(e) = tokio::fs::create_dir_all(&local_attempt_path).await {
                metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(attempt_start.elapsed().as_secs_f64());
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e).with_context(|| {
                    format!(
                        "Failed to create local directory for import: {}",
                        local_path_tag
                    )
                });
            }

            // Guard cleans up directory on drop (failure/timeout/cancel/panic) unless defused (success)
            let guard = ImportCleanupGuard::new(
                local_attempt_path.clone(),
                topic.to_string(),
                partition_number,
            );

            // Create child token for this attempt - allows sibling download cancellation
            // on error while preserving fallback to next checkpoint attempt.
            // Child token is cancelled when parent is cancelled (rebalance), or when
            // a file download fails (sibling cancellation).
            let attempt_token = cancel_token
                .map(|parent| parent.child_token())
                .unwrap_or_default();

            match self
                .fetch_checkpoint_files_cancellable(
                    &attempt,
                    &local_attempt_path,
                    Some(&attempt_token),
                )
                .await
            {
                Ok(_) => {
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();

                    // Write marker file with checkpoint metadata to identify this as an imported store
                    let marker_filename =
                        format!(".imported_{}", import_timestamp.timestamp_millis());
                    let marker_path = local_attempt_path.join(&marker_filename);
                    let marker_content = attempt.to_json()?;
                    tokio::fs::write(&marker_path, marker_content)
                        .await
                        .with_context(|| {
                            format!(
                                "Failed to write import marker file: {}",
                                marker_path.display()
                            )
                        })?;

                    info!(
                        checkpoint = attempt_tag,
                        local_store_path = local_path_tag,
                        original_checkpoint_timestamp = %attempt.attempt_timestamp,
                        local_store_timestamp_millis = import_timestamp.timestamp_millis(),
                        marker_file = %marker_filename,
                        attempt_duration_secs = attempt_duration,
                        total_duration_secs = start_time.elapsed().as_secs_f64(),
                        "Successfully imported checkpoint to local directory"
                    );
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "success")
                        .record(attempt_duration);
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "success")
                        .record(start_time.elapsed().as_secs_f64());

                    // Defuse guard - import succeeded, keep the directory
                    return Ok(guard.defuse());
                }
                Err(e) => {
                    // Guard drops here automatically, cleans up directory
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "failed")
                        .record(attempt_duration);
                    error!(
                        checkpoint = attempt_tag,
                        local_attempt_path = local_path_tag,
                        attempt_duration_secs = attempt_duration,
                        error = e.to_string(),
                        "Failed to import checkpoint files"
                    );
                    continue;
                }
            }
        }

        let err_msg = format!(
            "No usable checkpoints identified in recovery window for topic:{topic} partition:{partition_number}"
        );
        error!(err_msg);
        metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
            .record(start_time.elapsed().as_secs_f64());
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
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
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

    /// Mock downloader for testing pre-cancellation checks.
    /// For more complex cancellation scenarios (sibling cancellation, fallback),
    /// use MinIO integration tests which exercise the real S3Downloader.
    #[derive(Debug)]
    struct CancellationTestDownloader {
        checkpoints: Vec<CheckpointMetadata>,
    }

    impl CancellationTestDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>) -> Self {
            Self { checkpoints }
        }
    }

    // NOTE: This mock uses sequential downloads and does NOT implement sibling cancellation
    // (no FuturesUnordered, no token.cancel() on error). It is suitable only for testing
    // pre-cancellation paths. Complex cancellation scenarios (sibling cancellation,
    // fallback after attempt failure) are tested in checkpoint_integration_tests.rs
    // using real S3Downloader with MinIO.
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
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
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
            // Check cancellation before starting
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
                }
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
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {}",
            err
        );
    }

    #[tokio::test]
    async fn test_import_checkpoint_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            tmp_dir.path().to_path_buf(),
            3,
            Duration::from_secs(60),
        );

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        let result = importer
            .import_checkpoint_for_topic_partition_cancellable("test-topic", 0, Some(&token))
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {}",
            err
        );
    }

    #[tokio::test]
    async fn test_import_creates_timestamped_directory_with_marker() {
        let tmp_dir = TempDir::new().unwrap();
        let store_base_path = tmp_dir.path().to_path_buf();

        let topic = "test-topic";
        let partition = 0;
        // Use a fixed timestamp for the checkpoint metadata (this is the "old" checkpoint timestamp)
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

        // Create importer with mock downloader
        let downloader = MockDownloader::new(metadata);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            store_base_path.clone(),
            3,
            Duration::from_secs(60),
        );

        // Record time bounds around the import
        let before_import = Utc::now();
        let result = importer
            .import_checkpoint_for_topic_partition(topic, partition)
            .await;
        let after_import = Utc::now();

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        let import_path = result.unwrap();
        assert!(import_path.exists(), "Import path should exist");

        // Verify the import path uses a current timestamp (Utc::now()), not the checkpoint's old timestamp
        let timestamp_str = import_path.file_name().unwrap().to_str().unwrap();
        let timestamp_millis: i64 = timestamp_str
            .parse()
            .expect("Path should end with timestamp millis");
        assert!(
            timestamp_millis >= before_import.timestamp_millis(),
            "Import timestamp {} should be >= before_import {}",
            timestamp_millis,
            before_import.timestamp_millis()
        );
        assert!(
            timestamp_millis <= after_import.timestamp_millis(),
            "Import timestamp {} should be <= after_import {}",
            timestamp_millis,
            after_import.timestamp_millis()
        );

        // Verify the timestamp is NOT the old checkpoint timestamp
        assert_ne!(
            timestamp_millis,
            attempt_timestamp.timestamp_millis(),
            "Import should use Utc::now(), not the checkpoint's original timestamp"
        );

        // Verify marker file exists with correct content
        let marker_files: Vec<_> = std::fs::read_dir(&import_path)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().starts_with(".imported_"))
            .collect();
        assert_eq!(marker_files.len(), 1, "Should have exactly one marker file");

        let marker_filename = marker_files[0].file_name().to_string_lossy().to_string();
        assert!(
            marker_filename.starts_with(".imported_"),
            "Marker file should start with .imported_"
        );

        // Verify marker file content contains checkpoint metadata
        let marker_content = std::fs::read_to_string(marker_files[0].path()).unwrap();
        let marker_metadata: serde_json::Value =
            serde_json::from_str(&marker_content).expect("Marker should contain valid JSON");
        assert_eq!(marker_metadata["topic"], topic);
        assert_eq!(marker_metadata["partition"], partition);

        // Verify the imported SST file exists
        let imported_file = import_path.join("000001.sst");
        assert!(
            imported_file.exists(),
            "Imported SST file should exist after successful import"
        );
    }

    /// Mock downloader that always fails during file download
    #[derive(Debug)]
    struct FailingDownloader {
        metadata: CheckpointMetadata,
    }

    impl FailingDownloader {
        fn new(metadata: CheckpointMetadata) -> Self {
            Self { metadata }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for FailingDownloader {
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
            _local_filepath: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            Err(anyhow::anyhow!("Simulated download failure"))
        }

        async fn download_files_cancellable(
            &self,
            _remote_keys: &[String],
            _local_base_path: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            Err(anyhow::anyhow!("Simulated download failure"))
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn test_cleanup_guard_removes_directory_on_failure() {
        let tmp_dir = TempDir::new().unwrap();
        let store_base_path = tmp_dir.path().to_path_buf();

        let topic = "test-topic";
        let partition = 0;
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

        // Create importer with failing downloader
        let downloader = FailingDownloader::new(metadata);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            store_base_path.clone(),
            1, // Only 1 attempt so we fail fast
            Duration::from_secs(60),
        );

        // Record the partition directory path
        let partition_dir = store_base_path.join(format!("{topic}_{partition}"));

        // Import should fail
        let result = importer
            .import_checkpoint_for_topic_partition(topic, partition)
            .await;
        assert!(result.is_err(), "Import should fail");

        // The partition directory might exist but should have no timestamp subdirs
        // (the guard should have cleaned them up)
        if partition_dir.exists() {
            let subdirs: Vec<_> = std::fs::read_dir(&partition_dir)
                .unwrap()
                .filter_map(|e| e.ok())
                .filter(|e| e.path().is_dir())
                .collect();
            assert!(
                subdirs.is_empty(),
                "Cleanup guard should have removed the timestamp directory, but found: {:?}",
                subdirs
            );
        }
        // If partition_dir doesn't exist, that's also fine - means cleanup removed everything
    }

    #[test]
    fn test_cleanup_guard_defuse_prevents_cleanup() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        // Create guard and defuse it
        let guard = ImportCleanupGuard::new(test_path.clone(), "topic".to_string(), 0);
        let returned_path = guard.defuse();

        // Path should be returned
        assert_eq!(returned_path, test_path);

        // Directory should still exist (guard was defused)
        assert!(test_path.exists(), "Directory should exist after defuse");
        assert!(test_file.exists(), "File should exist after defuse");
    }

    #[test]
    fn test_cleanup_guard_removes_directory_on_drop() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        // Create guard and let it drop without defusing
        {
            let _guard = ImportCleanupGuard::new(test_path.clone(), "topic".to_string(), 0);
            // guard drops here
        }

        // Directory should be removed
        assert!(
            !test_path.exists(),
            "Directory should be removed after guard drops"
        );
    }
}
