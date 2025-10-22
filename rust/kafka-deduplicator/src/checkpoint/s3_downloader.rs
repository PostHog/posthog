use std::path::Path;
use std::time::Instant;

use super::config::CheckpointConfig;
use super::downloader::CheckpointDownloader;
use super::metadata::{DATE_PLUS_HOURS_ONLY_FORMAT, METADATA_FILENAME};
use crate::metrics_const::{CHECKPOINT_FILE_FETCH_HISTOGRAM, CHECKPOINT_LIST_METADATA_HISTOGRAM};

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
        let get_object = self
            .client
            .get_object()
            .bucket(&self.config.s3_bucket)
            .key(remote_key)
            .send()
            .await
            .with_context(|| {
                format!(
                    "Failed to get object from S3 bucket: s3://{0}/{remote_key}",
                    self.config.s3_bucket
                )
            })?;

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

    async fn download_files(&self, remote_keys: &[String], local_base_path: &Path) -> Result<()> {
        tokio::fs::create_dir_all(local_base_path)
            .await
            .with_context(|| {
                format!("Failed to create local base directory: {local_base_path:?}")
            })?;

        // TODO: get more sophisticated about partial fails, retries, etc.
        let mut download_futures = Vec::with_capacity(remote_keys.len());
        for remote_key in remote_keys {
            let remote_filename = remote_key
                .rsplit('/')
                .next()
                .with_context(|| format!("Failed to get remote filename from key: {remote_key}"))?
                .to_string();

            download_futures.push(async move {
                match self.download_file(remote_key).await {
                    Ok(contents) => Ok((remote_filename, contents)),
                    Err(e) => Err(e),
                }
            });
        }

        let results: Vec<(String, Vec<u8>)> =
            futures::future::try_join_all(download_futures).await?;
        for (filename, contents) in results {
            let local_filepath = local_base_path.join(filename);
            tokio::fs::write(&local_filepath, contents)
                .await
                .with_context(|| {
                    format!("Failed to write file contents to file: {local_filepath:?}")
                })?;
            info!("Downloaded remote file to {local_filepath:?}");
        }

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
