use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_config::{meta::region::RegionProviderChain, Region};
use aws_sdk_s3::{Client, Config};
use std::path::Path;
use tokio::fs;
use tracing::info;

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

    async fn upload_file(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let body = fs::read(local_path)
            .await
            .with_context(|| format!("Failed to read file: {local_path:?}"))?;

        let put_object = self
            .client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .body(body.into());

        // Apply timeout if configured
        let result = tokio::time::timeout(self.config.s3_timeout, put_object.send())
            .await
            .with_context(|| format!("S3 upload timeout for key: {s3_key}"))?;

        result.with_context(|| format!("Failed to upload to S3 key: {s3_key}"))?;

        info!(
            "Uploaded file {local_path:?} to s3://{0}/{s3_key}",
            self.config.s3_bucket
        );
        Ok(())
    }
}

#[async_trait]
impl CheckpointUploader for S3Uploader {
    async fn upload_checkpoint_with_plan(
        &self,
        plan: &super::CheckpointPlan,
    ) -> Result<Vec<String>> {
        info!(
            "Starting upload with plan: {} files to upload, {} files referenced from parents",
            plan.files_to_upload.len(),
            plan.info.metadata.files.len() - plan.files_to_upload.len()
        );

        // Upload all files concurrently (upload_files is in serial atm)
        let upload_futures: Vec<_> = plan
            .files_to_upload
            .iter()
            .map(|(filename, local_path)| {
                let bucket: String = self.config.s3_bucket.clone();
                let src = Path::new(local_path).to_path_buf();
                let dest: String = plan.info.get_file_key(filename);

                async move {
                    self.upload_file(&src, &dest).await.with_context(|| {
                        format!("Failed to upload file: {src:?} to s3://{bucket}/{dest}")
                    })?;
                    Ok::<String, anyhow::Error>(dest)
                }
            })
            .collect();

        let uploaded_keys = futures::future::try_join_all(upload_futures)
            .await
            .with_context(|| format!("Failed to upload files with plan: {plan:?}"))?;

        // Upload metadata.json - not using upload_file b/c meta is in memory and must be seriealized
        let metadata_json = plan.info.metadata.to_json()?;
        let metadata_key = plan.info.get_metadata_key();
        let put_object = self
            .client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(&metadata_key)
            .body(metadata_json.into_bytes().into());

        let result = tokio::time::timeout(self.config.s3_timeout, put_object.send())
            .await
            .with_context(|| format!("S3 upload timeout for key: {metadata_key}"))?;

        result.with_context(|| format!("Failed to upload metadata to S3 key: {metadata_key}"))?;

        info!(
            "Uploaded {} files and metadata file to s3://{}/{}",
            plan.files_to_upload.len(),
            self.config.s3_bucket,
            plan.info.get_remote_attempt_path(),
        );

        let mut all_keys = uploaded_keys;
        all_keys.push(metadata_key);
        Ok(all_keys)
    }

    async fn is_available(&self) -> bool {
        !self.config.s3_bucket.is_empty()
    }
}
