use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Error};
use async_trait::async_trait;
use futures_util::StreamExt;
use object_store::buffered::BufWriter;
use object_store::path::Path as ObjectPath;
use object_store::{ObjectStore, ObjectStoreExt};
use tokio::io::AsyncWriteExt;
use tokio::sync::Mutex;
use tracing::warn;

use crate::config::Config;
use crate::metrics;

use super::backend::{sanitize_key, PlaintextStream, StagingBackend};
use super::s3_client::create_temp_bucket_store;

/// Stages part plaintext as an object in an internal S3 "temp bucket", reading it back
/// with ranged GETs. Layout: `{prefix}{job_id}/{sanitized_key}.data`.
///
/// A part is written via a multipart-capable `BufWriter` that only completes the upload on
/// full success, so a failed ingest leaves no readable object — `head`/`read` never observe
/// a torn part. That atomicity is what makes head-based resume (skip re-ingest when a
/// completed object already exists) safe.
pub struct TempBucketBackend {
    store: Arc<dyn ObjectStore>,
    // Normalized to end with '/'.
    prefix: String,
    job_id: String,
    // Sizes recorded at stage time; on a cold process they are recovered via `head`.
    sizes: Mutex<HashMap<String, u64>>,
}

impl TempBucketBackend {
    /// Construct from an existing store (used by tests with in-memory / dev stores).
    pub fn new(
        store: Arc<dyn ObjectStore>,
        prefix: impl Into<String>,
        job_id: impl Into<String>,
    ) -> Self {
        let mut prefix = prefix.into();
        if !prefix.is_empty() && !prefix.ends_with('/') {
            prefix.push('/');
        }
        Self {
            store,
            prefix,
            job_id: job_id.into(),
            sizes: Mutex::new(HashMap::new()),
        }
    }

    /// Construct from config, building the S3 client from the standard credential chain.
    pub async fn from_config(config: &Config, job_id: impl Into<String>) -> Result<Self, Error> {
        let store = create_temp_bucket_store(config).await?;
        Ok(Self::new(store, config.temp_bucket_prefix.clone(), job_id))
    }

    fn object_path(&self, key: &str) -> ObjectPath {
        ObjectPath::from(format!(
            "{}{}/{}.data",
            self.prefix,
            self.job_id,
            sanitize_key(key)
        ))
    }

    fn job_prefix(&self) -> ObjectPath {
        ObjectPath::from(format!("{}{}/", self.prefix, self.job_id))
    }
}

#[async_trait]
impl StagingBackend for TempBucketBackend {
    async fn cleanup_job(&self) -> Result<(), Error> {
        let prefix = self.job_prefix();
        let mut stream = self.store.list(Some(&prefix));
        while let Some(item) = stream.next().await {
            match item {
                Ok(meta) => {
                    if let Err(e) = self.store.delete(&meta.location).await {
                        warn!("Failed to delete staged object {}: {e}", meta.location);
                    }
                }
                Err(e) => warn!("Failed to list staged objects under {prefix}: {e}"),
            }
        }
        self.sizes.lock().await.clear();
        Ok(())
    }

    async fn stage_part(&self, key: &str, mut plaintext: PlaintextStream) -> Result<u64, Error> {
        let path = self.object_path(key);
        let mut writer = BufWriter::new(Arc::clone(&self.store), path);
        let started = Instant::now();

        let mut total: u64 = 0;
        while let Some(block) = plaintext.next().await {
            match block {
                Ok(block) => {
                    if let Err(e) = writer.write_all(&block).await {
                        abort_quietly(&mut writer, key).await;
                        return Err(Error::from(e)
                            .context(format!("Failed to write staged data for key: {key}")));
                    }
                    total += block.len() as u64;
                }
                Err(e) => {
                    // Decode/ceiling error from the pipeline: abort so no readable object
                    // is left, and preserve the (possibly user-facing) error chain.
                    abort_quietly(&mut writer, key).await;
                    return Err(e.context(format!("Failed to stage part for key: {key}")));
                }
            }
        }

        // shutdown() completes the multipart upload — the object becomes visible only here.
        writer
            .shutdown()
            .await
            .with_context(|| format!("Failed to complete staged upload for key: {key}"))?;

        self.sizes.lock().await.insert(key.to_string(), total);
        metrics::temp_bucket_part_staged(total, started.elapsed().as_secs_f64());
        Ok(total)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        if let Some(size) = self.sizes.lock().await.get(key).copied() {
            return Ok(Some(size));
        }
        match self.store.head(&self.object_path(key)).await {
            Ok(meta) => Ok(Some(meta.size)),
            Err(object_store::Error::NotFound { .. }) => Ok(None),
            Err(e) => {
                Err(Error::from(e).context(format!("Failed to head staged object for key: {key}")))
            }
        }
    }

    async fn read(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let total_size = match self.size(key).await? {
            Some(s) => s,
            None => return Err(Error::msg(format!("Key not staged: {key}"))),
        };

        if total_size == 0 || offset >= total_size {
            return Ok(Vec::new());
        }

        let end_offset = std::cmp::min(offset + size, total_size);
        let started = Instant::now();
        let bytes = self
            .store
            .get_range(&self.object_path(key), offset..end_offset)
            .await
            .with_context(|| format!("Failed to read staged object for key: {key}"))?;
        metrics::temp_bucket_read(started.elapsed().as_secs_f64());
        Ok(bytes.to_vec())
    }

    async fn cleanup_key(&self, key: &str) -> Result<(), Error> {
        match self.store.delete(&self.object_path(key)).await {
            Ok(()) => {}
            Err(object_store::Error::NotFound { .. }) => {}
            Err(e) => {
                return Err(Error::from(e)
                    .context(format!("Failed to delete staged object for key: {key}")))
            }
        }
        self.sizes.lock().await.remove(key);
        Ok(())
    }
}

/// Abort an in-flight multipart upload, logging (not failing) if the abort itself errors.
/// Atomicity holds either way — an aborted or failed upload leaves no readable object — but a
/// failed abort can orphan multipart parts until the bucket lifecycle rule reclaims them, so
/// make that visible to operators.
async fn abort_quietly(writer: &mut BufWriter, key: &str) {
    if let Err(abort_err) = writer.abort().await {
        warn!("Failed to abort staged upload for key {key}: {abort_err}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extractor::ExtractorType;
    use crate::staging::backend::LocalDiskBackend;
    use crate::staging::open_plaintext_stream;
    use bytes::Bytes;
    use flate2::{write::GzEncoder, Compression};
    use object_store::memory::InMemory;
    use std::io::Write;
    use tempfile::TempDir;
    use tokio::sync::mpsc;

    fn backend() -> TempBucketBackend {
        TempBucketBackend::new(
            Arc::new(InMemory::new()),
            "batch-import-staging/",
            "job-TEST",
        )
    }

    async fn stage_bytes(be: &TempBucketBackend, key: &str, data: &[u8]) -> u64 {
        let stream = PlaintextStream::from_chunks(vec![Bytes::copy_from_slice(data)]);
        be.stage_part(key, stream).await.unwrap()
    }

    #[tokio::test]
    async fn round_trip_read_slices() {
        let be = backend();
        let body = b"line one\nline two\nline three\n";
        let size = stage_bytes(&be, "2024-01-01:00", body).await;
        assert_eq!(size, body.len() as u64);
        assert_eq!(
            be.size("2024-01-01:00").await.unwrap(),
            Some(body.len() as u64)
        );

        assert_eq!(be.read("2024-01-01:00", 0, 1000).await.unwrap(), body);
        assert_eq!(be.read("2024-01-01:00", 9, 8).await.unwrap(), b"line two");
        assert_eq!(
            be.read("2024-01-01:00", 18, 1000).await.unwrap(),
            b"line three\n"
        );
        assert!(be
            .read("2024-01-01:00", body.len() as u64, 10)
            .await
            .unwrap()
            .is_empty());
    }

    #[tokio::test]
    async fn empty_part_reports_zero_and_reads_empty() {
        let be = backend();
        assert_eq!(stage_bytes(&be, "empty", b"").await, 0);
        assert_eq!(be.size("empty").await.unwrap(), Some(0));
        assert!(be.read("empty", 0, 100).await.unwrap().is_empty());
    }

    #[tokio::test]
    async fn size_none_and_read_errors_for_unstaged_key() {
        let be = backend();
        assert_eq!(be.size("missing").await.unwrap(), None);
        assert!(be.read("missing", 0, 10).await.is_err());
    }

    #[tokio::test]
    async fn misaligned_reads_reconstruct_body() {
        let be = backend();
        let body = b"{\"id\":1}\n{\"id\":2}\n{\"id\":3}\n{\"id\":4}\n";
        crate::staging::backend::assert_reads_reconstruct(&be, "2024-01-01:00", body).await;
    }

    #[tokio::test]
    async fn cross_backend_byte_identity_with_local_disk() {
        // The load-bearing guarantee: the same compressed part staged through the pipeline
        // yields identical bytes + size on both backends, so a part's offsets stay valid
        // when the staging backend is flipped.
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("part.raw");
        {
            let file = std::fs::File::create(&raw).unwrap();
            let mut enc = GzEncoder::new(file, Compression::default());
            // No trailing newline: exercises the appended-newline path on both backends.
            enc.write_all(b"{\"a\":1}\n{\"b\":2}\n{\"c\":3}").unwrap();
            enc.finish().unwrap();
        }

        let local = LocalDiskBackend::new(dir.path().join("job-X"));
        let temp = backend();

        let local_size = local
            .stage_part(
                "k",
                open_plaintext_stream(raw.clone(), ExtractorType::PlainGzip, 0),
            )
            .await
            .unwrap();
        let temp_size = temp
            .stage_part("k", open_plaintext_stream(raw, ExtractorType::PlainGzip, 0))
            .await
            .unwrap();

        assert_eq!(local_size, temp_size);
        let local_bytes = local.read("k", 0, local_size + 10).await.unwrap();
        let temp_bytes = temp.read("k", 0, temp_size + 10).await.unwrap();
        assert_eq!(local_bytes, temp_bytes);
        assert_eq!(local_bytes, b"{\"a\":1}\n{\"b\":2}\n{\"c\":3}\n");
    }

    #[tokio::test]
    async fn head_recovers_size_on_cold_process() {
        // Simulate a restart: a completed object exists, but a fresh backend has an empty
        // in-memory size map. It must recover size/read via head without re-staging.
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let body = b"resumed body\n";
        {
            let warm = TempBucketBackend::new(Arc::clone(&store), "p/", "job-R");
            stage_bytes(&warm, "k", body).await;
        }
        let cold = TempBucketBackend::new(store, "p/", "job-R");
        assert_eq!(cold.size("k").await.unwrap(), Some(body.len() as u64));
        assert_eq!(cold.read("k", 0, 1000).await.unwrap(), body);
    }

    #[tokio::test]
    async fn failed_stage_leaves_no_readable_object() {
        // A pipeline error mid-stream must abort the upload so head sees nothing — the
        // property that makes head-based resume safe (no torn parts).
        let be = backend();
        let (tx, rx) = mpsc::channel(4);
        tx.send(Ok(Bytes::from_static(b"partial data")))
            .await
            .unwrap();
        tx.send(Err(anyhow::anyhow!("decode blew up")))
            .await
            .unwrap();
        drop(tx);

        let result = be.stage_part("k", PlaintextStream::new(rx)).await;
        assert!(result.is_err());
        assert_eq!(be.size("k").await.unwrap(), None);
        assert!(be.read("k", 0, 10).await.is_err());
    }

    #[tokio::test]
    async fn cleanup_key_is_idempotent() {
        let be = backend();
        stage_bytes(&be, "k", b"data").await;
        be.cleanup_key("k").await.unwrap();
        assert_eq!(be.size("k").await.unwrap(), None);
        // Second delete of an absent object is a no-op.
        be.cleanup_key("k").await.unwrap();
    }

    #[tokio::test]
    async fn cleanup_job_sweeps_all_objects_under_prefix() {
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let be = TempBucketBackend::new(Arc::clone(&store), "batch-import-staging/", "job-S");
        stage_bytes(&be, "a", b"aaa").await;
        stage_bytes(&be, "b", b"bbb").await;

        // A sibling job's object must be left untouched by this job's sweep.
        let other =
            TempBucketBackend::new(Arc::clone(&store), "batch-import-staging/", "job-OTHER");
        stage_bytes(&other, "c", b"ccc").await;

        be.cleanup_job().await.unwrap();
        assert_eq!(be.size("a").await.unwrap(), None);
        assert_eq!(be.size("b").await.unwrap(), None);
        assert_eq!(other.size("c").await.unwrap(), Some(3));
        // Idempotent.
        be.cleanup_job().await.unwrap();
    }
}
