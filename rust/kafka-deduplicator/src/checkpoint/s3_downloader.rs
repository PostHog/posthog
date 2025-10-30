use std::path::Path;
use std::time::Instant;

use super::config::CheckpointConfig;
use super::downloader::CheckpointDownloader;
use super::metadata::{DATE_PLUS_HOURS_ONLY_FORMAT, METADATA_FILENAME};
use crate::metrics_const::{
    CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM, CHECKPOINT_FILE_DOWNLOADS_COUNTER,
    CHECKPOINT_FILE_FETCH_HISTOGRAM, CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM,
    CHECKPOINT_LIST_METADATA_HISTOGRAM,
};

use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_config::{meta::region::RegionProviderChain, Region};
use aws_config::{retry::RetryConfig, timeout::TimeoutConfig, BehaviorVersion};
use aws_sdk_s3::{Client, Config};
use chrono::{Duration, Utc};
use tracing::{error, info};

#[derive(Debug, Clone)]
pub struct S3Downloader {
    client: Client,
    config: CheckpointConfig,
}

impl S3Downloader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let region_provider =
            RegionProviderChain::default_provider().or_else(Region::new(config.aws_region.clone()));

        let timeout_config = TimeoutConfig::builder()
            .operation_timeout(config.s3_operation_timeout)
            .operation_attempt_timeout(config.s3_attempt_timeout)
            .build();

        let aws_config = aws_config::defaults(BehaviorVersion::latest())
            .region(region_provider)
            .timeout_config(timeout_config)
            .retry_config(RetryConfig::adaptive())
            .load()
            .await;

        let s3_config = Config::from(&aws_config);
        let client = Client::from_conf(s3_config);

        Ok(Self { client, config })
    }
}

#[async_trait]
impl CheckpointDownloader for S3Downloader {
    async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
        let start_time = Instant::now();
        let get_object = match self
            .client
            .get_object()
            .bucket(&self.config.s3_bucket)
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
                return Err(anyhow::anyhow!(format!(
                    "Failed to get object from S3 bucket: s3://{0}/{remote_key}: {e}",
                    self.config.s3_bucket
                )));
            }
        };

        let body = get_object.body.collect().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object s3://{0}/{remote_key}",
                self.config.s3_bucket,
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
            .bucket(&self.config.s3_bucket)
            .key(remote_key)
            .send()
            .await
        {
            Ok(get_object) => get_object,
            Err(e) => {
                metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error")
                    .increment(1);
                return Err(anyhow::anyhow!(format!(
                    "Failed to get object from S3 bucket: s3://{0}/{remote_key}: {e}",
                    self.config.s3_bucket
                )));
            }
        };

        // Create the file and copy the remote stream into it
        let mut file = tokio::fs::File::create(local_filepath)
            .await
            .with_context(|| format!("Failed to create local file: {local_filepath:?}"))?;
        let mut stream = get_object.body.into_async_read();
        if let Err(e) = tokio::io::copy(&mut stream, &mut file).await {
            metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "error").increment(1);
            return Err(anyhow::anyhow!(
                "Failed to write remote contents to local file: {local_filepath:?}: {e}"
            ));
        }

        metrics::counter!(CHECKPOINT_FILE_DOWNLOADS_COUNTER, "status" => "success").increment(1);
        let elapsed = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM).record(elapsed.as_secs() as f64);

        info!("Downloaded remote file {remote_key} to {local_filepath:?}");
        Ok(())
    }

    async fn download_files(&self, remote_keys: &[String], local_base_path: &Path) -> Result<()> {
        let start_time = Instant::now();
        tokio::fs::create_dir_all(local_base_path)
            .await
            .with_context(|| {
                format!("Failed to create local base directory: {local_base_path:?}")
            })?;

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
                    Err(e) => {
                        Err::<String, anyhow::Error>(anyhow::anyhow!("In download_files: {e}"))
                    }
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
        let import_window_hours =
            Duration::hours(self.config.checkpoint_import_window_hours as i64);
        let remote_key_prefix = format!("{}/{topic}/{partition_number}", self.config.s3_key_prefix);
        let yesterday_remote_key = format!(
            "{}/{}",
            remote_key_prefix,
            (Utc::now() - import_window_hours).format(DATE_PLUS_HOURS_ONLY_FORMAT),
        );

        info!(
            "Listing checkpoint files newer than {} from S3 bucket: {}",
            yesterday_remote_key, self.config.s3_bucket
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
            .bucket(&self.config.s3_bucket)
            .prefix(remote_key_prefix)
            .start_after(&yesterday_remote_key);

        loop {
            let mut req = base_request.clone();
            if let Some(token) = continuation_token {
                req = req.continuation_token(&token);
            }

            let response = req.send().await.with_context(|| {
                format!(
                    "Failed to list remote objects after s3://{}/{yesterday_remote_key}",
                    self.config.s3_bucket
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
            yesterday_remote_key
        );

        Ok(keys_found)
    }

    async fn is_available(&self) -> bool {
        !self.config.s3_bucket.is_empty()
    }
}
