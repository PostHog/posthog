//! Multipart upload for large data files.
//!
//! `RecordBatchWriter::flush()` uploads each finished Parquet file through
//! `ObjectStore::put` -- a single PUT (~`target_file_size` bytes, 100 MB by default).
//! On real S3 that serialises the whole file on one connection and re-uploads
//! everything on a connection reset; measured under injected per-request latency it
//! cost deltalite ~4x more wall-clock than MERGE. delta-rs's own DataFusion writer
//! uses ~5 MB multipart parts for the same reason.
//!
//! The writer offers no hook to change this, but the store it writes through does:
//! `RecordBatchWriter::for_table` takes `table.object_store()`, which comes from the
//! table's `LogStore`. [`MultipartPutStore`] wraps an object store so that plain
//! overwrite `put`s above a size threshold become multipart uploads, and
//! [`MultipartLogStore`] wraps a log store to hand that store to the writer.
//!
//! Commit safety is deliberately untouched: log-store commit writes go through
//! `write_commit_entry` (delegated verbatim to the inner log store, preserving the
//! conditional-put `If-None-Match` behaviour), and any `put_opts` with a non-Overwrite
//! mode or a preconditioned option set is forwarded unmodified.

use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use deltalake::kernel::transaction::TransactionError;
use deltalake::logstore::{CommitOrBytes, LogStore, LogStoreConfig};
use futures::stream::BoxStream;
use object_store::path::Path;
use object_store::{
    GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore, PutMode,
    PutMultipartOptions, PutOptions, PutPayload, PutResult,
};
use uuid::Uuid;

/// Default size above which a single `put` becomes a multipart upload.
pub const DEFAULT_MULTIPART_THRESHOLD: usize = 64 * 1024 * 1024;
/// Part size for multipart uploads. Must be >= 5 MiB for S3; 16 MiB balances request
/// count against retry granularity.
pub const DEFAULT_MULTIPART_PART_SIZE: usize = 16 * 1024 * 1024;

/// An [`ObjectStore`] wrapper that turns large plain-overwrite `put`s into multipart
/// uploads and delegates everything else.
#[derive(Debug)]
pub struct MultipartPutStore {
    inner: Arc<dyn ObjectStore>,
    threshold: usize,
    part_size: usize,
}

impl MultipartPutStore {
    /// Wrap `inner`; `threshold` of 0 disables the rewrite (pure delegation).
    pub fn new(inner: Arc<dyn ObjectStore>, threshold: usize, part_size: usize) -> Self {
        Self {
            inner,
            threshold,
            part_size: part_size.max(5 * 1024 * 1024),
        }
    }

    /// Split `payload` into parts of at most `part_size` bytes, zero-copy (`Bytes`
    /// slices share the underlying allocation).
    fn split_parts(&self, payload: &PutPayload) -> Vec<PutPayload> {
        let mut parts: Vec<PutPayload> = Vec::new();
        let mut current: Vec<Bytes> = Vec::new();
        let mut current_len = 0usize;
        for chunk in payload.as_ref() {
            let mut offset = 0usize;
            while offset < chunk.len() {
                let room = self.part_size - current_len;
                let take = room.min(chunk.len() - offset);
                current.push(chunk.slice(offset..offset + take));
                current_len += take;
                offset += take;
                if current_len == self.part_size {
                    parts.push(PutPayload::from_iter(current.drain(..)));
                    current_len = 0;
                }
            }
        }
        if current_len > 0 {
            parts.push(PutPayload::from_iter(current.drain(..)));
        }
        parts
    }
}

impl std::fmt::Display for MultipartPutStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "MultipartPutStore({})", self.inner)
    }
}

#[async_trait]
impl ObjectStore for MultipartPutStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> object_store::Result<PutResult> {
        // Only rewrite the plain overwrite path (data-file uploads). Conditional puts
        // (PutMode::Create -- Delta log commits -- or Update) must keep their exact
        // semantics, so they are forwarded untouched.
        if self.threshold == 0
            || !matches!(opts.mode, PutMode::Overwrite)
            || payload.content_length() < self.threshold
        {
            return self.inner.put_opts(location, payload, opts).await;
        }

        let multipart_opts = PutMultipartOptions {
            tags: opts.tags,
            attributes: opts.attributes,
            extensions: opts.extensions,
        };
        let mut upload = self
            .inner
            .put_multipart_opts(location, multipart_opts)
            .await?;
        for part in self.split_parts(&payload) {
            if let Err(e) = upload.put_part(part).await {
                // Best-effort cleanup of the incomplete upload; the original error is
                // what the caller needs to see.
                drop(upload.abort().await);
                return Err(e);
            }
        }
        match upload.complete().await {
            Ok(result) => Ok(result),
            Err(e) => {
                drop(upload.abort().await);
                Err(e)
            }
        }
    }

    async fn put_multipart_opts(
        &self,
        location: &Path,
        opts: PutMultipartOptions,
    ) -> object_store::Result<Box<dyn MultipartUpload>> {
        self.inner.put_multipart_opts(location, opts).await
    }

    async fn get_opts(
        &self,
        location: &Path,
        options: GetOptions,
    ) -> object_store::Result<GetResult> {
        self.inner.get_opts(location, options).await
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[std::ops::Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        self.inner.get_ranges(location, ranges).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<Path>>,
    ) -> BoxStream<'static, object_store::Result<Path>> {
        self.inner.delete_stream(locations)
    }

    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        self.inner.list(prefix)
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        self.inner.list_with_offset(prefix, offset)
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> object_store::Result<ListResult> {
        self.inner.list_with_delimiter(prefix).await
    }

    async fn copy_opts(
        &self,
        from: &Path,
        to: &Path,
        options: object_store::CopyOptions,
    ) -> object_store::Result<()> {
        self.inner.copy_opts(from, to, options).await
    }

    async fn rename_opts(
        &self,
        from: &Path,
        to: &Path,
        options: object_store::RenameOptions,
    ) -> object_store::Result<()> {
        self.inner.rename_opts(from, to, options).await
    }
}

/// A [`LogStore`] wrapper whose `object_store()` returns a [`MultipartPutStore`] over
/// the inner store, so data files written by `RecordBatchWriter` (and read by the
/// probe/rewrite) go through the multipart-aware store while commit-entry writes stay
/// on the inner log store's own path.
pub struct MultipartLogStore {
    inner: Arc<dyn LogStore>,
    threshold: usize,
    part_size: usize,
}

impl MultipartLogStore {
    /// Wrap `inner` with the given multipart threshold and part size.
    pub fn new(inner: Arc<dyn LogStore>, threshold: usize, part_size: usize) -> Self {
        Self {
            inner,
            threshold,
            part_size,
        }
    }
}

impl std::fmt::Debug for MultipartLogStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "MultipartLogStore({})", self.inner.name())
    }
}

#[async_trait]
impl LogStore for MultipartLogStore {
    fn name(&self) -> String {
        // Delegated VERBATIM, not decorated: delta-rs's transaction layer string-matches
        // `log_store.name()` (`["LakeFSLogStore", "DefaultLogStore"]`) to decide between
        // the conditional-put commit path (LogBytes) and the tmp-commit + rename path.
        // A decorated name silently switched every commit onto the tmp-commit path,
        // which `DefaultLogStore::write_commit_entry` rejects with `unreachable!()`.
        // The wrapper changes nothing about commit behaviour, so it must present the
        // inner store's identity.
        self.inner.name()
    }

    async fn refresh(&self) -> deltalake::DeltaResult<()> {
        self.inner.refresh().await
    }

    async fn read_commit_entry(&self, version: u64) -> deltalake::DeltaResult<Option<Bytes>> {
        self.inner.read_commit_entry(version).await
    }

    async fn write_commit_entry(
        &self,
        version: u64,
        commit_or_bytes: CommitOrBytes,
        operation_id: Uuid,
    ) -> Result<(), TransactionError> {
        self.inner
            .write_commit_entry(version, commit_or_bytes, operation_id)
            .await
    }

    async fn abort_commit_entry(
        &self,
        version: u64,
        commit_or_bytes: CommitOrBytes,
        operation_id: Uuid,
    ) -> Result<(), TransactionError> {
        self.inner
            .abort_commit_entry(version, commit_or_bytes, operation_id)
            .await
    }

    async fn get_latest_version(&self, start_version: u64) -> deltalake::DeltaResult<u64> {
        self.inner.get_latest_version(start_version).await
    }

    fn object_store(&self, operation_id: Option<Uuid>) -> Arc<dyn ObjectStore> {
        Arc::new(MultipartPutStore::new(
            self.inner.object_store(operation_id),
            self.threshold,
            self.part_size,
        ))
    }

    fn root_object_store(&self, operation_id: Option<Uuid>) -> Arc<dyn ObjectStore> {
        Arc::new(MultipartPutStore::new(
            self.inner.root_object_store(operation_id),
            self.threshold,
            self.part_size,
        ))
    }

    fn config(&self) -> &LogStoreConfig {
        self.inner.config()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use object_store::memory::InMemory;
    use object_store::ObjectStoreExt;

    fn payload_of(len: usize) -> PutPayload {
        PutPayload::from_bytes(Bytes::from(vec![7u8; len]))
    }

    #[tokio::test]
    async fn small_put_is_delegated_and_readable() {
        let inner = Arc::new(InMemory::new());
        let store = MultipartPutStore::new(inner.clone(), 1024, 5 * 1024 * 1024);
        let path = Path::from("small");
        store.put(&path, payload_of(100)).await.unwrap();
        let got = inner.get(&path).await.unwrap().bytes().await.unwrap();
        assert_eq!(got.len(), 100);
    }

    #[tokio::test]
    async fn large_put_goes_multipart_and_content_is_identical() {
        let inner = Arc::new(InMemory::new());
        // Force multipart with a tiny threshold; part size is clamped to >= 5 MiB, so
        // use a payload bigger than one part to exercise splitting.
        let store = MultipartPutStore::new(inner.clone(), 1024, 5 * 1024 * 1024);
        let path = Path::from("large");
        let len = 11 * 1024 * 1024; // 3 parts at 5 MiB
        let mut data = Vec::with_capacity(len);
        for i in 0..len {
            data.push((i % 251) as u8);
        }
        let payload = PutPayload::from_bytes(Bytes::from(data.clone()));
        store.put(&path, payload).await.unwrap();
        let got = inner.get(&path).await.unwrap().bytes().await.unwrap();
        assert_eq!(got.as_ref(), data.as_slice(), "content must round-trip");
    }

    #[tokio::test]
    async fn conditional_puts_are_never_rewritten() {
        let inner = Arc::new(InMemory::new());
        let store = MultipartPutStore::new(inner.clone(), 1, 5 * 1024 * 1024);
        let path = Path::from("commit");
        let opts = PutOptions::from(PutMode::Create);
        store
            .put_opts(&path, payload_of(10_000), opts.clone())
            .await
            .unwrap();
        // Second Create on the same path must fail exactly as the inner store would --
        // this is the conditional-put semantics Delta commits rely on.
        let err = store.put_opts(&path, payload_of(10_000), opts).await;
        assert!(
            matches!(err, Err(object_store::Error::AlreadyExists { .. })),
            "{err:?}"
        );
    }

    #[test]
    fn split_parts_respects_part_size_and_preserves_bytes() {
        let store = MultipartPutStore::new(Arc::new(InMemory::new()), 1, 5 * 1024 * 1024);
        let a = Bytes::from(vec![1u8; 3 * 1024 * 1024]);
        let b = Bytes::from(vec![2u8; 9 * 1024 * 1024]);
        let payload = PutPayload::from_iter(vec![a, b]);
        let parts = store.split_parts(&payload);
        assert_eq!(parts.len(), 3); // 12 MiB at 5 MiB parts
        assert!(parts.iter().all(|p| p.content_length() <= 5 * 1024 * 1024));
        let total: usize = parts.iter().map(|p| p.content_length()).sum();
        assert_eq!(total, 12 * 1024 * 1024);
    }
}
