//! Reads checkpoint candidates from S3. Deciding which candidate to restore is
//! [`recovery`](super::recovery)'s job; this module only downloads and decodes.

use std::path::Path;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use tokio_util::sync::CancellationToken;
use tracing::info;

use super::manifest::{ManifestError, OffsetManifest, MANIFEST_FILENAME};
use super::metadata::{CheckpointMetadata, MetadataError, METADATA_FILENAME};
use super::CheckpointDownloader;
use crate::observability::metrics::CHECKPOINT_IMPORT_DURATION_SECONDS;

#[derive(Debug, thiserror::Error)]
pub enum ImportError {
    /// The attempt has no `metadata.json`: its upload failed or was cancelled before the end, since
    /// `metadata.json` is written last.
    #[error("the attempt has no {METADATA_FILENAME}, so its upload never finished")]
    Unfinished,
    #[error(transparent)]
    Download(anyhow::Error),
    #[error(transparent)]
    Metadata(#[from] MetadataError),
    #[error(transparent)]
    Manifest(#[from] ManifestError),
    #[error("the checkpoint tracks no {MANIFEST_FILENAME}")]
    NoManifest,
    #[error("downloading the checkpoint files took longer than {0:?}")]
    Timeout(Duration),
}

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
    import_timeout: Duration,
}

impl CheckpointImporter {
    pub fn new(downloader: Box<dyn CheckpointDownloader>, import_timeout: Duration) -> Self {
        Self {
            downloader,
            import_timeout,
        }
    }

    /// Metadata keys of the lineage's attempts inside the listing window that ends at `now`, newest
    /// first.
    pub async fn candidates(&self, now: DateTime<Utc>) -> anyhow::Result<Vec<String>> {
        self.downloader.list_recent_checkpoints(now).await
    }

    pub async fn metadata(&self, metadata_key: &str) -> Result<CheckpointMetadata, ImportError> {
        let bytes = self
            .downloader
            .download_file(metadata_key)
            .await
            .map_err(|err| match err.downcast_ref::<object_store::Error>() {
                Some(object_store::Error::NotFound { .. }) => ImportError::Unfinished,
                _ => ImportError::Download(err),
            })?;
        Ok(CheckpointMetadata::from_json_bytes(&bytes)?)
    }

    /// The candidate's `offsets.json`, downloaded alone so a candidate is judged before its bulk
    /// download.
    pub async fn manifest(
        &self,
        metadata: &CheckpointMetadata,
    ) -> Result<OffsetManifest, ImportError> {
        let suffix = format!("/{MANIFEST_FILENAME}");
        let key = metadata
            .files
            .iter()
            .find(|file| file.remote_filepath.ends_with(&suffix))
            .ok_or(ImportError::NoManifest)?;
        let bytes = self
            .downloader
            .download_file(&key.remote_filepath)
            .await
            .map_err(ImportError::Download)?;
        Ok(OffsetManifest::decode(&bytes)?)
    }

    /// Downloads every file the candidate tracks into `stage`, which the caller owns and removes on
    /// failure.
    pub async fn fetch_files(
        &self,
        metadata: &CheckpointMetadata,
        stage: &Path,
    ) -> Result<(), ImportError> {
        let started = Instant::now();
        let keys: Vec<String> = metadata
            .files
            .iter()
            .map(|file| file.remote_filepath.clone())
            .collect();
        // Without a token, the files left after a failed one would all still download.
        let siblings = CancellationToken::new();
        let download = self
            .downloader
            .download_files_cancellable(&keys, stage, Some(&siblings));
        let result = match tokio::time::timeout(self.import_timeout, download).await {
            Ok(Ok(())) => Ok(()),
            Ok(Err(err)) => Err(ImportError::Download(err)),
            Err(_elapsed) => Err(ImportError::Timeout(self.import_timeout)),
        };
        let label = if result.is_ok() { "success" } else { "failed" };
        metrics::histogram!(CHECKPOINT_IMPORT_DURATION_SECONDS, "result" => label)
            .record(started.elapsed().as_secs_f64());
        if result.is_ok() {
            info!(
                checkpoint = %metadata.id,
                files = keys.len(),
                elapsed_secs = started.elapsed().as_secs_f64(),
                "downloaded checkpoint files into the stage",
            );
        }
        result
    }
}
