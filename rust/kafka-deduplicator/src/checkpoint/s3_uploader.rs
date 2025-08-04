use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_config::{meta::region::RegionProviderChain, Region};
use aws_sdk_s3::{Client, Config};
use std::path::{Path, PathBuf};
use tokio::fs;
use tracing::{error, info, warn};

use super::config::CheckpointConfig;
use super::uploader::CheckpointUploader;

#[derive(Debug)]
pub struct S3Uploader {
    client: Client,
    config: CheckpointConfig,
}

impl S3Uploader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let region_provider =
            RegionProviderChain::default_provider().or_else(Region::new(config.aws_region.clone()));

        let aws_config = aws_config::from_env().region(region_provider).load().await;

        let s3_config = Config::from(&aws_config);
        let client = Client::from_conf(s3_config);

        Ok(Self { client, config })
    }

    fn collect_files_to_upload(
        &self,
        base_path: &Path,
        s3_key_prefix: &str,
    ) -> Result<Vec<(PathBuf, String)>> {
        let mut files_to_upload = Vec::new();
        let mut stack = vec![base_path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)
                .with_context(|| format!("Failed to read directory: {:?}", current_path))?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_dir() {
                    stack.push(path);
                } else {
                    let relative_path = path
                        .strip_prefix(base_path)
                        .with_context(|| format!("Failed to get relative path for: {:?}", path))?;

                    let s3_key = format!(
                        "{}/{}",
                        s3_key_prefix,
                        relative_path.to_string_lossy().replace('\\', "/")
                    );

                    files_to_upload.push((path, s3_key));
                }
            }
        }

        Ok(files_to_upload)
    }

    async fn upload_files(&self, files_to_upload: Vec<(PathBuf, String)>) -> Result<Vec<String>> {
        let mut uploaded_keys = Vec::new();

        for (local_path, s3_key) in files_to_upload {
            match self.upload_file(&local_path, &s3_key).await {
                Ok(()) => {
                    uploaded_keys.push(s3_key);
                }
                Err(e) => {
                    error!(
                        "Failed to upload file {:?} to {}: {}",
                        local_path, s3_key, e
                    );
                    return Err(e);
                }
            }
        }

        Ok(uploaded_keys)
    }

    async fn upload_file(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let body = fs::read(local_path)
            .await
            .with_context(|| format!("Failed to read file: {:?}", local_path))?;

        let put_object = self
            .client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .body(body.into());

        // Apply timeout if configured
        let result = tokio::time::timeout(self.config.s3_timeout, put_object.send())
            .await
            .with_context(|| format!("S3 upload timeout for key: {}", s3_key))?;

        result.with_context(|| format!("Failed to upload to S3 key: {}", s3_key))?;

        info!(
            "Uploaded file {:?} to s3://{}/{}",
            local_path, self.config.s3_bucket, s3_key
        );
        Ok(())
    }

    async fn delete_object(&self, key: &str) -> Result<()> {
        self.client
            .delete_object()
            .bucket(&self.config.s3_bucket)
            .key(key)
            .send()
            .await
            .with_context(|| format!("Failed to delete S3 object: {}", key))?;

        info!("Deleted S3 object: {}", key);
        Ok(())
    }
}

#[async_trait]
impl CheckpointUploader for S3Uploader {
    async fn upload_checkpoint_dir(
        &self,
        local_path: &Path,
        s3_key_prefix: &str,
    ) -> Result<Vec<String>> {
        if !local_path.exists() {
            return Err(anyhow::anyhow!(
                "Local checkpoint path does not exist: {:?}",
                local_path
            ));
        }

        info!(
            "Starting upload of checkpoint directory: {:?} to s3://{}/{}",
            local_path, self.config.s3_bucket, s3_key_prefix
        );

        let files_to_upload = self.collect_files_to_upload(local_path, s3_key_prefix)?;
        let uploaded_keys = self.upload_files(files_to_upload).await?;

        info!("Successfully uploaded {} files to S3", uploaded_keys.len());
        Ok(uploaded_keys)
    }

    async fn list_checkpoints(&self) -> Result<Vec<String>> {
        let response = self
            .client
            .list_objects_v2()
            .bucket(&self.config.s3_bucket)
            .prefix(&self.config.s3_key_prefix)
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

    async fn cleanup_old_checkpoints(&self, keep_count: usize) -> Result<()> {
        let mut checkpoint_keys = self.list_checkpoints().await?;

        // Sort by key name (which should include timestamp)
        checkpoint_keys.sort();

        if checkpoint_keys.len() <= keep_count {
            return Ok(());
        }

        let keys_to_delete: Vec<String> = checkpoint_keys
            .into_iter()
            .rev() // Keep the most recent ones
            .skip(keep_count)
            .collect();

        if keys_to_delete.is_empty() {
            return Ok(());
        }

        warn!("Deleting {} old checkpoints from S3", keys_to_delete.len());

        for key in keys_to_delete {
            if let Err(e) = self.delete_object(&key).await {
                error!("Failed to delete S3 object {}: {}", key, e);
                // Continue with other deletions
            }
        }

        Ok(())
    }

    async fn is_available(&self) -> bool {
        !self.config.s3_bucket.is_empty()
    }
}
