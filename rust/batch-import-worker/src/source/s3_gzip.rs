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

    /// Free pod-local state: prepared readers/`.raw` files and the job temp dir.
    /// Clear refs first, then explicitly `close()` the temp dir to surface removal
    /// errors. Never touches remote staging.
    async fn cleanup_local_resources(&self) {
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
        // Terminal: sweep any staged objects this job left in the remote backend
        // (best-effort; the bucket TTL is the final backstop), then release local
        // resources.
        if let Some(remote) = &self.remote_staging {
            remote.sweep_job().await;
        }
        self.cleanup_local_resources().await;
        debug!("Job cleanup complete");
        Ok(())
    }

    async fn release_job_resources(&self) -> Result<(), Error> {
        // Transient interruption: keep staged remote objects for the resume to
        // re-attach to; free only pod-local disk and in-memory state (the disk is
        // shared with whatever job this pod claims next).
        self.cleanup_local_resources().await;
        debug!("Job resources released (remote staging kept for resume)");
        Ok(())
    }

    async fn cleanup_after_data_error(&self) -> Result<(), Error> {
        // Data-error pause: quarantine staged plaintext for post-mortem (it is
        // the exact byte stream the failing offset points into), so the resume
        // re-downloads a clean copy while support can still inspect the bytes
        // that failed to parse.
        if let Some(remote) = &self.remote_staging {
            remote.quarantine_job().await;
        }
        self.cleanup_local_resources().await;
        debug!("Job data-error cleanup complete (staged parts quarantined)");
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

/// Remote (temp-bucket) staging mode for the S3 gzip source, held to the same contract
/// as the date-range source: the origin is a real aws-sdk S3 client pointed at an
/// httpmock endpoint (GetObject only — these tests address parts by key, as the job
/// loop does), and the backend is the real one over `object_store::memory::InMemory`.
#[cfg(test)]
mod remote_staging_tests {
    use super::*;
    use crate::extractor::ExtractorType;
    use crate::source::RemoteStaging;
    use crate::staging::TempBucketBackend;
    use aws_config::BehaviorVersion;
    use aws_sdk_s3::config::{Credentials, Region};
    use flate2::{write::GzEncoder, Compression};
    use httpmock::{Mock, MockServer};
    use object_store::memory::InMemory;
    use object_store::ObjectStore;
    use std::io::Write;
    use std::path::Path;
    use tempfile::TempDir;

    const BUCKET: &str = "customer-bucket";
    const KEY: &str = "exports/2024/events-0001.jsonl.gz";

    /// Realistic captured-event JSONL: multiple records whose boundaries don't align
    /// with the small read slices used below.
    fn realistic_body() -> Vec<u8> {
        let mut body = Vec::new();
        for i in 0..40u32 {
            let line = serde_json::json!({
                "event": "$pageview",
                "distinct_id": format!("user-{i}"),
                "timestamp": format!("2024-01-{:02}T12:00:00Z", (i % 28) + 1),
                "uuid": uuid::Uuid::now_v7().to_string(),
                "properties": { "idx": i, "$browser": "Firefox" }
            })
            .to_string();
            body.extend_from_slice(line.as_bytes());
            body.push(b'\n');
        }
        body
    }

    fn gzip(data: &[u8]) -> Vec<u8> {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(data).unwrap();
        encoder.finish().unwrap()
    }

    /// Mock the S3 GetObject request the aws-sdk client issues for `KEY`
    /// (path-style: GET /{bucket}/{key}).
    fn mock_get_object<'a>(server: &'a MockServer, gz: &[u8]) -> Mock<'a> {
        let body = gz.to_vec();
        server.mock(move |when, then| {
            when.method(httpmock::Method::GET)
                .path(format!("/{BUCKET}/{KEY}"));
            then.status(200).body(body.clone());
        })
    }

    async fn aws_client_for(server: &MockServer) -> aws_sdk_s3::Client {
        let config = aws_config::defaults(BehaviorVersion::latest())
            .endpoint_url(server.base_url())
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::new("k", "s", None, None, "test"))
            .load()
            .await;
        let s3_config = aws_sdk_s3::config::Builder::from(&config)
            .force_path_style(true)
            .build();
        aws_sdk_s3::Client::from_conf(s3_config)
    }

    async fn build_source(
        server: &MockServer,
        staging: &Path,
        store: Arc<dyn ObjectStore>,
    ) -> GzipS3Source {
        GzipS3Source::new(
            aws_client_for(server).await,
            BUCKET.to_string(),
            "exports/".to_string(),
            ExtractorType::PlainGzip.create_extractor(),
            staging.to_path_buf(),
            0,
            Some(RemoteStaging {
                backend: Arc::new(TempBucketBackend::new(store, "staging/", "job-S3GZ")),
                extractor_type: ExtractorType::PlainGzip,
                max_plaintext_bytes: 0,
            }),
        )
    }

    #[tokio::test]
    async fn remote_round_trip_resume_and_lifecycle() {
        let body = realistic_body();
        let server = MockServer::start();
        let mock = mock_get_object(&server, &gzip(&body));
        let staging = TempDir::new().unwrap();
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());

        let src = build_source(&server, staging.path(), Arc::clone(&store)).await;
        src.prepare_for_job().await.unwrap();

        // Stage on first touch; size known immediately; prepare_key idempotent.
        src.prepare_key(KEY).await.unwrap();
        src.prepare_key(KEY).await.unwrap();
        assert_eq!(
            mock.hits(),
            1,
            "second prepare_key must attach, not re-download"
        );
        assert_eq!(src.size(KEY).await.unwrap(), Some(body.len() as u64));

        // Record-misaligned ranged reads reconstruct the body exactly.
        let mut out = Vec::new();
        let mut offset = 0u64;
        loop {
            let chunk = src.get_chunk(KEY, offset, 97).await.unwrap();
            if chunk.is_empty() {
                break;
            }
            offset += chunk.len() as u64;
            out.extend_from_slice(&chunk);
        }
        assert_eq!(out, body);

        // Transient-interruption release keeps the staged part: a fresh source
        // (resuming pod) attaches with no origin re-hit.
        src.release_job_resources().await.unwrap();
        let staging_b = TempDir::new().unwrap();
        let resumed = build_source(&server, staging_b.path(), Arc::clone(&store)).await;
        resumed.prepare_for_job().await.unwrap();
        resumed.prepare_key(KEY).await.unwrap();
        assert_eq!(mock.hits(), 1, "resume must not re-hit the origin");
        assert_eq!(resumed.get_chunk(KEY, 10, 25).await.unwrap(), &body[10..35]);

        // Per-part delete is idempotent; the terminal sweep forces a clean
        // re-download on the next attempt (the fixed-source-after-pause guarantee).
        resumed.cleanup_key(KEY).await.unwrap();
        assert_eq!(resumed.size(KEY).await.unwrap(), None);
        resumed.cleanup_key(KEY).await.unwrap();
        resumed.prepare_key(KEY).await.unwrap();
        assert_eq!(mock.hits(), 2, "after delete, prepare_key re-downloads");
        resumed.cleanup_after_job().await.unwrap();
        let staging_c = TempDir::new().unwrap();
        let fresh = build_source(&server, staging_c.path(), store).await;
        assert_eq!(fresh.size(KEY).await.unwrap(), None);
    }

    #[tokio::test]
    async fn remote_zero_byte_object_stages_empty_part() {
        let server = MockServer::start();
        let mock = mock_get_object(&server, b"");
        let staging = TempDir::new().unwrap();
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());

        let src = build_source(&server, staging.path(), store).await;
        src.prepare_for_job().await.unwrap();
        src.prepare_key(KEY).await.unwrap();

        // A zero-byte origin object stages an empty part: size reports Some(0) (the
        // job loop's done-empty short-circuit), reads are empty, and the staged
        // marker makes prepare_key idempotent with no second origin hit.
        assert_eq!(src.size(KEY).await.unwrap(), Some(0));
        assert!(src.get_chunk(KEY, 0, 100).await.unwrap().is_empty());
        src.prepare_key(KEY).await.unwrap();
        assert_eq!(mock.hits(), 1);
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
