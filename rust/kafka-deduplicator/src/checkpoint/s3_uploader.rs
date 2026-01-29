use anyhow::{Context, Result};
use async_trait::async_trait;
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::types::CompletedMultipartUpload;
use aws_sdk_s3::types::CompletedPart;
use aws_sdk_s3::Client;
use futures::stream::{self, StreamExt};
use std::path::Path;
use tokio::fs::File;
use tokio::io::{AsyncReadExt, AsyncSeekExt};
use tracing::{debug, info};

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
                    config.s3_bucket, config.aws_region.as_deref().unwrap_or("default")
                )
            })?;
        info!(
            "S3 bucket '{}' validated successfully in region '{}'",
            config.s3_bucket,
            config.aws_region.as_deref().unwrap_or("default")
        );

        Ok(Self { client, config })
    }

    /// Upload a file using streaming. For files larger than the part size,
    /// uses multipart upload to avoid loading the entire file into memory.
    async fn upload_file(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let metadata = tokio::fs::metadata(local_path)
            .await
            .with_context(|| format!("Failed to get metadata for file: {local_path:?}"))?;

        let file_size = metadata.len() as usize;
        let part_size = self.config.s3_multipart_part_size_bytes;

        if file_size <= part_size {
            // Small file: use streaming single-part upload
            self.upload_file_streaming(local_path, s3_key).await
        } else {
            // Large file: use multipart upload
            self.upload_file_multipart(local_path, s3_key, file_size)
                .await
        }
    }

    /// Upload a small file using streaming (ByteStream::from_path).
    /// This avoids loading the entire file into memory.
    async fn upload_file_streaming(&self, local_path: &Path, s3_key: &str) -> Result<()> {
        let body = ByteStream::from_path(local_path)
            .await
            .with_context(|| format!("Failed to create byte stream from file: {local_path:?}"))?;

        self.client
            .put_object()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .body(body)
            .send()
            .await
            .with_context(|| format!("Failed to upload to S3 key: {s3_key}"))?;

        debug!(
            "Uploaded file {local_path:?} to s3://{}/{s3_key} (streaming)",
            self.config.s3_bucket
        );
        Ok(())
    }

    /// Upload a large file using multipart upload with concurrent part uploads.
    /// Each part is read and uploaded independently, limiting memory usage to
    /// (part_size * concurrency) bytes.
    async fn upload_file_multipart(
        &self,
        local_path: &Path,
        s3_key: &str,
        file_size: usize,
    ) -> Result<()> {
        let part_size = self.config.s3_multipart_part_size_bytes;
        let concurrency = self.config.s3_multipart_concurrency;

        // Calculate number of parts
        let num_parts = file_size.div_ceil(part_size);

        debug!(
            "Starting multipart upload for {local_path:?}: {file_size} bytes, {num_parts} parts of {part_size} bytes, concurrency {concurrency}"
        );

        // Initiate multipart upload
        let create_response = self
            .client
            .create_multipart_upload()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .send()
            .await
            .with_context(|| format!("Failed to initiate multipart upload for {s3_key}"))?;

        let upload_id = create_response
            .upload_id()
            .ok_or_else(|| anyhow::anyhow!("No upload_id returned from create_multipart_upload"))?
            .to_string();

        // Upload parts concurrently with bounded concurrency
        let part_uploads: Vec<_> = (0..num_parts)
            .map(|i| {
                let part_number = (i + 1) as i32; // S3 part numbers are 1-indexed
                let offset = i * part_size;
                let this_part_size = std::cmp::min(part_size, file_size - offset);
                (part_number, offset, this_part_size)
            })
            .collect();

        let upload_results: Vec<Result<CompletedPart>> = stream::iter(part_uploads)
            .map(|(part_number, offset, this_part_size)| {
                let client = &self.client;
                let bucket = &self.config.s3_bucket;
                let upload_id = &upload_id;
                let local_path = local_path.to_path_buf();

                async move {
                    // Read this part from the file
                    let mut file = File::open(&local_path).await.with_context(|| {
                        format!("Failed to open file for part {part_number}: {local_path:?}")
                    })?;

                    // Seek to the correct offset
                    file.seek(std::io::SeekFrom::Start(offset as u64))
                        .await
                        .with_context(|| {
                            format!("Failed to seek to offset {offset} for part {part_number}")
                        })?;

                    // Read exactly this_part_size bytes
                    let mut buffer = vec![0u8; this_part_size];
                    file.read_exact(&mut buffer).await.with_context(|| {
                        format!("Failed to read {this_part_size} bytes for part {part_number}")
                    })?;

                    // Upload the part
                    let response = client
                        .upload_part()
                        .bucket(bucket)
                        .key(s3_key)
                        .upload_id(upload_id)
                        .part_number(part_number)
                        .body(buffer.into())
                        .send()
                        .await
                        .with_context(|| format!("Failed to upload part {part_number}"))?;

                    let etag = response
                        .e_tag()
                        .ok_or_else(|| anyhow::anyhow!("No ETag returned for part {part_number}"))?
                        .to_string();

                    Ok(CompletedPart::builder()
                        .part_number(part_number)
                        .e_tag(etag)
                        .build())
                }
            })
            .buffer_unordered(concurrency)
            .collect()
            .await;

        // Check for errors and collect completed parts
        let mut completed_parts: Vec<CompletedPart> = Vec::with_capacity(num_parts);
        for result in upload_results {
            match result {
                Ok(part) => completed_parts.push(part),
                Err(e) => {
                    // Abort the multipart upload on error
                    let _ = self
                        .client
                        .abort_multipart_upload()
                        .bucket(&self.config.s3_bucket)
                        .key(s3_key)
                        .upload_id(&upload_id)
                        .send()
                        .await;
                    return Err(e);
                }
            }
        }

        // Sort parts by part number (required by S3)
        completed_parts.sort_by_key(|p| p.part_number());

        // Complete the multipart upload
        let completed_upload = CompletedMultipartUpload::builder()
            .set_parts(Some(completed_parts))
            .build();

        self.client
            .complete_multipart_upload()
            .bucket(&self.config.s3_bucket)
            .key(s3_key)
            .upload_id(&upload_id)
            .multipart_upload(completed_upload)
            .send()
            .await
            .with_context(|| format!("Failed to complete multipart upload for {s3_key}"))?;

        debug!(
            "Uploaded file {local_path:?} to s3://{}/{s3_key} (multipart, {num_parts} parts)",
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

        // Upload metadata.json - small file, use put_object directly
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
