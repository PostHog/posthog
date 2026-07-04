use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Error};
use async_trait::async_trait;
use aws_sdk_s3::Client as S3Client;
use tempfile::TempDir;
use tokio::sync::Mutex;
use tokio::{fs::File, io::AsyncWriteExt};
use tracing::{debug, info, warn};

use crate::error::ToUserError;
use crate::extractor::PartExtractor;
use crate::staging::StagingGuard;

use super::s3::extract_user_friendly_error;
use super::{read_prepared_chunk, remove_prepared_key, DataSource, PreparedPart, RemoteStaging};

fn sanitize_key_for_path(key: &str) -> String {
    key.replace(['/', ':'], "_")
}

fn is_gzip_key(key: &str) -> bool {
    key.ends_with(".gz")
}

pub struct GzipS3Source {
    client: S3Client,
    bucket: String,
    prefix: String,
    extractor: Arc<dyn PartExtractor>,
    staging_dir: PathBuf,
    staging_max_bytes: u64,
    remote_staging: Option<RemoteStaging>,
    temp_dir: Arc<Mutex<Option<TempDir>>>,
    prepared_keys: Arc<Mutex<HashMap<String, PreparedPart>>>,
}

impl GzipS3Source {
    pub fn new(
        client: S3Client,
        bucket: String,
        prefix: String,
        extractor: Arc<dyn PartExtractor>,
        staging_dir: PathBuf,
        staging_max_bytes: u64,
        remote_staging: Option<RemoteStaging>,
    ) -> Self {
        Self {
            client,
            bucket,
            prefix,
            extractor,
            staging_dir,
            staging_max_bytes,
            remote_staging,
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
        read_prepared_chunk(&self.prepared_keys, key, offset, size).await
    }

    /// Stream the compressed object into a temp `.raw` file and return its path, or
    /// `None` for a zero-byte object (the empty `.raw` is removed). The staging guard is
    /// checked before the download, throttled as the file grows, and once more at the
    /// part boundary.
    async fn download_object_raw(&self, key: &str) -> Result<Option<(PathBuf, u64)>, Error> {
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

        let temp_dir = self.get_temp_dir_path().await?;
        let safe_key = sanitize_key_for_path(key);

        // Pause the job if staging is already over budget before we add to it,
        // and again as the `.raw` grows.
        let mut guard = StagingGuard::new(self.staging_dir.clone(), self.staging_max_bytes);
        guard.check().await?;

        let raw_file_path = temp_dir.join(format!("{}.raw", safe_key));
        let mut raw_file = File::create(&raw_file_path)
            .await
            .with_context(|| format!("Failed to create raw file: {}", raw_file_path.display()))?;

        let mut stream = get.body;
        let mut total_bytes: u64 = 0;
        while let Some(chunk) = stream.try_next().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object s3://{0}/{key}",
                self.bucket,
            )
        })? {
            raw_file.write_all(&chunk).await.with_context(|| {
                format!("Failed to write raw file: {}", raw_file_path.display())
            })?;
            total_bytes += chunk.len() as u64;
            guard.record(chunk.len() as u64).await?;
        }

        raw_file
            .sync_all()
            .await
            .with_context(|| format!("Failed to sync raw file: {}", raw_file_path.display()))?;
        drop(raw_file);

        if total_bytes == 0 {
            if let Err(e) = tokio::fs::remove_file(&raw_file_path).await {
                warn!(
                    "Failed to remove empty raw file {}: {e}",
                    raw_file_path.display()
                );
            }
            return Ok(None);
        }

        // Final check once the whole `.raw` is on disk: the per-chunk `record` calls are
        // throttled, so a part smaller than the check interval could otherwise exceed the
        // limit without ever being measured. This enforces the limit at the part boundary.
        guard.check().await?;

        debug!(
            "Streamed {total_bytes} compressed bytes to {} for key: {key}",
            raw_file_path.display()
        );

        Ok(Some((raw_file_path, total_bytes)))
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
                keys.extend(
                    contents
                        .iter()
                        .filter_map(|o| o.key.clone())
                        .filter(|k| is_gzip_key(k)),
                );
            }
            match output.next_continuation_token {
                Some(token) => continuation_token = Some(token),
                None => break,
            }
        }
        Ok(keys)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        if let Some(remote) = &self.remote_staging {
            return remote.backend.size(key).await;
        }
        let prepared_keys = self.prepared_keys.lock().await;
        Ok(prepared_keys.get(key).and_then(|part| part.total_size))
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        if let Some(remote) = &self.remote_staging {
            return remote.read_chunk(key, offset, size).await;
        }
        self.get_chunk_from_prepared_key(key, offset, size).await
    }

    async fn prepare_for_job(&self) -> Result<(), Error> {
        let temp_dir = tempfile::Builder::new()
            .prefix("job-")
            .tempdir_in(&self.staging_dir)
            .with_context(|| {
                format!(
                    "Failed to create temp directory in staging dir: {}",
                    self.staging_dir.display()
                )
            })?;
        debug!("Created temp directory for job: {:?}", temp_dir.path());

        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            *temp_dir_guard = Some(temp_dir);
        }

        Ok(())
    }

    async fn cleanup_after_job(&self) -> Result<(), Error> {
        // Sweep any staged objects this job left in the remote backend (best-effort;
        // the bucket TTL is the final backstop).
        if let Some(remote) = &self.remote_staging {
            remote.sweep_job().await;
        }
        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.clear();
        }
        {
            let mut temp_dir_guard = self.temp_dir.lock().await;
            if let Some(temp_dir) = temp_dir_guard.take() {
                let path = temp_dir.path().to_path_buf();
                if let Err(e) = temp_dir.close() {
                    warn!("Failed to remove temp directory {}: {e}", path.display());
                } else {
                    debug!("Cleaned up temp directory: {}", path.display());
                }
            }
        }
        debug!("Job cleanup complete");
        Ok(())
    }

    async fn prepare_key(&self, key: &str) -> Result<(), Error> {
        if let Some(remote) = &self.remote_staging {
            return remote
                .prepare_key(key, || self.download_object_raw(key))
                .await;
        }

        {
            let prepared_keys = self.prepared_keys.lock().await;
            if prepared_keys.contains_key(key) {
                debug!("Key already prepared: {}", key);
                return Ok(());
            }
        }

        let prepared_part = match self.download_object_raw(key).await? {
            None => {
                info!("Prepared key {} (empty object)", key);
                PreparedPart::empty()
            }
            Some((raw_file_path, total_bytes)) => {
                // Open a streaming decoder over the compressed file; we keep the `.raw`
                // on disk and decompress on demand rather than materializing a `.data`
                // copy, bounding disk usage to the compressed size.
                let reader = self.extractor.open_reader(raw_file_path.clone());
                info!("Prepared key {key} ({total_bytes} compressed bytes, streaming decode)");
                PreparedPart::streaming(raw_file_path, reader)
            }
        };

        {
            let mut prepared_keys = self.prepared_keys.lock().await;
            prepared_keys.insert(key.to_string(), prepared_part);
        }

        Ok(())
    }

    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        if let Some(remote) = &self.remote_staging {
            return remote.backend.cleanup_key(key).await;
        }
        remove_prepared_key(&self.prepared_keys, key).await;
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

    #[test]
    fn test_is_gzip_key() {
        let cases = vec![
            // (key, expected)
            ("analytics/366676/366676_2025-01-01_0#0.json.gz", true),
            ("analytics/366676/366676_2025-01-01_0#1.json.gz", true),
            ("path/to/file.jsonl.gz", true),
            ("data.gz", true),
            ("analytics/366676/366676_2025-01-01_0_complete", false),
            ("analytics/366676/366676_2025-01-01_1_complete", false),
            ("some/path/metadata.json", false),
            ("some/path/readme.txt", false),
            ("", false),
        ];

        for (key, expected) in cases {
            assert_eq!(is_gzip_key(key), expected, "is_gzip_key({key:?})");
        }
    }
}
