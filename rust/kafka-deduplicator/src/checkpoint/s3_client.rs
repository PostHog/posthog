use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_config::{meta::region::RegionProviderChain, Region};
use aws_sdk_s3::{Client, Config};
use std::path::Path;
use tokio::fs;
use tracing::{info, warn};

use super::client::CheckpointClient;
use super::config::CheckpointConfig;
use super::metadata::{CheckpointInfo, CheckpointMetadata};

#[derive(Debug, Clone)]
pub struct S3CheckpointClient {
    client: Client,
    config: CheckpointConfig,
}

impl S3CheckpointClient {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let region_provider =
            RegionProviderChain::default_provider().or_else(Region::new(config.aws_region.clone()));

        let aws_config = aws_config::from_env().region(region_provider).load().await;

        let s3_config = Config::from(&aws_config);
        let client = Client::from_conf(s3_config);

        Ok(Self { client, config })
    }

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
impl CheckpointClient for S3CheckpointClient {
    async fn list_checkpoint_metadata(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Vec<CheckpointInfo>> {
        let prefix = format!("{}/{}/{}", self.config.s3_key_prefix, topic, partition);
        let keys = self.list_objects_with_prefix(&prefix).await?;

        let mut checkpoint_infos = Vec::new();

        for key in keys {
            if key.ends_with("/metadata.json") {
                // Parse the key to extract checkpoint info
                if let Some((topic_parsed, partition_parsed, _timestamp)) =
                    CheckpointInfo::parse_s3_key(&key, &self.config.s3_key_prefix)
                {
                    if topic_parsed == topic && partition_parsed == partition {
                        // Get the metadata
                        match self.get_checkpoint_metadata(&key).await {
                            Ok(metadata) => {
                                let s3_key_prefix = key.replace("/metadata.json", "");
                                checkpoint_infos.push(CheckpointInfo {
                                    metadata,
                                    s3_key_prefix,
                                });
                            }
                            Err(e) => {
                                warn!("Failed to get checkpoint metadata for key {}: {}", key, e);
                            }
                        }
                    }
                }
            }
        }

        // Sort by timestamp (newest first)
        checkpoint_infos.sort_by(|a, b| b.metadata.timestamp.cmp(&a.metadata.timestamp));

        Ok(checkpoint_infos)
    }

    async fn download_checkpoint(
        &self,
        checkpoint_info: &CheckpointInfo,
        local_path: &Path,
    ) -> Result<()> {
        info!(
            "Downloading checkpoint {} to {:?} using transfer manager",
            checkpoint_info.s3_key_prefix, local_path
        );

        // Create local directory
        fs::create_dir_all(local_path)
            .await
            .with_context(|| format!("Failed to create checkpoint directory: {local_path:?}"))?;

        // Download metadata.json first
        let metadata_s3_key = format!("{}/metadata.json", checkpoint_info.s3_key_prefix);
        let metadata_local_path = local_path.join("metadata.json");
        self.download_file(&metadata_s3_key, &metadata_local_path)
            .await?;

        // Download all files concurrently
        let download_tasks: Vec<_> = checkpoint_info
            .metadata
            .files
            .iter()
            .map(|file| {
                let file_s3_key = format!("{}/{}", checkpoint_info.s3_key_prefix, file.path);
                let file_local_path = local_path.join(&file.path);

                async move { self.download_file(&file_s3_key, &file_local_path).await }
            })
            .collect();

        // Execute all downloads concurrently
        futures::future::try_join_all(download_tasks).await?;

        info!(
            "Successfully downloaded checkpoint with {} files to {:?}",
            checkpoint_info.metadata.files.len(),
            local_path
        );

        Ok(())
    }

    async fn get_checkpoint_metadata(&self, metadata_key: &str) -> Result<CheckpointMetadata> {
        let response = self
            .client
            .get_object()
            .bucket(&self.config.s3_bucket)
            .key(metadata_key)
            .send()
            .await
            .with_context(|| format!("Failed to get checkpoint metadata: {metadata_key}"))?;

        let body = response
            .body
            .collect()
            .await
            .context("Failed to read metadata body")?;

        let json =
            String::from_utf8(body.into_bytes().to_vec()).context("Invalid UTF-8 in metadata")?;

        serde_json::from_str(&json)
            .with_context(|| format!("Failed to parse checkpoint metadata: {metadata_key}"))
    }

    async fn checkpoint_exists(&self, checkpoint_info: &CheckpointInfo) -> Result<bool> {
        let metadata_key = format!("{}/metadata.json", checkpoint_info.s3_key_prefix);

        let result = self
            .client
            .head_object()
            .bucket(&self.config.s3_bucket)
            .key(&metadata_key)
            .send()
            .await;

        Ok(result.is_ok())
    }

    async fn is_available(&self) -> bool {
        !self.config.s3_bucket.is_empty()
    }
}

impl CheckpointInfo {
    /// Parse S3 key to extract topic, partition, and timestamp
    pub fn parse_s3_key(key: &str, prefix: &str) -> Option<(String, i32, u64)> {
        // Remove prefix and split remaining path
        let path = key.strip_prefix(prefix)?.trim_start_matches('/');
        let parts: Vec<&str> = path.split('/').collect();

        if parts.len() < 3 {
            return None;
        }

        let topic = parts[0].to_string();
        let partition = parts[1].parse().ok()?;
        let timestamp = parts[2].parse().ok()?;

        Some((topic, partition, timestamp))
    }
}
