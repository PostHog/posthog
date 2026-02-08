use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use tokio_util::bytes::Bytes;

use super::config::CheckpointConfig;
use super::downloader::CheckpointDownloader;
use super::error::DownloadCancelledError;
use super::metadata::{DATE_PLUS_HOURS_ONLY_FORMAT, METADATA_FILENAME};
use super::s3_client::create_s3_client;
use crate::metrics_const::{
    CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM, CHECKPOINT_FILE_DOWNLOADS_COUNTER,
    CHECKPOINT_FILE_FETCH_HISTOGRAM, CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM,
    CHECKPOINT_LIST_METADATA_HISTOGRAM,
};

use anyhow::{Context, Result};
use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use futures::stream::FuturesUnordered;
use futures::{StreamExt, TryStreamExt};
use object_store::limit::LimitStore;
use object_store::path::Path as ObjectPath;
use object_store::{ObjectStore, ObjectStoreExt};
use tokio::io::AsyncWriteExt;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

/// Result of attempting to read the next chunk from a stream with cancellation support
enum ChunkResult {
    Data(Bytes),
    EndOfStream,
    Cancelled,
    Error(object_store::Error),
}

/// Read next chunk from stream with cancellation support.
/// Uses `tokio::select!` with `biased;` to ensure cancellation is checked promptly,
/// even if the stream is slow or stalled.
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

/// Build the S3 key prefix for listing checkpoints for a specific topic/partition.
/// The trailing slash is critical: ensures partition "41" doesn't prefix-match "410", "419", etc.
fn format_checkpoint_list_prefix(
    s3_key_prefix: &str,
    topic: &str,
    partition_number: i32,
) -> String {
    format!("{s3_key_prefix}/{topic}/{partition_number}/")
}

/// Build the S3 key used as lexicographic lower bound for listing recent checkpoints.
/// S3 list_objects_v2 returns keys in lexicographic order, and checkpoint IDs are
/// timestamp-formatted (YYYY-MM-DD-HH), so keys >= this bound are within the import window.
fn format_checkpoint_list_start_after(partition_prefix: &str, cutoff: DateTime<Utc>) -> String {
    format!(
        "{}{}",
        partition_prefix,
        cutoff.format(DATE_PLUS_HOURS_ONLY_FORMAT)
    )
}

/// S3Downloader using `object_store` crate with `LimitStore` for bounded concurrency.
/// The LimitStore wraps the S3 client with a semaphore that limits concurrent requests.
/// Each download holds a permit for the entire stream duration, ensuring memory is bounded.
#[derive(Debug)]
pub struct S3Downloader {
    store: Arc<LimitStore<object_store::aws::AmazonS3>>,
    s3_bucket: String,
    s3_key_prefix: String,
    checkpoint_import_window_hours: u32,
}

impl S3Downloader {
    pub async fn new(config: &CheckpointConfig) -> Result<Self> {
        let store =
            create_s3_client(config, config.max_concurrent_checkpoint_file_downloads).await?;

        info!(
            "S3 downloader initialized for bucket '{}' with max {} concurrent downloads",
            config.s3_bucket, config.max_concurrent_checkpoint_file_downloads
        );

        Ok(Self {
            store,
            s3_bucket: config.s3_bucket.clone(),
            s3_key_prefix: config.s3_key_prefix.clone(),
            checkpoint_import_window_hours: config.checkpoint_import_window_hours,
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
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "success")
                    .increment(1);
                result
            }
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                    .increment(1);
                return Err(anyhow::anyhow!(e)).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        // Buffer entire file into memory (used for small metadata.json files)
        let body = result.bytes().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object from bucket {}: {remote_key}",
                self.s3_bucket,
            )
        })?;

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_HISTOGRAM).record(elapsed.as_secs_f64());
        Ok(body.to_vec())
    }

    async fn download_and_store_file_cancellable(
        &self,
        remote_key: &str,
        local_filepath: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        let start_time = Instant::now();

        // Check cancellation before starting the request
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

        // Get object - LimitStore automatically acquires semaphore permit
        // The permit is held for the entire stream duration
        let result = match self.store.get(&path).await {
            Ok(result) => result,
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                    .increment(1);
                return Err(anyhow::anyhow!(e)).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        // Create the file to write chunks to
        let mut file = tokio::fs::File::create(local_filepath)
            .await
            .with_context(|| format!("Failed to create local file: {local_filepath:?}"))?;

        // Stream chunks to disk - permit held until stream fully consumed
        let mut stream = result.into_stream();

        // Process stream with cancellation support
        loop {
            let chunk_result = next_chunk_cancellable(&mut stream, cancel_token).await;

            match chunk_result {
                ChunkResult::Data(chunk) => {
                    if let Err(e) = file.write_all(&chunk).await {
                        metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                            .increment(1);
                        return Err(e).with_context(|| {
                            format!("Failed to write chunk to local file: {local_filepath:?}")
                        });
                    }
                }
                ChunkResult::EndOfStream => break,
                ChunkResult::Cancelled => {
                    drop(file);
                    let _ = tokio::fs::remove_file(local_filepath).await;
                    metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "cancelled")
                        .increment(1);
                    warn!("Download of {remote_key} cancelled mid-stream");
                    return Err(DownloadCancelledError {
                        reason: format!("mid-stream: {remote_key}"),
                    }
                    .into());
                }
                ChunkResult::Error(e) => {
                    metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                        .increment(1);
                    return Err(anyhow::anyhow!(e)).with_context(|| {
                        format!("Failed to read chunk from S3 stream: {remote_key}")
                    });
                }
            }
        }

        // Ensure all data is flushed to disk
        file.flush()
            .await
            .with_context(|| format!("Failed to flush file: {local_filepath:?}"))?;

        metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "success").increment(1);
        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM).record(elapsed.as_secs_f64());

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

        // Check cancellation before starting
        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                warn!("Download cancelled before starting");
                return Err(DownloadCancelledError {
                    reason: "before starting batch".to_string(),
                }
                .into());
            }
        }

        // Build download futures using FuturesUnordered for early exit with sibling cancellation.
        // LimitStore's semaphore still limits concurrent S3 requests.
        let mut futures: FuturesUnordered<_> = remote_keys
            .iter()
            .map(|remote_key| {
                let remote_filename = remote_key
                    .rsplit('/')
                    .next()
                    .unwrap_or(remote_key)
                    .to_string();
                let local_filepath = local_base_path.join(&remote_filename);

                async move {
                    self.download_and_store_file_cancellable(
                        remote_key,
                        &local_filepath,
                        cancel_token,
                    )
                    .await
                    .with_context(|| format!("Failed to download: {remote_key}"))
                }
            })
            .collect();

        let mut first_error: Option<anyhow::Error> = None;

        // Process completions, cancel siblings on first error
        while let Some(result) = futures.next().await {
            if let Err(e) = result {
                first_error = Some(e);
                // Cancel siblings via the attempt token - they'll exit on next chunk iteration
                if let Some(token) = cancel_token {
                    token.cancel();
                }
                break;
            }
        }

        // Drain remaining futures - they'll exit quickly due to cancellation check in their loop
        if first_error.is_some() {
            while futures.next().await.is_some() {}
        }

        if let Some(e) = first_error {
            return Err(e);
        }

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM).record(elapsed.as_secs_f64());
        info!("Successfully downloaded checkpoint with {file_count} files to local path: {local_base_path:?}");

        Ok(())
    }

    async fn list_recent_checkpoints(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<Vec<String>> {
        let start_time = Instant::now();
        let import_window_hours = Duration::hours(self.checkpoint_import_window_hours as i64);
        let remote_key_prefix =
            format_checkpoint_list_prefix(&self.s3_key_prefix, topic, partition_number);
        let cutoff = Utc::now() - import_window_hours;
        let start_after_key = format_checkpoint_list_start_after(&remote_key_prefix, cutoff);

        info!(
            "Listing checkpoint files newer than {} from S3 bucket: {}",
            start_after_key, self.s3_bucket
        );

        // Use object_store's list_with_offset for lexicographic filtering
        // This is equivalent to S3's start_after parameter
        let prefix = ObjectPath::from(remote_key_prefix.as_str());
        let offset = ObjectPath::from(start_after_key.as_str());

        let mut keys_found = Vec::new();
        let mut stream = self.store.list_with_offset(Some(&prefix), &offset);

        while let Some(result) = stream.next().await {
            match result {
                Ok(meta) => {
                    keys_found.push(meta.location.to_string());
                }
                Err(e) => {
                    error!("Error listing S3 objects: {e}");
                }
            }
        }

        // filter results down to only metadata.json files and sort by most recently uploaded
        let total_keys = keys_found.len();
        keys_found.retain(|k| k.ends_with(METADATA_FILENAME));
        keys_found.reverse();

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_LIST_METADATA_HISTOGRAM).record(elapsed.as_secs_f64());
        info!(
            "Found {} metadata.json files of {} total keys scanned at or after: {}",
            keys_found.len(),
            total_keys,
            start_after_key
        );

        Ok(keys_found)
    }

    async fn is_available(&self) -> bool {
        !self.s3_bucket.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_checkpoint_list_prefix_basic() {
        let prefix = format_checkpoint_list_prefix("checkpoints", "events", 0);
        assert_eq!(prefix, "checkpoints/events/0/");
    }

    #[test]
    fn test_format_checkpoint_list_prefix_trailing_slash_prevents_prefix_collision() {
        // This test documents the bug fix: partition 41 must NOT match partition 419
        let prefix_41 = format_checkpoint_list_prefix("checkpoints", "events", 41);
        let prefix_419 = format_checkpoint_list_prefix("checkpoints", "events", 419);

        assert_eq!(prefix_41, "checkpoints/events/41/");
        assert_eq!(prefix_419, "checkpoints/events/419/");

        // The key insight: with trailing slash, "41/" is NOT a prefix of "419/"
        assert!(!prefix_419.starts_with(&prefix_41));

        // Simulated S3 keys that would be returned
        let key_for_41 = "checkpoints/events/41/2026-01-22T12-00-00Z/metadata.json";
        let key_for_419 = "checkpoints/events/419/2026-01-22T12-00-00Z/metadata.json";

        // Prefix 41/ correctly matches only partition 41's keys
        assert!(key_for_41.starts_with(&prefix_41));
        assert!(!key_for_419.starts_with(&prefix_41));

        // Prefix 419/ correctly matches only partition 419's keys
        assert!(key_for_419.starts_with(&prefix_419));
        assert!(!key_for_41.starts_with(&prefix_419));
    }

    #[test]
    fn test_format_checkpoint_list_prefix_with_namespaced_topic() {
        let prefix = format_checkpoint_list_prefix("checkpoints", "ingestion-events-512", 41);
        assert_eq!(prefix, "checkpoints/ingestion-events-512/41/");
    }

    #[test]
    fn test_format_checkpoint_list_start_after_basic() {
        use chrono::TimeZone;

        let prefix = "checkpoints/events/0/";
        let cutoff = Utc.with_ymd_and_hms(2026, 1, 22, 14, 30, 0).unwrap();
        let start_after = format_checkpoint_list_start_after(prefix, cutoff);

        // Format is YYYY-MM-DD-HH (hour precision for lexicographic filtering)
        assert_eq!(start_after, "checkpoints/events/0/2026-01-22-14");
    }

    #[test]
    fn test_format_checkpoint_list_start_after_lexicographic_ordering() {
        use chrono::TimeZone;

        let prefix = "checkpoints/events/0/";

        // Checkpoint IDs use format YYYY-MM-DDTHH-MM-SSZ (e.g., 2026-01-20T12-00-00Z)
        // start_after uses YYYY-MM-DD-HH (e.g., 2026-01-20-12)
        //
        // Since 'T' (ASCII 84) > '-' (ASCII 45), any checkpoint from a given date
        // is lexicographically GREATER than the start_after for that date.
        // This means start_after effectively filters by DATE, not hour.
        let cutoff = Utc.with_ymd_and_hms(2026, 1, 20, 12, 0, 0).unwrap();
        let start_after = format_checkpoint_list_start_after(prefix, cutoff);
        assert_eq!(start_after, "checkpoints/events/0/2026-01-20-12");

        // Keys lexicographically > start_after will be returned by S3 list_objects_v2
        // (start_after is exclusive - keys strictly greater are returned)

        // Previous day: lexicographically < start_after (filtered out)
        let yesterday = "checkpoints/events/0/2026-01-19T23-59-59Z/metadata.json";
        assert!(yesterday < start_after.as_str());

        // Same day but earlier hour: 'T' > '-', so this is > start_after (returned)
        let same_day_early = "checkpoints/events/0/2026-01-20T00-00-00Z/metadata.json";
        assert!(same_day_early > start_after.as_str());

        // Same day, later hour: also > start_after (returned)
        let same_day_late = "checkpoints/events/0/2026-01-20T23-59-59Z/metadata.json";
        assert!(same_day_late > start_after.as_str());

        // Next day: > start_after (returned)
        let tomorrow = "checkpoints/events/0/2026-01-21T08-00-00Z/metadata.json";
        assert!(tomorrow > start_after.as_str());
    }
}
