use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_sdk_s3::Client;
use std::path::Path;
use tokio::fs;
use tracing::info;

use super::config::CheckpointConfig;
use super::s3_utils::create_s3_client;
use super::uploader::CheckpointUploader;

#[derive(Debug)]
pub struct S3Uploader {
    client: Client,
    config: CheckpointConfig,
}

impl S3Uploader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let client = create_s3_client(&config).await;

        client
            .head_bucket()
            .bucket(&config.s3_bucket)
            .send()
            .await
            .with_context(|| {
                format!(
                    "S3 bucket validation failed for '{}' in region '{}'. Check credentials and bucket access.",
                    config.s3_bucket, config.aws_region
                )
            })?;
        info!(
            "S3 bucket '{}' validated successfully in region '{}'",
            config.s3_bucket, config.aws_region
        );

        Ok(Self { client, config })
    }

    async fn upload_file(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let body = fs::read(local_path)
            .await
            .with_context(|| format!("Failed to read file: {local_path:?}"))?;

        self.client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .body(body.into())
            .send()
            .await
            .with_context(|| format!("Failed to upload to S3 key: {s3_key}"))?;

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
            .map(|local_file| {
                let bucket: String = self.config.s3_bucket.clone();
                let src = local_file.local_path.to_path_buf();
                let dest: String = plan.info.get_file_key(&local_file.filename);

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
        self.client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(&metadata_key)
            .body(metadata_json.into_bytes().into())
            .send()
            .await
            .with_context(|| format!("Failed to upload metadata to S3 key: {metadata_key}"))?;

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
