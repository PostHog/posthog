use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use tokio_util::bytes::Bytes;

use super::config::DurabilityConfig;
use super::downloader::CheckpointDownloader;
use super::error::DownloadCancelledError;
use super::lineage::CheckpointLineage;
use super::metadata::{CheckpointMetadata, METADATA_FILENAME};
use super::s3_client::create_s3_client;
use crate::observability::metrics::{
    CHECKPOINT_FILES_DOWNLOADED_TOTAL, CHECKPOINT_FILES_FETCH_DURATION_SECONDS,
    CHECKPOINT_FILE_FETCH_DURATION_SECONDS, CHECKPOINT_FILE_FETCH_STORE_DURATION_SECONDS,
    CHECKPOINT_LIST_DURATION_SECONDS,
};

use anyhow::{Context, Result};
use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use futures::stream;
use futures::{StreamExt, TryStreamExt};
use object_store::limit::LimitStore;
use object_store::path::Path as ObjectPath;
use object_store::{ObjectStore, ObjectStoreExt};
use tokio::io::AsyncWriteExt;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

enum ChunkResult {
    Data(Bytes),
    EndOfStream,
    Cancelled,
    Error(object_store::Error),
}

/// `biased;` ensures cancellation is checked before polling the stream each iteration.
async fn next_chunk_cancellable<S>(
    stream: &mut S,
    cancel_token: Option<&CancellationToken>,
) -> ChunkResult
where
    S: futures::Stream<Item = Result<Bytes, object_store::Error>> + Unpin,
{
    match cancel_token {
        Some(token) => {
            tokio::select! {
                biased;

                _ = token.cancelled() => ChunkResult::Cancelled,

                result = stream.try_next() => match result {
                    Ok(Some(chunk)) => ChunkResult::Data(chunk),
                    Ok(None) => ChunkResult::EndOfStream,
                    Err(e) => ChunkResult::Error(e),
                }
            }
        }
        None => match stream.try_next().await {
            Ok(Some(chunk)) => ChunkResult::Data(chunk),
            Ok(None) => ChunkResult::EndOfStream,
            Err(e) => ChunkResult::Error(e),
        },
    }
}

/// The metadata keys of the attempt folders at or after `now - window`, newest first. Ids are parsed
/// and compared as instants. A folder whose name is not an attempt id is skipped.
fn recent_metadata_keys<'a>(
    folders: impl IntoIterator<Item = &'a str>,
    now: DateTime<Utc>,
    window: Duration,
) -> Vec<String> {
    let cutoff = now - window;
    let mut attempts: Vec<(DateTime<Utc>, &str)> = folders
        .into_iter()
        .filter_map(|folder| {
            let id = folder.rsplit('/').find(|segment| !segment.is_empty())?;
            let attempted_at = CheckpointMetadata::parse_id(id)?;
            (attempted_at >= cutoff).then_some((attempted_at, folder.trim_end_matches('/')))
        })
        .collect();
    attempts.sort_by(|a, b| b.0.cmp(&a.0));
    attempts
        .into_iter()
        .map(|(_, folder)| format!("{folder}/{METADATA_FILENAME}"))
        .collect()
}

/// Classify an object_store error into a short, searchable label for structured logging.
fn s3_error_kind(e: &object_store::Error) -> &'static str {
    match e {
        object_store::Error::NotFound { .. } => "not_found",
        object_store::Error::PermissionDenied { .. } => "permission_denied",
        object_store::Error::Unauthenticated { .. } => "unauthenticated",
        object_store::Error::Precondition { .. } => "precondition",
        object_store::Error::Generic { .. } => "generic",
        _ => "other",
    }
}

/// Each download holds a `LimitStore` permit for the entire stream duration, bounding in-flight
/// memory.
#[derive(Debug)]
pub struct S3Downloader {
    store: Arc<LimitStore<object_store::aws::AmazonS3>>,
    s3_bucket: String,
    /// The lineage's remote directory: every attempt this downloader lists lives under it.
    remote_dir: String,
    checkpoint_import_window_hours: u32,
    max_concurrent_file_downloads: usize,
}

impl S3Downloader {
    pub async fn new(config: &DurabilityConfig, lineage: CheckpointLineage) -> Result<Self> {
        let remote_dir = lineage.remote_dir(&config.s3_key_prefix);
        let store = create_s3_client(
            config,
            config.max_concurrent_checkpoint_file_downloads,
            &remote_dir,
        )
        .await?;

        info!(
            "S3 downloader initialized for bucket '{}' with max {} concurrent downloads",
            config.s3_bucket, config.max_concurrent_checkpoint_file_downloads
        );

        Ok(Self {
            store,
            s3_bucket: config.s3_bucket.clone(),
            remote_dir,
            checkpoint_import_window_hours: config.checkpoint_import_window_hours,
            max_concurrent_file_downloads: config.max_concurrent_checkpoint_file_downloads,
        })
    }
}

#[async_trait]
impl CheckpointDownloader for S3Downloader {
    async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
        let start_time = Instant::now();
        let path = ObjectPath::from(remote_key);

        let result = match self.store.get(&path).await {
            Ok(result) => {
                metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "success")
                    .increment(1);
                result
            }
            Err(e) => {
                // An attempt whose upload never finished has no metadata.json, and a restore
                // expects to meet some, so a missing object is not a download error.
                let status = if matches!(e, object_store::Error::NotFound { .. }) {
                    info!(remote_key, bucket = %self.s3_bucket, "S3 object not found");
                    "not_found"
                } else {
                    error!(
                        remote_key,
                        bucket = %self.s3_bucket,
                        error_kind = s3_error_kind(&e),
                        error = %e,
                        "S3 object download failed"
                    );
                    "error"
                };
                metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => status)
                    .increment(1);
                return Err(anyhow::anyhow!(e)).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        // Buffers the whole response into memory; only used for small metadata.json files.
        let body = result.bytes().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object from bucket {}: {remote_key}",
                self.s3_bucket,
            )
        })?;

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_DURATION_SECONDS).record(elapsed.as_secs_f64());
        Ok(body.to_vec())
    }

    async fn download_and_store_file_cancellable(
        &self,
        remote_key: &str,
        local_filepath: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        let start_time = Instant::now();

        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                warn!("Download cancelled before starting: {remote_key}");
                return Err(DownloadCancelledError {
                    reason: format!("before starting: {remote_key}"),
                }
                .into());
            }
        }

        let path = ObjectPath::from(remote_key);

        let result = match self.store.get(&path).await {
            Ok(result) => result,
            Err(e) => {
                let error_kind = s3_error_kind(&e);
                error!(
                    remote_key,
                    bucket = %self.s3_bucket,
                    error_kind,
                    error = %e,
                    "S3 object download failed"
                );
                metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "error")
                    .increment(1);
                return Err(anyhow::anyhow!(e)).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        let mut file = tokio::fs::File::create(local_filepath)
            .await
            .with_context(|| format!("Failed to create local file: {local_filepath:?}"))?;

        let mut stream = result.into_stream();

        loop {
            let chunk_result = next_chunk_cancellable(&mut stream, cancel_token).await;

            match chunk_result {
                ChunkResult::Data(chunk) => {
                    if let Err(e) = file.write_all(&chunk).await {
                        metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "error")
                            .increment(1);
                        return Err(e).with_context(|| {
                            format!("Failed to write chunk to local file: {local_filepath:?}")
                        });
                    }
                }
                ChunkResult::EndOfStream => break,
                ChunkResult::Cancelled => {
                    drop(file);
                    drop(tokio::fs::remove_file(local_filepath).await);
                    metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "cancelled")
                        .increment(1);
                    warn!("Download of {remote_key} cancelled mid-stream");
                    return Err(DownloadCancelledError {
                        reason: format!("mid-stream: {remote_key}"),
                    }
                    .into());
                }
                ChunkResult::Error(e) => {
                    metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "error")
                        .increment(1);
                    return Err(anyhow::anyhow!(e)).with_context(|| {
                        format!("Failed to read chunk from S3 stream: {remote_key}")
                    });
                }
            }
        }

        file.flush()
            .await
            .with_context(|| format!("Failed to flush file: {local_filepath:?}"))?;

        metrics::counter!(CHECKPOINT_FILES_DOWNLOADED_TOTAL, "status" => "success").increment(1);
        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_STORE_DURATION_SECONDS)
            .record(elapsed.as_secs_f64());

        info!("Downloaded remote file {remote_key} to {local_filepath:?}");
        Ok(())
    }

    async fn download_files_cancellable(
        &self,
        remote_keys: &[String],
        local_base_path: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        let start_time = Instant::now();
        let file_count = remote_keys.len();

        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                warn!("Download cancelled before starting");
                return Err(DownloadCancelledError {
                    reason: "before starting batch".to_string(),
                }
                .into());
            }
        }

        // Pre-collect owned (key, path) pairs so closures capture owned data, not borrowed refs.
        let download_tasks: Vec<_> = remote_keys
            .iter()
            .map(|remote_key| {
                let remote_filename = remote_key
                    .rsplit('/')
                    .next()
                    .unwrap_or(remote_key)
                    .to_string();
                let local_filepath = local_base_path.join(&remote_filename);
                (remote_key.clone(), local_filepath)
            })
            .collect();

        let mut stream = stream::iter(download_tasks)
            .map(|(remote_key, local_filepath)| async move {
                self.download_and_store_file_cancellable(&remote_key, &local_filepath, cancel_token)
                    .await
                    .with_context(|| format!("Failed to download: {remote_key}"))
            })
            .buffer_unordered(self.max_concurrent_file_downloads);

        let mut first_error: Option<anyhow::Error> = None;

        while let Some(result) = stream.next().await {
            if let Err(e) = result {
                first_error = Some(e);
                if let Some(token) = cancel_token {
                    token.cancel();
                }
                break;
            }
        }

        if first_error.is_some() {
            while stream.next().await.is_some() {}
        }

        if let Some(e) = first_error {
            return Err(e);
        }

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILES_FETCH_DURATION_SECONDS).record(elapsed.as_secs_f64());
        info!("Successfully downloaded checkpoint with {file_count} files to local path: {local_base_path:?}");

        Ok(())
    }

    async fn list_recent_checkpoints(&self) -> Result<Vec<String>> {
        let start_time = Instant::now();
        let window = Duration::hours(i64::from(self.checkpoint_import_window_hours));

        // Shallow list (delimiter="/"): returns only the common prefixes (checkpoint folders).
        let prefix = ObjectPath::from(self.remote_dir.as_str());
        let result = self
            .store
            .list_with_delimiter(Some(&prefix))
            .await
            .context("listing checkpoint folders from S3")?;
        let metadata_keys = recent_metadata_keys(
            result.common_prefixes.iter().map(|folder| folder.as_ref()),
            Utc::now(),
            window,
        );

        metrics::histogram!(CHECKPOINT_LIST_DURATION_SECONDS)
            .record(start_time.elapsed().as_secs_f64());
        info!(
            bucket = %self.s3_bucket,
            prefix = %self.remote_dir,
            window_hours = self.checkpoint_import_window_hours,
            candidates = metadata_keys.len(),
            "listed checkpoint attempts",
        );

        Ok(metadata_keys)
    }

    async fn is_available(&self) -> bool {
        !self.s3_bucket.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn the_listing_keeps_attempts_inside_the_window_newest_first() {
        let dir = "819f7b67/checkpoints/cohort_stream_state/0";
        let folders = [
            format!("{dir}/2026-10-09T01-00-00-000Z"),
            format!("{dir}/2026-10-09T05-00-00-000Z"),
            format!("{dir}/2026-10-09T03-00-00-000Z"),
            format!("{dir}/2026-10-09T15-30-00-250Z"),
            format!("{dir}/scratch"),
        ];
        let now = Utc.with_ymd_and_hms(2026, 10, 9, 16, 0, 0).unwrap();

        let keys =
            recent_metadata_keys(folders.iter().map(String::as_str), now, Duration::hours(12));

        assert_eq!(
            keys,
            [
                format!("{dir}/2026-10-09T15-30-00-250Z/metadata.json"),
                format!("{dir}/2026-10-09T05-00-00-000Z/metadata.json"),
            ],
        );
    }
}
