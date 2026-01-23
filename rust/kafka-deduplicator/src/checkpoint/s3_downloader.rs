use std::path::Path;
use std::time::Instant;

use super::config::CheckpointConfig;
use super::downloader::CheckpointDownloader;
use super::metadata::{DATE_PLUS_HOURS_ONLY_FORMAT, METADATA_FILENAME};
use super::s3_utils::create_s3_client;
use crate::metrics_const::{
    CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM, CHECKPOINT_FILE_DOWNLOADS_COUNTER,
    CHECKPOINT_FILE_FETCH_HISTOGRAM, CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM,
    CHECKPOINT_LIST_METADATA_HISTOGRAM,
};

use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_sdk_s3::Client;
use chrono::{DateTime, Duration, Utc};
use tracing::{error, info};

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

#[derive(Debug, Clone)]
pub struct S3Downloader {
    client: Client,
    s3_bucket: String,
    s3_key_prefix: String,
    checkpoint_import_window_hours: u32,
}

impl S3Downloader {
    pub async fn new(config: &CheckpointConfig) -> Result<Self> {
        let client = create_s3_client(config).await;

        client
            .head_bucket()
            .bucket(&config.s3_bucket)
            .send()
            .await
            .with_context(|| {
                format!(
                    "S3 bucket validation failed for: {}. Check credentials and bucket access.",
                    config.s3_bucket,
                )
            })?;
        info!("S3 bucket '{}' validated successfully", config.s3_bucket);

        Ok(Self {
            client,
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
        let get_object = match self
            .client
            .get_object()
            .bucket(&self.s3_bucket)
            .key(remote_key)
            .send()
            .await
        {
            Ok(get_object) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "success")
                    .increment(1);
                get_object
            }
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                    .increment(1);
                return Err(e).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        let body = get_object.body.collect().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object from bucket {}: {remote_key}",
                self.s3_bucket,
            )
        })?;

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_HISTOGRAM).record(elapsed.as_secs() as f64);
        Ok(body.to_vec())
    }

    // Download a single file from remote storage and store it in the given local file path.
    // The method assumes the local path parent directories were pre-created
    async fn download_and_store_file(&self, remote_key: &str, local_filepath: &Path) -> Result<()> {
        let start_time = Instant::now();

        let get_object = match self
            .client
            .get_object()
            .bucket(&self.s3_bucket)
            .key(remote_key)
            .send()
            .await
        {
            Ok(get_object) => get_object,
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                    .increment(1);
                return Err(e).with_context(|| {
                    format!(
                        "Failed to get object from S3 bucket {}: {remote_key}",
                        self.s3_bucket
                    )
                });
            }
        };

        // Create the file and copy the remote stream into it
        let mut file = tokio::fs::File::create(local_filepath)
            .await
            .with_context(|| format!("Failed to create local file: {local_filepath:?}"))?;
        let mut stream = get_object.body.into_async_read();
        if let Err(e) = tokio::io::copy(&mut stream, &mut file).await {
            metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error").increment(1);
            return Err(e).with_context(|| {
                format!("Failed to write remote contents to local file: {local_filepath:?}")
            });
        }

        metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "success").increment(1);
        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM).record(elapsed.as_secs() as f64);

        info!("Downloaded remote file {remote_key} to {local_filepath:?}");
        Ok(())
    }

    async fn download_files(&self, remote_keys: &[String], local_base_path: &Path) -> Result<()> {
        let start_time = Instant::now();
        let mut download_futures = Vec::with_capacity(remote_keys.len());
        for remote_key in remote_keys {
            let remote_filename = remote_key
                .rsplit('/')
                .next()
                .with_context(|| {
                    format!("Failed to extract remote filename from key: {remote_key}")
                })?
                .to_string();
            let local_filepath = local_base_path.join(&remote_filename);

            download_futures.push(async move {
                match self
                    .download_and_store_file(remote_key, &local_filepath)
                    .await
                {
                    Ok(()) => Ok::<String, anyhow::Error>(remote_filename),
                    Err(e) => Err::<String, anyhow::Error>(e.context("In download_files")),
                }
            });
        }

        let results = futures::future::try_join_all(download_futures).await?;
        let file_count = results.len();
        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM)
            .record(elapsed.as_secs() as f64);
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

        // list_objects_v2 returns results in *lexicographic sort order*
        // but we want the most recent by timestamp path elem. So, we cheat and
        // use prefix() and start_after() to pull a recent window, that we can
        // hopefully sort in memory to obtain the most recent metadata.json files
        let mut keys_found = Vec::new();
        let mut continuation_token = None;
        let base_request = self
            .client
            .list_objects_v2()
            .bucket(&self.s3_bucket)
            .prefix(remote_key_prefix)
            .start_after(&start_after_key);

        loop {
            let mut req = base_request.clone();
            if let Some(token) = continuation_token {
                req = req.continuation_token(&token);
            }

            let response = req.send().await.with_context(|| {
                format!(
                    "Failed to list remote objects after s3://{}/{start_after_key}",
                    self.s3_bucket
                )
            })?;

            response
                .contents()
                .iter()
                .for_each(|object| match object.key() {
                    Some(key) => {
                        keys_found.push(key.to_string());
                    }
                    None => {
                        error!("Failed to get object key from S3 object: {object:?}");
                    }
                });

            if let Some(true) = response.is_truncated() {
                if let Some(token) = response.next_continuation_token() {
                    continuation_token = Some(token.to_string());
                } else {
                    error!("Expected continuation token not found in response: {response:?}");
                    break;
                }
            } else {
                break;
            }
        }

        // filter results down to only metadata.json files and sort by most recently uploaded
        let total_keys = keys_found.len();
        keys_found.retain(|k| k.ends_with(METADATA_FILENAME));
        keys_found.reverse();

        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_LIST_METADATA_HISTOGRAM).record(elapsed.as_secs() as f64);
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
