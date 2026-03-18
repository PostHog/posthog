use anyhow::{Context, Result};
use async_trait::async_trait;
use futures::stream::FuturesUnordered;
use futures::StreamExt;
use object_store::buffered::BufWriter;
use object_store::path::Path as ObjectPath;
use object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use std::path::Path;
use std::sync::Arc;
use tokio::fs::File;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use super::config::CheckpointConfig;
use super::error::UploadCancelledError;
use super::s3_client::create_s3_client;
use super::uploader::CheckpointUploader;
use crate::metrics_const::CHECKPOINT_FILE_UPLOADS_COUNTER;

/// Chunk size for streaming file reads during upload.
/// Balances memory usage and cancellation responsiveness.
const UPLOAD_CHUNK_SIZE: usize = 8 * 1024 * 1024; // 8MB

/// Result of attempting to read the next chunk from a file with cancellation support
enum ChunkResult {
    Data(usize), // Number of bytes read
    EndOfStream,
    Cancelled,
    Error(std::io::Error),
}

/// Read next chunk from file with cancellation support.
/// Uses `tokio::select!` with `biased;` to ensure cancellation is checked promptly,
/// even if the read is slow or stalled.
async fn read_chunk_cancellable(
    file: &mut File,
    buf: &mut [u8],
    cancel_token: Option<&CancellationToken>,
) -> ChunkResult {
    match cancel_token {
        Some(token) => {
            tokio::select! {
                biased;

                _ = token.cancelled() => ChunkResult::Cancelled,

                result = file.read(buf) => match result {
                    Ok(0) => ChunkResult::EndOfStream,
                    Ok(n) => ChunkResult::Data(n),
                    Err(e) => ChunkResult::Error(e),
                }
            }
        }
        None => match file.read(buf).await {
            Ok(0) => ChunkResult::EndOfStream,
            Ok(n) => ChunkResult::Data(n),
            Err(e) => ChunkResult::Error(e),
        },
    }
}

/// S3Uploader using `object_store` crate with `LimitStore` for bounded concurrency.
/// The LimitStore wraps the S3 client with a semaphore that limits concurrent requests.
#[derive(Debug)]
pub struct S3Uploader {
    store: Arc<dyn ObjectStore>,
    config: CheckpointConfig,
}

impl S3Uploader {
    pub async fn new(config: CheckpointConfig) -> Result<Self> {
        let store =
            create_s3_client(&config, config.max_concurrent_checkpoint_file_uploads).await?;

        info!(
            "S3 uploader initialized for bucket '{}' with max {} concurrent uploads",
            config.s3_bucket, config.max_concurrent_checkpoint_file_uploads
        );

        // Coerce to trait object for use with BufWriter
        let store: Arc<dyn ObjectStore> = store;
        Ok(Self { store, config })
    }

    /// Upload a file with cancellation support.
    /// On cancellation or error, calls abort() to clean up multipart upload parts.
    async fn upload_file_cancellable(
        &self,
        local_path: &Path,
        s3_key: &str,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        // Pre-start cancellation check
        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                metrics::counter!(CHECKPOINT_FILE_UPLOADS_COUNTER, "status" => "cancelled")
                    .increment(1);
                warn!("Upload cancelled before starting: {s3_key}");
                return Err(UploadCancelledError {
                    reason: format!("before starting: {s3_key}"),
                }
                .into());
            }
        }

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

        let mut buf = vec![0u8; UPLOAD_CHUNK_SIZE];

        loop {
            let chunk_result = read_chunk_cancellable(&mut file, &mut buf, cancel_token).await;

            match chunk_result {
                ChunkResult::Data(n) => {
                    if let Err(e) = upload.write_all(&buf[..n]).await {
                        let _ = upload.abort().await;
                        metrics::counter!(CHECKPOINT_FILE_UPLOADS_COUNTER, "status" => "error")
                            .increment(1);
                        return Err(anyhow::Error::new(e))
                            .with_context(|| format!("Failed to write chunk to S3: {s3_key}"));
                    }
                }
                ChunkResult::EndOfStream => break,
                ChunkResult::Cancelled => {
                    let _ = upload.abort().await;
                    metrics::counter!(CHECKPOINT_FILE_UPLOADS_COUNTER, "status" => "cancelled")
                        .increment(1);
                    warn!("Upload of {s3_key} cancelled mid-stream");
                    return Err(UploadCancelledError {
                        reason: format!("mid-stream: {s3_key}"),
                    }
                    .into());
                }
                ChunkResult::Error(e) => {
                    let _ = upload.abort().await;
                    metrics::counter!(CHECKPOINT_FILE_UPLOADS_COUNTER, "status" => "error")
                        .increment(1);
                    return Err(anyhow::Error::new(e)).with_context(|| {
                        format!("Failed to read chunk from file: {local_path:?}")
                    });
                }
            }
        }

        // Finalize the upload (triggers CompleteMultipartUpload API call for large files)
        upload
            .shutdown()
            .await
            .with_context(|| format!("Failed to complete upload for: {s3_key}"))?;

        metrics::counter!(CHECKPOINT_FILE_UPLOADS_COUNTER, "status" => "success").increment(1);
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
    async fn upload_checkpoint_with_plan_cancellable(
        &self,
        plan: &super::CheckpointPlan,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<Vec<String>> {
        // Pre-start check
        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                warn!("Upload cancelled before starting batch");
                return Err(UploadCancelledError {
                    reason: "before starting batch".to_string(),
                }
                .into());
            }
        }

        info!(
            "Starting upload with plan: {} files to upload, {} files referenced from parents",
            plan.files_to_upload.len(),
            plan.info.metadata.files.len() - plan.files_to_upload.len()
        );

        // Create child token for sibling cancellation - allows cancelling siblings
        // without cancelling parent (so caller can continue with other work)
        let upload_token = cancel_token
            .map(|parent| parent.child_token())
            .unwrap_or_default();

        // Build upload futures using FuturesUnordered for early exit with sibling cancellation.
        // LimitStore's semaphore still limits concurrent S3 requests.
        let mut futures: FuturesUnordered<_> = plan
            .files_to_upload
            .iter()
            .map(|local_file| {
                let src = local_file.local_path.clone();
                let dest = plan.info.get_file_key(&local_file.filename);
                let token = upload_token.clone();

                async move {
                    self.upload_file_cancellable(&src, &dest, Some(&token))
                        .await?;
                    Ok::<String, anyhow::Error>(dest)
                }
            })
            .collect();

        let mut uploaded_keys = Vec::with_capacity(plan.files_to_upload.len());
        let mut first_error: Option<anyhow::Error> = None;

        // Process completions, cancel siblings on first error
        while let Some(result) = futures.next().await {
            match result {
                Ok(key) => uploaded_keys.push(key),
                Err(e) => {
                    first_error = Some(e);
                    // Cancel siblings - they'll exit on next chunk read
                    upload_token.cancel();
                    break;
                }
            }
        }

        // Drain remaining futures - they'll exit quickly due to cancellation
        while futures.next().await.is_some() {}

        // Return early on error - DO NOT upload metadata
        if let Some(e) = first_error {
            return Err(e);
        }

        // Check cancellation before uploading metadata (final gate)
        if let Some(token) = cancel_token {
            if token.is_cancelled() {
                warn!("Upload cancelled before metadata upload");
                return Err(UploadCancelledError {
                    reason: "before metadata upload".to_string(),
                }
                .into());
            }
        }

        // ALL files succeeded - now safe to upload metadata
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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use tokio::io::AsyncWriteExt;

    #[tokio::test]
    async fn test_read_chunk_cancellable_returns_data_without_token() {
        let tmp_dir = TempDir::new().unwrap();
        let file_path = tmp_dir.path().join("test_file.txt");

        // Create a test file with some content
        let mut file = tokio::fs::File::create(&file_path).await.unwrap();
        file.write_all(b"hello world").await.unwrap();
        file.flush().await.unwrap();
        drop(file);

        // Read without cancellation token
        let mut file = tokio::fs::File::open(&file_path).await.unwrap();
        let mut buf = vec![0u8; 1024];

        let result = read_chunk_cancellable(&mut file, &mut buf, None).await;
        match result {
            ChunkResult::Data(n) => {
                assert_eq!(n, 11);
                assert_eq!(&buf[..n], b"hello world");
            }
            _ => panic!("Expected Data result"),
        }

        // Next read should return EndOfStream
        let result = read_chunk_cancellable(&mut file, &mut buf, None).await;
        assert!(matches!(result, ChunkResult::EndOfStream));
    }

    #[tokio::test]
    async fn test_read_chunk_cancellable_returns_cancelled_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let file_path = tmp_dir.path().join("test_file.txt");

        // Create a test file
        let mut file = tokio::fs::File::create(&file_path).await.unwrap();
        file.write_all(b"hello world").await.unwrap();
        file.flush().await.unwrap();
        drop(file);

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        // Read with pre-cancelled token should return Cancelled
        let mut file = tokio::fs::File::open(&file_path).await.unwrap();
        let mut buf = vec![0u8; 1024];

        let result = read_chunk_cancellable(&mut file, &mut buf, Some(&token)).await;
        assert!(
            matches!(result, ChunkResult::Cancelled),
            "Expected Cancelled result"
        );
    }

    #[tokio::test]
    async fn test_read_chunk_cancellable_returns_data_with_active_token() {
        let tmp_dir = TempDir::new().unwrap();
        let file_path = tmp_dir.path().join("test_file.txt");

        // Create a test file
        let mut file = tokio::fs::File::create(&file_path).await.unwrap();
        file.write_all(b"hello world").await.unwrap();
        file.flush().await.unwrap();
        drop(file);

        // Create an active (not cancelled) token
        let token = CancellationToken::new();

        // Read with active token should return Data
        let mut file = tokio::fs::File::open(&file_path).await.unwrap();
        let mut buf = vec![0u8; 1024];

        let result = read_chunk_cancellable(&mut file, &mut buf, Some(&token)).await;
        match result {
            ChunkResult::Data(n) => {
                assert_eq!(n, 11);
                assert_eq!(&buf[..n], b"hello world");
            }
            _ => panic!("Expected Data result"),
        }
    }
}
