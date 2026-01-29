use anyhow::{Context, Result};
use async_trait::async_trait;
use futures::StreamExt;
use object_store::aws::AmazonS3Builder;
use object_store::buffered::BufWriter;
use object_store::path::Path as ObjectPath;
use object_store::{ClientOptions, ObjectStore, ObjectStoreExt, PutPayload};
use std::path::Path;
use std::sync::Arc;
use tokio::fs::File;
use tokio::io::AsyncWriteExt;
use tracing::info;

use super::config::CheckpointConfig;
use super::uploader::CheckpointUploader;

#[derive(Debug)]
pub struct S3Uploader {
    store: Arc<dyn ObjectStore>,
    config: CheckpointConfig,
}

impl S3Uploader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        // Per-request timeout (analogous to operation_attempt_timeout in aws_sdk_s3)
        let client_options = ClientOptions::new().with_timeout(config.s3_attempt_timeout);

        let mut builder = AmazonS3Builder::new()
            .with_bucket_name(&config.s3_bucket)
            .with_client_options(client_options)
            .with_retry(object_store::RetryConfig {
                max_retries: 3,
                // Total retry budget (analogous to operation_timeout in aws_sdk_s3)
                retry_timeout: config.s3_operation_timeout,
                ..Default::default()
            });

        // Set region if provided
        if let Some(ref region) = config.aws_region {
            builder = builder.with_region(region);
        }

        // Set custom endpoint for MinIO/local dev
        if let Some(ref endpoint) = config.s3_endpoint {
            builder = builder.with_endpoint(endpoint);
            // Allow HTTP for local development
            if endpoint.starts_with("http://") {
                builder = builder.with_allow_http(true);
            }
        }

        // Set credentials if provided (for local dev without IAM)
        if let (Some(ref access_key), Some(ref secret_key)) =
            (&config.s3_access_key_id, &config.s3_secret_access_key)
        {
            builder = builder
                .with_access_key_id(access_key)
                .with_secret_access_key(secret_key);
        }

        // Force path-style URLs if needed (required for MinIO)
        if config.s3_force_path_style {
            builder = builder.with_virtual_hosted_style_request(false);
        }

        let store = builder.build().with_context(|| {
            format!(
                "Failed to create S3 client for bucket '{}' in region '{}'",
                config.s3_bucket,
                config.aws_region.as_deref().unwrap_or("default")
            )
        })?;

        // Validate bucket access by listing (head not available in object_store)
        let _ = store.list(Some(&ObjectPath::from(""))).next().await;

        info!(
            "S3 bucket '{}' validated successfully in region '{}'",
            config.s3_bucket,
            config.aws_region.as_deref().unwrap_or("default")
        );

        Ok(Self {
            store: Arc::new(store),
            config,
        })
    }

    /// Upload a file using object_store's streaming multipart upload.
    /// Data is streamed from disk to S3 with automatic backpressure handling.
    /// Uses BufWriter which handles chunking and multipart upload internally.
    async fn upload_file(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let path = ObjectPath::from(s3_key);

        let mut file = File::open(local_path)
            .await
            .with_context(|| format!("Failed to open file: {local_path:?}"))?;

        let file_size = file
            .metadata()
            .await
            .with_context(|| format!("Failed to get metadata for file: {local_path:?}"))?
            .len();

        // BufWriter implements AsyncWrite and handles multipart upload internally.
        // It buffers data and automatically uses multipart upload for large files.
        let mut upload = BufWriter::new(Arc::clone(&self.store), path.clone());

        // Stream data from disk to S3 with automatic backpressure.
        // On failure, we must abort to clean up any uploaded parts (ghost upload prevention).
        if let Err(e) = tokio::io::copy(&mut file, &mut upload).await {
            // Attempt to clean up S3 side; ignore secondary error if abort fails
            let _ = upload.abort().await;
            return Err(anyhow::Error::new(e))
                .with_context(|| format!("Failed to stream file to S3: {local_path:?}"));
        }

        // Finalize the upload (triggers CompleteMultipartUpload API call for large files)
        upload
            .shutdown()
            .await
            .with_context(|| format!("Failed to complete upload for: {s3_key}"))?;

        info!(
            "Uploaded file {local_path:?} ({file_size} bytes) to s3://{}/{}",
            self.config.s3_bucket, s3_key
        );
        Ok(())
    }

    /// Upload bytes directly to S3
    async fn upload_bytes(&self, s3_key: &str, data: Vec<u8>) -> Result<()> {
        let path = ObjectPath::from(s3_key);

        self.store
            .put(&path, PutPayload::from(data))
            .await
            .with_context(|| format!("Failed to upload to S3 key: {s3_key}"))?;

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

        // Upload all files concurrently
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

        // Upload metadata.json
        let metadata_json = plan.info.metadata.to_json()?;
        let metadata_key = plan.info.get_metadata_key();
        self.upload_bytes(&metadata_key, metadata_json.into_bytes())
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
