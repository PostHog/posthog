use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use super::error::{DownloadCancelledError, ImportTimeoutError};
use super::{CheckpointDownloader, CheckpointMetadata, DirCleanupGuard, STORE_TOPIC};
use crate::observability::metrics::{
    CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS, CHECKPOINT_IMPORT_DURATION_SECONDS,
};
use crate::store::STORE_SCHEMA_VERSION;

use anyhow::{Context, Result};
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
    import_attempt_depth: usize,
    import_timeout: Duration,
}

impl CheckpointImporter {
    pub fn new(
        downloader: Box<dyn CheckpointDownloader>,
        import_attempt_depth: usize,
        import_timeout: Duration,
    ) -> Self {
        Self {
            downloader,
            import_attempt_depth,
            import_timeout,
        }
    }

    /// Lists recent checkpoint metadata.json keys (newest first), tries up to `import_attempt_depth`
    /// of them lazily (one metadata download at a time), and falls back to the next on failure. On
    /// success, downloads all tracked files and writes metadata.json into `target_path`.
    pub async fn import_checkpoint(&self, target_path: &Path) -> Result<PathBuf> {
        self.import_checkpoint_cancellable(target_path, None).await
    }

    /// Import with optional cancellation. The whole operation is bounded by `import_timeout` to stay
    /// below Kafka's max poll interval.
    pub async fn import_checkpoint_cancellable(
        &self,
        target_path: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<PathBuf> {
        let start_time = Instant::now();

        match tokio::time::timeout(
            self.import_timeout,
            self.import_checkpoint_inner(target_path, cancel_token, start_time),
        )
        .await
        {
            Ok(result) => result,
            Err(_elapsed) => {
                error!(
                    store = STORE_TOPIC,
                    timeout_secs = self.import_timeout.as_secs(),
                    elapsed_secs = start_time.elapsed().as_secs_f64(),
                    "Checkpoint import timed out"
                );
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "timeout")
                    .record(start_time.elapsed().as_secs_f64());
                Err(ImportTimeoutError {
                    store: STORE_TOPIC,
                    timeout_secs: self.import_timeout.as_secs(),
                }
                .into())
            }
        }
    }

    async fn import_checkpoint_inner(
        &self,
        target_path: &Path,
        cancel_token: Option<&CancellationToken>,
        start_time: Instant,
    ) -> Result<PathBuf> {
        let metadata_keys = match self.downloader.list_recent_checkpoints().await {
            Ok(keys) => keys,
            Err(e) => {
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e).context("listing checkpoint metadata");
            }
        };

        if metadata_keys.is_empty() {
            metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "failed")
                .record(start_time.elapsed().as_secs_f64());
            return Err(anyhow::anyhow!(
                "No checkpoint metadata files found for store {STORE_TOPIC}"
            ));
        }

        let metadata_keys: Vec<_> = metadata_keys
            .into_iter()
            .take(self.import_attempt_depth)
            .collect();

        info!(
            "Found checkpoint metadata keys for store {STORE_TOPIC}, will attempt up to {} (newest first)",
            metadata_keys.len(),
        );

        let target_path_tag = target_path.to_string_lossy().to_string();

        for remote_key in &metadata_keys {
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    warn!(
                        store = STORE_TOPIC,
                        "Checkpoint import cancelled before attempt"
                    );
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "cancelled")
                        .record(start_time.elapsed().as_secs_f64());
                    return Err(DownloadCancelledError {
                        reason: "import cancelled before attempt".to_string(),
                    }
                    .into());
                }
            }

            let attempt_start = Instant::now();

            let mut attempt = match self.downloader.download_file(remote_key).await {
                Ok(content) => match CheckpointMetadata::from_json_bytes(&content) {
                    Ok(metadata) => metadata,
                    Err(e) => {
                        error!("Failed to parse metadata: {remote_key}: {e:#}");
                        continue;
                    }
                },
                Err(e) => {
                    error!("Failed to download metadata: {remote_key}: {e:#}");
                    continue;
                }
            };

            // Skip a schema-mismatched checkpoint before the bulk data-file download or any local dir
            // mutation. Skipping (not failing) falls through to the next candidate, and a fully-skipped
            // list downgrades to a cold start in `restore_from_s3`.
            if attempt.store_schema != STORE_SCHEMA_VERSION {
                warn!(
                    store = STORE_TOPIC,
                    checkpoint = %remote_key,
                    found = attempt.store_schema,
                    expected = STORE_SCHEMA_VERSION,
                    "Skipping checkpoint written under a different store schema version",
                );
                continue;
            }

            let attempt_tag = attempt.get_attempt_path();

            if target_path.exists() {
                info!(
                    store = STORE_TOPIC,
                    path = %target_path.display(),
                    "Removing stale local store before import"
                );
                drop(tokio::fs::remove_dir_all(target_path).await);
            }

            if let Err(e) = tokio::fs::create_dir_all(target_path).await {
                metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS, "result" => "failed")
                    .record(attempt_start.elapsed().as_secs_f64());
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e).with_context(|| {
                    format!("Failed to create local directory for import: {target_path_tag}")
                });
            }

            let guard = DirCleanupGuard::new(target_path.to_path_buf());

            // A failed file cancels siblings, but the parent token survives so the next attempt can proceed.
            let attempt_token = cancel_token
                .map(|parent| parent.child_token())
                .unwrap_or_default();

            match self
                .fetch_checkpoint_files_cancellable(&attempt, target_path, Some(&attempt_token))
                .await
            {
                Ok(_) => {
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();

                    attempt.write_to_dir(target_path).await.with_context(|| {
                        format!("Failed to write metadata.json to import dir: {target_path_tag}")
                    })?;

                    info!(
                        checkpoint = attempt_tag,
                        local_store_path = target_path_tag,
                        original_checkpoint_timestamp = %attempt.attempt_timestamp,
                        attempt_duration_secs = attempt_duration,
                        total_duration_secs = start_time.elapsed().as_secs_f64(),
                        "Successfully imported checkpoint to local directory"
                    );
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS, "result" => "success")
                        .record(attempt_duration);
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "success")
                        .record(start_time.elapsed().as_secs_f64());

                    return Ok(guard.defuse());
                }
                Err(e) => {
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS, "result" => "failed")
                        .record(attempt_duration);
                    error!(
                        checkpoint = attempt_tag,
                        local_attempt_path = target_path_tag,
                        attempt_duration_secs = attempt_duration,
                        error = ?e,
                        "Failed to import checkpoint files"
                    );
                    continue;
                }
            }
        }

        let err_msg =
            format!("No usable checkpoints identified in recovery window for store {STORE_TOPIC}");
        error!(err_msg);
        metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => "failed")
            .record(start_time.elapsed().as_secs_f64());
        Err(anyhow::anyhow!(err_msg))
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
                error!("Failed to download checkpoint files to: {local_attempt_path:?}: {e:#}");
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

    use crate::store::durability::{STORE_PARTITION, STORE_TOPIC};

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
        async fn list_recent_checkpoints(&self) -> Result<Vec<String>> {
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

    #[derive(Debug)]
    struct CancellationTestDownloader {
        checkpoints: Vec<CheckpointMetadata>,
    }

    impl CancellationTestDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>) -> Self {
            Self { checkpoints }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for CancellationTestDownloader {
        async fn list_recent_checkpoints(&self) -> Result<Vec<String>> {
            Ok(self
                .checkpoints
                .iter()
                .map(CheckpointMetadata::get_metadata_filepath)
                .collect())
        }

        async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
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

    fn create_test_metadata(hour: u32) -> CheckpointMetadata {
        let timestamp = Utc.with_ymd_and_hms(2025, 6, 15, hour, 0, 0).unwrap();
        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            timestamp,
            12345,
            0,
            0,
        );
        metadata.track_file(
            format!(
                "checkpoints/{STORE_TOPIC}/{STORE_PARTITION}/2025-06-15T{hour:02}-00-00Z/000001.sst"
            ),
            "checksum1".to_string(),
        );
        metadata
    }

    #[tokio::test]
    async fn download_files_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata(12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);

        let token = CancellationToken::new();
        token.cancel();

        let result = downloader
            .download_files_cancellable(
                &["checkpoints/file.sst".to_string()],
                tmp_dir.path(),
                Some(&token),
            )
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {err}",
        );
    }

    #[tokio::test]
    async fn import_checkpoint_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata(12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);
        let importer = CheckpointImporter::new(Box::new(downloader), 3, Duration::from_secs(60));

        let token = CancellationToken::new();
        token.cancel();

        let result = importer
            .import_checkpoint_cancellable(&tmp_dir.path().join("store"), Some(&token))
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {err}",
        );
    }

    #[tokio::test]
    async fn import_materializes_target_path_with_files_and_metadata() {
        let tmp_dir = TempDir::new().unwrap();
        let target_path = tmp_dir.path().join("store");

        let attempt_timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();
        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            12345,
            0,
            0,
        );
        metadata.track_file(
            format!("checkpoints/{STORE_TOPIC}/{STORE_PARTITION}/2025-06-15T12-00-00Z/000001.sst"),
            "checksum1".to_string(),
        );

        let downloader = MockDownloader::new(metadata);
        let importer = CheckpointImporter::new(Box::new(downloader), 3, Duration::from_secs(60));

        let before_import = Utc::now();
        let result = importer.import_checkpoint(&target_path).await;
        let after_import = Utc::now();

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        let import_path = result.unwrap();
        assert_eq!(import_path, target_path, "Import path should be the target");
        assert!(import_path.exists(), "Import path should exist");

        let imported_file = import_path.join("000001.sst");
        assert!(
            imported_file.exists(),
            "Imported SST file should exist after successful import"
        );

        let loaded_metadata = CheckpointMetadata::load_from_dir(&import_path)
            .await
            .expect("metadata.json should exist and deserialize");
        assert_eq!(loaded_metadata.topic, STORE_TOPIC);
        assert_eq!(loaded_metadata.partition, STORE_PARTITION);
        assert!(
            loaded_metadata.updated_at.timestamp_millis() >= before_import.timestamp_millis(),
            "updated_at should be >= before_import"
        );
        assert!(
            loaded_metadata.updated_at.timestamp_millis() <= after_import.timestamp_millis(),
            "updated_at should be <= after_import"
        );
    }

    #[tokio::test]
    async fn import_skips_a_schema_mismatched_checkpoint_and_uses_the_next() {
        let tmp_dir = TempDir::new().unwrap();
        let target_path = tmp_dir.path().join("store");

        let mut newest = create_test_metadata(13);
        newest.store_schema = STORE_SCHEMA_VERSION + 1; // incompatible
        let current = create_test_metadata(12); // stamped with STORE_SCHEMA_VERSION by `new`
        assert_eq!(current.store_schema, STORE_SCHEMA_VERSION);

        // Newest first, matching the S3 listing order.
        let downloader = CancellationTestDownloader::new(vec![newest.clone(), current.clone()]);
        let importer = CheckpointImporter::new(Box::new(downloader), 3, Duration::from_secs(60));

        let import_path = importer
            .import_checkpoint(&target_path)
            .await
            .expect("import should skip the mismatched candidate and use the current one");

        let loaded = CheckpointMetadata::load_from_dir(&import_path)
            .await
            .expect("metadata.json written for the accepted candidate");
        assert_eq!(
            loaded.store_schema, STORE_SCHEMA_VERSION,
            "the imported checkpoint is the current-era one, not the mismatched newest",
        );
        assert_eq!(
            loaded.id, current.id,
            "the accepted attempt is the older, schema-matching candidate",
        );
    }

    #[tokio::test]
    async fn import_fails_when_every_candidate_has_a_mismatched_schema() {
        let tmp_dir = TempDir::new().unwrap();
        let target_path = tmp_dir.path().join("store");

        let mut old_era = create_test_metadata(12);
        old_era.store_schema = 0; // pre-versioning metadata.json decodes to this
        let downloader = CancellationTestDownloader::new(vec![old_era]);
        let importer = CheckpointImporter::new(Box::new(downloader), 3, Duration::from_secs(60));

        let result = importer.import_checkpoint(&target_path).await;
        assert!(
            result.is_err(),
            "an all-mismatched candidate list yields no usable checkpoint",
        );
        assert!(
            !target_path.exists(),
            "a skipped candidate must not create or leave any local store directory",
        );
    }

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
        async fn list_recent_checkpoints(&self) -> Result<Vec<String>> {
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
    async fn cleanup_guard_removes_directory_on_failure() {
        let tmp_dir = TempDir::new().unwrap();
        let target_path = tmp_dir.path().join("store");

        let attempt_timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();
        let mut metadata = CheckpointMetadata::new(
            STORE_TOPIC.to_string(),
            STORE_PARTITION,
            attempt_timestamp,
            12345,
            0,
            0,
        );
        metadata.track_file(
            format!("checkpoints/{STORE_TOPIC}/{STORE_PARTITION}/2025-06-15T12-00-00Z/000001.sst"),
            "checksum1".to_string(),
        );

        let downloader = FailingDownloader::new(metadata);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            1, // Only 1 attempt so we fail fast
            Duration::from_secs(60),
        );

        let result = importer.import_checkpoint(&target_path).await;
        assert!(result.is_err(), "Import should fail");

        assert!(
            !target_path.exists(),
            "Cleanup guard should have removed the store directory on failure"
        );
    }

    #[test]
    fn cleanup_guard_defuse_prevents_cleanup() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        let guard = DirCleanupGuard::new(test_path.clone());
        let returned_path = guard.defuse();

        assert_eq!(returned_path, test_path);
        assert!(test_path.exists(), "Directory should exist after defuse");
        assert!(test_file.exists(), "File should exist after defuse");
    }

    #[test]
    fn cleanup_guard_removes_directory_on_drop() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        {
            let _guard = DirCleanupGuard::new(test_path.clone());
        }

        assert!(
            !test_path.exists(),
            "Directory should be removed after guard drops"
        );
    }

    #[derive(Debug)]
    struct TrackingDownloader {
        checkpoints: Vec<CheckpointMetadata>,
        metadata_download_count: Arc<AtomicUsize>,
        file_download_fail_count: usize,
        file_download_attempts: Arc<AtomicUsize>,
    }

    impl TrackingDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>, file_download_fail_count: usize) -> Self {
            Self {
                checkpoints,
                metadata_download_count: Arc::new(AtomicUsize::new(0)),
                file_download_fail_count,
                file_download_attempts: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for TrackingDownloader {
        async fn list_recent_checkpoints(&self) -> Result<Vec<String>> {
            Ok(self
                .checkpoints
                .iter()
                .map(CheckpointMetadata::get_metadata_filepath)
                .collect())
        }

        async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
            self.metadata_download_count.fetch_add(1, Ordering::SeqCst);
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
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            let attempt = self.file_download_attempts.fetch_add(1, Ordering::SeqCst);
            if attempt < self.file_download_fail_count {
                return Err(anyhow::anyhow!("Simulated file download failure"));
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

    #[tokio::test]
    async fn lazy_metadata_download_only_fetches_needed() {
        let tmp_dir = TempDir::new().unwrap();

        let checkpoints = vec![
            create_test_metadata(14),
            create_test_metadata(13),
            create_test_metadata(12),
        ];

        let tracker = TrackingDownloader::new(checkpoints, 0);
        let download_count = Arc::clone(&tracker.metadata_download_count);

        let importer = CheckpointImporter::new(Box::new(tracker), 3, Duration::from_secs(60));

        let result = importer
            .import_checkpoint(&tmp_dir.path().join("store"))
            .await;

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        assert_eq!(
            download_count.load(Ordering::SeqCst),
            1,
            "Only the newest metadata.json should be downloaded when the first attempt succeeds"
        );
    }

    #[tokio::test]
    async fn lazy_metadata_download_fallback_downloads_incrementally() {
        let tmp_dir = TempDir::new().unwrap();

        let checkpoints = vec![
            create_test_metadata(14),
            create_test_metadata(13),
            create_test_metadata(12),
        ];

        let tracker = TrackingDownloader::new(checkpoints, 2);
        let metadata_count = Arc::clone(&tracker.metadata_download_count);

        let importer = CheckpointImporter::new(Box::new(tracker), 3, Duration::from_secs(60));

        let result = importer
            .import_checkpoint(&tmp_dir.path().join("store"))
            .await;

        assert!(
            result.is_ok(),
            "Import should succeed on 3rd attempt: {:?}",
            result.err()
        );
        assert_eq!(
            metadata_count.load(Ordering::SeqCst),
            3,
            "Should download exactly 3 metadata files (2 failed attempts + 1 success)"
        );
    }
}
