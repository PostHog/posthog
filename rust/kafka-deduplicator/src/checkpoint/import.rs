use std::path::{Path, PathBuf};

use super::{CheckpointDownloader, CheckpointMetadata};

use anyhow::{Context, Result};
use tracing::{error, info};

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
            let local_attempt_path = attempt.get_store_path(&self.store_base_path);
            let local_path_tag = local_attempt_path.to_string_lossy().to_string();
            let attempt_tag = attempt.get_attempt_path();

            // Defensive cleanup: remove any existing directory from a previous failed attempt.
            // Since the path is deterministic (based on checkpoint timestamp), a crash loop
            // could leave corrupted partial downloads that would break the retry.
            if local_attempt_path.exists() {
                info!(
                    checkpoint = attempt_tag,
                    local_attempt_path = local_path_tag,
                    "Removing existing directory before checkpoint import (likely from previous failed attempt)"
                );
                tokio::fs::remove_dir_all(&local_attempt_path)
                    .await
                    .with_context(|| {
                        format!(
                            "Failed to remove existing directory before import: {}",
                            local_path_tag
                        )
                    })?;
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
                .fetch_checkpoint_files(&attempt, &local_attempt_path)
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
                        "Failed to import checkpoint files "
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
            .download_files(&target_files, local_attempt_path)
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

        async fn download_and_store_file(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
        ) -> Result<()> {
            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
        ) -> Result<()> {
            self.download_count.fetch_add(1, Ordering::SeqCst);
            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file(key, &local_path).await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
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
