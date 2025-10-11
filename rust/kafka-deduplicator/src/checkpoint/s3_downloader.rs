use std::path::{Path, PathBuf};

use super::config::CheckpointConfig;
use super::downloader::CheckpointDownloader;

use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_config::{meta::region::RegionProviderChain, Region};
use aws_sdk_s3::{Client, Config};
use tokio::fs;
use tracing::info;

#[derive(Debug, Clone)]
pub struct S3Downloader {
    client: Client,
    config: CheckpointConfig,
}

impl S3Downloader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let region_provider =
            RegionProviderChain::default_provider().or_else(Region::new(config.aws_region.clone()));

        let aws_config = aws_config::from_env().region(region_provider).load().await;

        let s3_config = Config::from(&aws_config);
        let client = Client::from_conf(s3_config);

        Ok(Self { client, config })
    }

    /// Download a file from S3 to a local path - return the s3 key of the file if successful
    async fn download_file(&self, s3_key: &str, local_path: &Path) -> Result<()> {
        let response = self
            .client
            .get_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .send()
            .await
            .with_context(|| format!("Failed to download S3 object: {s3_key}"))?;

        let body = response
            .body
            .collect()
            .await
            .context("Failed to read S3 object body")?;

        if let Some(parent) = local_path.parent() {
            fs::create_dir_all(parent).await.with_context(|| {
                format!("Failed to create parent directories for: {local_path:?}")
            })?;
        }

        fs::write(local_path, body.into_bytes())
            .await
            .with_context(|| format!("Failed to write file: {local_path:?}"))?;

        info!(
            "Downloaded s3://{}/{} to {:?}",
            self.config.s3_bucket, s3_key, local_path
        );

        Ok(())
    }

    async fn list_objects_with_prefix(&self, prefix: &str) -> Result<Vec<String>> {
        let response = self
            .client
            .list_objects_v2()
            .bucket(&self.config.s3_bucket)
            .prefix(prefix)
            .send()
            .await
            .context("Failed to list S3 objects")?;

        let keys = response
            .contents()
            .iter()
            .filter_map(|obj| obj.key())
            .map(|k| k.to_string())
            .collect();

        Ok(keys)
    }
}

#[async_trait]
impl CheckpointDownloader for S3Downloader {
    async fn list_checkpoint_metadata(&self, remote_metadata_path: &str) -> Result<Vec<String>> {
        let mut candidates = self
            .list_objects_with_prefix(remote_metadata_path)
            .await
            .with_context(|| {
                format!("Failed to list checkpoint metadata: {remote_metadata_path}")
            })?;

        // Sort by 0-padded UNIX microsecond timestamp embedded
        // in the filename (most recent first)
        candidates.sort_by(|a, b| b.cmp(a));

        Ok(candidates)
    }

    // Download all checkpoint files under the given S3 key prefix to the
    // given local base path which we assume is scoped to the parent
    //CheckpointMetadata (Target)'s topic, partition, and attempt timestamp
    async fn download_checkpoint(
        &self,
        s3_key_prefix: &str,
        local_base_path: &Path,
    ) -> Result<Vec<String>> {
        info!(
            "Downloading checkpoint files from s3://{}/{} to local directory {:?}",
            self.config.s3_bucket, s3_key_prefix, local_base_path,
        );

        // Create local directory
        fs::create_dir_all(local_base_path).await.with_context(|| {
            format!("Failed to create checkpoint directory: {local_base_path:?}")
        })?;

        let files = self
            .list_objects_with_prefix(s3_key_prefix)
            .await
            .with_context(|| {
                format!(
                    "Failed to list checkpoint files from: s3://{}/{}",
                    self.config.s3_bucket, s3_key_prefix
                )
            })?;

        // Download all files concurrently
        let files_to_import: Vec<(String, PathBuf)> = files
            .iter()
            .map(|s3_file_key| {
                let file_key = s3_file_key
                    .strip_prefix(s3_key_prefix)
                    .unwrap_or(s3_file_key)
                    .to_string();
                let file_local_path = local_base_path.join(&file_key);

                (s3_file_key.to_string(), file_local_path)
            })
            .collect();

        let download_tasks: Vec<_> = files_to_import
            .iter()
            .map(|(file_key, file_local_path)| async move {
                self.download_file(file_key, file_local_path).await
            })
            .collect();

        // Execute all downloads concurrently
        futures::future::try_join_all(download_tasks)
            .await
            .with_context(|| {
                format!(
                    "Failed to download checkpoint files from: s3://{}/{}",
                    self.config.s3_bucket, s3_key_prefix
                )
            })?;

        info!(
            "Successfully downloaded checkpoint with {} files to {:?}",
            files.len(),
            local_base_path
        );

        // these short names (just filename or file path without remote/local base prefix)
        // should match what the parent CheckpointMetadata stored in during export, so
        // these should be usable for diffing in a partial fail scenario in the future
        Ok(files_to_import
            .into_iter()
            .map(|(file_key, _)| file_key)
            .collect())
    }

    async fn download_metadata_file(&self, s3_file_key: &str) -> Result<Vec<u8>> {
        let response = self
            .client
            .get_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_file_key)
            .send()
            .await
            .with_context(|| {
                format!("Failed to download checkpoint metadata file: {s3_file_key}")
            })?;

        let body = response
            .body
            .collect()
            .await
            .context("Failed to read {s3_file_key} metadata file body")?;

        Ok(body.into_bytes().to_vec())
    }

    // TODO: may not need this! if the metadata file exists, it was exported
    // *after* the checkpoint files were successfully uploaded, so it's pretty
    // safe to assume the checkpoint files exist at this point in the import flow
    async fn checkpoint_exists(&self, s3_key_prefix: &str) -> Result<bool> {
        let response = self
            .client
            .list_objects_v2()
            .bucket(&self.config.s3_bucket)
            .prefix(s3_key_prefix)
            .max_keys(1)
            .send()
            .await;

        match response {
            Ok(result) => match result.key_count() {
                Some(count) if count > 0 => Ok(true),
                _ => Ok(false),
            },
            Err(e) => Err(anyhow::anyhow!(e.into_service_error())),
        }
    }

    async fn is_available(&self) -> bool {
        !self.config.s3_bucket.is_empty()
    }
}
