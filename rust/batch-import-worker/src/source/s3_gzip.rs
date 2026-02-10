use crate::error::ToUserError;
use crate::extractor::{ExtractedPartData, PartExtractor};
use anyhow::{Context, Error};
use aws_sdk_s3::Client as S3Client;
use axum::async_trait;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::Mutex;
use tokio::{fs::File, io::AsyncReadExt, io::AsyncSeekExt, io::AsyncWriteExt};
use tracing::{debug, info, warn};

use super::s3::extract_user_friendly_error;
use super::DataSource;

fn sanitize_key_for_path(key: &str) -> String {
    key.replace(['/', ':'], "_")
}

pub struct GzipS3Source {
    client: S3Client,
    bucket: String,
    prefix: String,
    extractor: Arc<dyn PartExtractor>,
    temp_dir: Arc<Mutex<Option<TempDir>>>,
    prepared_keys: Arc<Mutex<HashMap<String, ExtractedPartData>>>,
}

impl GzipS3Source {
    pub fn new(
        client: S3Client,
        bucket: String,
        prefix: String,
        extractor: Arc<dyn PartExtractor>,
    ) -> Self {
        Self {
            client,
            bucket,
            prefix,
            extractor,
            temp_dir: Arc::new(Mutex::new(None)),
            prepared_keys: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    async fn get_temp_dir_path(&self) -> Result<PathBuf, Error> {
        let guard = self.temp_dir.lock().await;
        Ok(guard
            .as_ref()
            .ok_or_else(|| Error::msg("Temp directory not initialized"))?
            .path()
            .to_path_buf())
    }

    async fn get_chunk_from_prepared_key(
        &self,
        key: &str,
        offset: u64,
        size: u64,
    ) -> Result<Vec<u8>, Error> {
        let extracted_part = {
            let prepared_keys = self.prepared_keys.lock().await;
            prepared_keys
                .get(key)
                .ok_or_else(|| Error::msg(format!("Key not prepared: {key}")))?
                .clone()
        };

        if extracted_part.data_file_size == 0 {
            return Ok(Vec::new());
        }

        let total_size = extracted_part.data_file_size as u64;
        if offset >= total_size {
            return Ok(Vec::new());
        }

        let end_offset = std::cmp::min(offset + size, total_size);
        let read_size = (end_offset - offset) as usize;

        let mut file = File::open(&extracted_part.data_file_path)
            .await
            .with_context(|| format!("Failed to open extracted data file for key: {key}"))?;
        file.seek(std::io::SeekFrom::Start(offset))
            .await
            .with_context(|| {
                format!("Failed to seek to offset {offset} in extracted data file for key: {key}")
            })?;
        let mut buffer = vec![0u8; read_size];
        file.read_exact(&mut buffer).await.with_context(|| {
            format!(
                "Failed to read exact {read_size} bytes from extracted data file for key: {key}"
            )
        })?;

        if end_offset == total_size {
            if let Err(e) = self.cleanup_key(key).await {
                warn!("Failed to cleanup key {key}: {e:?}");
            }
        }

        Ok(buffer)
    }
}

#[async_trait]
impl DataSource for GzipS3Source {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        debug!(
            "Listing keys in bucket {} with prefix {}",
            self.bucket, self.prefix
        );
        let mut keys = Vec::new();
        let mut continuation_token = None;
        loop {
            let mut cmd = self
                .client
                .list_objects_v2()
                .bucket(&self.bucket)
                .prefix(self.prefix.clone());
            if let Some(token) = continuation_token {
                cmd = cmd.continuation_token(token);
            }
            let output = cmd.send().await.or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "list objects");
                Err(sdk_error).user_error(friendly_msg)
            })?;

            debug!("Got response: {:?}", output);
            if let Some(contents) = output.contents {
                keys.extend(contents.iter().filter_map(|o| o.key.clone()));
            }
            match output.next_continuation_token {
                Some(token) => continuation_token = Some(token),
                None => break,
            }
        }
        Ok(keys)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        let prepared_keys = self.prepared_keys.lock().await;
        if let Some(extracted_part) = prepared_keys.get(key) {
            Ok(Some(extracted_part.data_file_size as u64))
        } else {
            Ok(None)
        }
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        self.get_chunk_from_prepared_key(key, offset, size).await
    }

    async fn prepare_for_job(&self) -> Result<(), Error> {
        let temp_dir =
            tempfile::tempdir().with_context(|| "Failed to create temp directory for job")?;
        debug!("Created temp directory for job: {:?}", temp_dir.path());

        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            *temp_dir_guard = Some(temp_dir);
        }

        Ok(())
    }

    async fn cleanup_after_job(&self) -> Result<(), Error> {
        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.clear();
        }
        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            if let Some(temp_dir) = temp_dir_guard.take() {
                drop(temp_dir);
                debug!("Cleaned up temp directory");
            }
        }
        debug!("Job cleanup complete");
        Ok(())
    }

    async fn prepare_key(&self, key: &str) -> Result<(), Error> {
        {
            let prepared_keys = self.prepared_keys.lock().await;
            if prepared_keys.contains_key(key) {
                debug!("Key already prepared: {}", key);
                return Ok(());
            }
        }

        let get = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "get object");
                Err(sdk_error).user_error(friendly_msg)
            })?;

        let data = get.body.collect().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object s3://{0}/{key}",
                self.bucket,
            )
        })?;

        let bytes = data.to_vec();
        let temp_dir = self.get_temp_dir_path().await?;
        let safe_key = sanitize_key_for_path(key);

        if bytes.is_empty() {
            let empty_data_file_path = temp_dir.join(format!("{}.data", safe_key));
            let empty_file = File::create(&empty_data_file_path)
                .await
                .with_context(|| format!("Failed to create empty data file for key: {key}"))?;
            empty_file.sync_all().await?;

            let extracted_part = ExtractedPartData {
                data_file_path: empty_data_file_path,
                data_file_size: 0,
            };
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.insert(key.to_string(), extracted_part);
            info!("Prepared key {} (empty object)", key);
            return Ok(());
        }

        let raw_file_path = temp_dir.join(format!("{}.raw", safe_key));
        let mut raw_file = File::create(&raw_file_path)
            .await
            .with_context(|| format!("Failed to create raw file: {}", raw_file_path.display()))?;
        raw_file
            .write_all(&bytes)
            .await
            .with_context(|| format!("Failed to write raw file: {}", raw_file_path.display()))?;
        raw_file
            .sync_all()
            .await
            .with_context(|| format!("Failed to sync raw file: {}", raw_file_path.display()))?;
        drop(raw_file);

        let extracted_part = self
            .extractor
            .extract_compressed_to_seekable_file(&safe_key, &raw_file_path, &temp_dir)
            .await
            .with_context(|| {
                format!("Failed to extract compressed to seekable file for key: {key}")
            })?;

        if let Err(e) = tokio::fs::remove_file(&raw_file_path).await {
            warn!(
                "Failed to remove raw file {}: {e:?}",
                raw_file_path.display()
            );
        }

        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.insert(key.to_string(), extracted_part.clone());
        }

        info!(
            "Prepared key {} ({} bytes decompressed)",
            key, extracted_part.data_file_size
        );

        Ok(())
    }

    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        let extracted_part = {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.remove(key)
        };

        if let Some(extracted_part) = extracted_part {
            if let Err(e) = tokio::fs::remove_file(&extracted_part.data_file_path).await {
                warn!("Failed to remove temp file for key {}: {}", key, e);
            } else {
                debug!("Cleaned up key: {}", key);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sanitize_key_for_path() {
        assert_eq!(sanitize_key_for_path("a/b/c.jsonl.gz"), "a_b_c.jsonl.gz");
        assert_eq!(sanitize_key_for_path("key:with:colons"), "key_with_colons");
        assert_eq!(
            sanitize_key_for_path("path/to/file.jsonl.gz"),
            "path_to_file.jsonl.gz"
        );
    }
}
