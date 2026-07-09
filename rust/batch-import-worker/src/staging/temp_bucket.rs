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

/// Multipart part size for staging uploads. Each part is buffered in memory, and S3
/// caps a multipart upload at 10,000 parts, so this bounds both the upload's RAM
/// footprint (part_size x (concurrency + 1)) and the maximum staged object size
/// (part_size x 10,000). 64 MiB => 640 GiB max part. Config-overridable.
const DEFAULT_UPLOAD_PART_SIZE_BYTES: usize = 64 * 1024 * 1024;
/// In-flight part uploads while staging. Staging throughput is producer-bound
/// (origin download + gzip decode), so a small window keeps uploads fully
/// overlapped without multiplying memory. Config-overridable.
const DEFAULT_UPLOAD_CONCURRENCY: usize = 4;

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
    upload_part_size: usize,
    upload_concurrency: usize,
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
            upload_part_size: DEFAULT_UPLOAD_PART_SIZE_BYTES,
            upload_concurrency: DEFAULT_UPLOAD_CONCURRENCY,
            sizes: Mutex::new(HashMap::new()),
        }
    }

    /// Override the multipart upload geometry (part size bounds the max staged object
    /// size at part_size x 10,000; concurrency bounds upload memory). Used by
    /// `from_config` and by tests that force many small parts.
    pub fn with_upload_tuning(mut self, part_size: usize, concurrency: usize) -> Self {
        self.upload_part_size = part_size;
        self.upload_concurrency = concurrency;
        self
    }

    /// Construct from config, building the S3 client from the standard credential chain.
    pub async fn from_config(config: &Config, job_id: impl Into<String>) -> Result<Self, Error> {
        let store = create_temp_bucket_store(config).await?;
        Ok(
            Self::new(store, config.temp_bucket_prefix.clone(), job_id).with_upload_tuning(
                config.temp_bucket_upload_part_size_bytes as usize,
                config.temp_bucket_upload_concurrency,
            ),
        )
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

    fn quarantine_prefix(&self) -> String {
        format!("{}{}/quarantine/", self.prefix, self.job_id)
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

    /// Server-side move of every staged object into `quarantine/` under the job
    /// prefix. The quarantine location is never produced by `object_path`, so
    /// `size`/`read` (and therefore a resume) cannot attach to it, while
    /// `cleanup_job` and the bucket TTL still reclaim it. Per-object failures
    /// leave that object in place, which degrades to today's behavior at worst
    /// (a stale canonical object is unreachable for resume only if moved, so a
    /// failed move is logged loudly).
    async fn quarantine_job(&self) -> Result<(), Error> {
        let prefix = self.job_prefix();
        let quarantine_prefix = self.quarantine_prefix();
        let mut stream = self.store.list(Some(&prefix));
        let mut moves: Vec<(ObjectPath, ObjectPath)> = Vec::new();
        while let Some(item) = stream.next().await {
            match item {
                Ok(meta) => {
                    if meta.location.as_ref().starts_with(&quarantine_prefix) {
                        continue;
                    }
                    let name = meta
                        .location
                        .filename()
                        .unwrap_or("unnamed.data")
                        .to_string();
                    let to = ObjectPath::from(format!("{quarantine_prefix}{name}"));
                    moves.push((meta.location, to));
                }
                Err(e) => warn!("Failed to list staged objects under {prefix}: {e}"),
            }
        }
        for (from, to) in moves {
            if let Err(e) = self.store.copy(&from, &to).await {
                warn!("Failed to quarantine staged object {from}: {e}");
                continue;
            }
            if let Err(e) = self.store.delete(&from).await {
                warn!("Failed to delete staged object {from} after quarantining: {e}");
            }
        }
        self.sizes.lock().await.clear();
        Ok(())
    }

    async fn stage_part(&self, key: &str, mut plaintext: PlaintextStream) -> Result<u64, Error> {
        let path = self.object_path(key);
        let mut writer =
            BufWriter::with_capacity(Arc::clone(&self.store), path, self.upload_part_size)
                .with_max_concurrency(self.upload_concurrency);
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
            Ok(meta) => {
                // Cache the recovered size so a resumed job doesn't re-head the same
                // object on every prepare_key/read iteration. Invalidated by
                // cleanup_key/cleanup_job and by a NotFound read (object deleted
                // out-of-band, e.g. bucket TTL on a long-paused job).
                self.sizes.lock().await.insert(key.to_string(), meta.size);
                Ok(Some(meta.size))
            }
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
        match self
            .store
            .get_range(&self.object_path(key), offset..end_offset)
            .await
        {
            Ok(bytes) => {
                metrics::temp_bucket_read(started.elapsed().as_secs_f64());
                Ok(bytes.to_vec())
            }
            Err(object_store::Error::NotFound { .. }) => {
                // The object was deleted out-of-band (e.g. bucket TTL) after its size
                // was cached. Drop the stale entry so the next prepare_key sees the
                // key as unstaged and re-ingests from origin instead of failing every
                // read against a cached size.
                self.sizes.lock().await.remove(key);
                Err(Error::msg(format!(
                    "Staged object for key {key} disappeared (deleted out-of-band); \
                     it will be re-staged on the next attempt"
                )))
            }
            Err(e) => {
                Err(Error::from(e).context(format!("Failed to read staged object for key: {key}")))
            }
        }
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

    fn backend_with_store() -> (Arc<InMemory>, TempBucketBackend) {
        let store = Arc::new(InMemory::new());
        let be = TempBucketBackend::new(store.clone(), "batch-import-staging/", "job-TEST");
        (store, be)
    }

    async fn quarantined_bytes(store: &Arc<InMemory>, key: &str) -> Option<Vec<u8>> {
        let path = ObjectPath::from(format!(
            "batch-import-staging/job-TEST/quarantine/{}.data",
            sanitize_key(key)
        ));
        let result = store.get(&path).await.ok()?;
        Some(result.bytes().await.ok()?.to_vec())
    }

    #[tokio::test]
    async fn quarantine_preserves_bytes_and_detaches_resume() {
        let (store, be) = backend_with_store();
        let body = b"{\"a\":1}\nnot json at all\n";
        stage_bytes(&be, "2024-01-01:00", body).await;

        be.quarantine_job().await.unwrap();

        // The canonical object is gone: a resume's size/read (and therefore
        // prepare_key's head-based attach) must not see the stale bytes.
        assert_eq!(be.size("2024-01-01:00").await.unwrap(), None);
        assert!(be.read("2024-01-01:00", 0, 100).await.is_err());

        // The exact failing bytes are preserved for post-mortem.
        assert_eq!(
            quarantined_bytes(&store, "2024-01-01:00").await.as_deref(),
            Some(body.as_slice())
        );
    }

    #[tokio::test]
    async fn quarantine_is_idempotent_and_swept_by_cleanup_job() {
        let (store, be) = backend_with_store();
        stage_bytes(&be, "k1", b"data-one").await;
        stage_bytes(&be, "k2", b"data-two").await;

        be.quarantine_job().await.unwrap();
        // A second pause on the same job must not double-move or error.
        be.quarantine_job().await.unwrap();
        assert_eq!(
            quarantined_bytes(&store, "k1").await.as_deref(),
            Some(b"data-one".as_slice())
        );
        assert_eq!(
            quarantined_bytes(&store, "k2").await.as_deref(),
            Some(b"data-two".as_slice())
        );

        // Re-staging after quarantine works (the resume path), and the fresh
        // canonical object coexists with the quarantined evidence.
        stage_bytes(&be, "k1", b"data-one-fixed").await;
        assert_eq!(be.size("k1").await.unwrap(), Some(14));
        assert_eq!(
            quarantined_bytes(&store, "k1").await.as_deref(),
            Some(b"data-one".as_slice())
        );

        // Terminal cleanup reclaims quarantine along with everything else, so
        // quarantined evidence cannot outlive the job inside the bucket.
        be.cleanup_job().await.unwrap();
        assert!(quarantined_bytes(&store, "k1").await.is_none());
        assert!(quarantined_bytes(&store, "k2").await.is_none());
        assert_eq!(be.size("k1").await.unwrap(), None);
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
        crate::staging::backend::assert_reads_reconstruct(
            &be,
            "2024-01-01:00",
            crate::staging::backend::TEST_RECORD_BODY,
        )
        .await;
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

    #[tokio::test]
    async fn multi_part_upload_is_byte_identical_to_oracle() {
        // Force a genuine multi-part upload (part size far below the body) and prove
        // the assembled object is byte-identical to the LocalDiskBackend oracle —
        // the guarantee that raising TEMP_BUCKET_UPLOAD_PART_SIZE_BYTES only moves
        // the size wall, never the bytes.
        let dir = TempDir::new().unwrap();
        let raw = dir.path().join("part.raw");
        let body: String = (0..2_000).map(|i| format!("{{\"n\":{i}}}\n")).collect();
        {
            let file = std::fs::File::create(&raw).unwrap();
            let mut enc = GzEncoder::new(file, Compression::default());
            enc.write_all(body.as_bytes()).unwrap();
            enc.finish().unwrap();
        }

        let local = LocalDiskBackend::new(dir.path().join("job-X"));
        // 1 KiB parts x concurrency 2: the ~22 KB body spans many parts.
        let temp = TempBucketBackend::new(Arc::new(InMemory::new()), "p/", "job-MP")
            .with_upload_tuning(1024, 2);

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
        assert!(
            temp_size > 10 * 1024,
            "body must span many 1 KiB parts (got {temp_size} bytes)"
        );
        let local_bytes = local.read("k", 0, local_size).await.unwrap();
        let temp_bytes = temp.read("k", 0, temp_size).await.unwrap();
        assert_eq!(local_bytes, temp_bytes);
        // Misaligned ranged reads over the multi-part object reconstruct exactly.
        crate::staging::backend::assert_reads_reconstruct(
            &temp,
            "k2",
            crate::staging::backend::TEST_RECORD_BODY,
        )
        .await;
    }

    #[tokio::test]
    async fn head_size_is_cached_and_invalidated_by_notfound_read() {
        // Cold size() recovers via head and caches; an out-of-band deletion (bucket
        // TTL, manual sweep) surfaces as a NotFound read that must invalidate the
        // cache so the next prepare_key re-ingests instead of failing forever.
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let body = b"cached body\n";
        {
            let warm = TempBucketBackend::new(Arc::clone(&store), "p/", "job-C");
            stage_bytes(&warm, "k", body).await;
        }

        let cold = TempBucketBackend::new(Arc::clone(&store), "p/", "job-C");
        assert_eq!(cold.size("k").await.unwrap(), Some(body.len() as u64));

        // Delete the object out-of-band. The cached size still answers (proves the
        // head result was cached — no re-head per call)...
        store
            .delete(&ObjectPath::from("p/job-C/k.data"))
            .await
            .unwrap();
        assert_eq!(cold.size("k").await.unwrap(), Some(body.len() as u64));

        // ...but a read observes NotFound, invalidates the entry, and the next
        // size() sees the key as unstaged (the re-ingest trigger).
        let err = cold.read("k", 0, 10).await.unwrap_err();
        assert!(
            err.to_string().contains("disappeared"),
            "unexpected error: {err:#}"
        );
        assert_eq!(cold.size("k").await.unwrap(), None);
    }
}
