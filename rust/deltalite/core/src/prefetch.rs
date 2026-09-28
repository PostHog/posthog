//! Whole-object prefetch for Delta checkpoint Parquet files.
//!
//! A snapshot load reads the latest checkpoint through the kernel's Parquet reader, which
//! issues one ranged GET for the footer, one for the metadata and one per column chunk it
//! decodes: a dozen or more sequential round trips against a single object, each paid at
//! object-store latency. The load decodes nearly the whole file anyway (every live Add
//! action is materialised), so [`CheckpointPrefetchStore`] fetches the object once on its
//! first ranged read and serves every later range from memory.
//!
//! The rewrite is scoped to checkpoint files under `_delta_log/`. Data files must keep
//! their range reads: the probe reads only the PK columns of a file and the rewrite
//! streams row groups, so buffering a whole data file would defeat the memory bound.
//!
//! Objects above [`CheckpointCache::max_bytes`] fall through to plain range reads, and the
//! cache is meant to live for one load: [`crate::handle::TableHandle`] clears it after
//! every open and refresh so a long-lived handle does not pin checkpoint bytes between
//! upserts.

use std::collections::HashMap;
use std::ops::Range;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use bytes::Bytes;
use deltalake::kernel::transaction::TransactionError;
use deltalake::logstore::{CommitOrBytes, LogStore, LogStoreConfig};
use futures::stream::{BoxStream, StreamExt};
use metrics::counter;
use object_store::path::Path;
use object_store::{
    Attributes, GetOptions, GetRange, GetResult, GetResultPayload, ListResult, MultipartUpload,
    ObjectMeta, ObjectStore, ObjectStoreExt, PutMultipartOptions, PutOptions, PutPayload,
    PutResult,
};
use tokio::sync::OnceCell;
use tracing::debug;
use uuid::Uuid;

/// Largest checkpoint object fetched whole by default. A checkpoint this size describes
/// a table with hundreds of thousands of live files, whose snapshot the kernel holds in
/// memory anyway; the load's peak grows by at most this much while the fetch is in flight.
pub const DEFAULT_CHECKPOINT_PREFETCH_MAX_BYTES: u64 = 128 * 1024 * 1024;

/// Environment override for [`DEFAULT_CHECKPOINT_PREFETCH_MAX_BYTES`]; `0` disables the
/// prefetch entirely (every read passes through as a range read).
pub const CHECKPOINT_PREFETCH_MAX_BYTES_ENV: &str = "DELTALITE_CHECKPOINT_PREFETCH_MAX_BYTES";

/// Whether `location` names a checkpoint Parquet file: `_delta_log/<v>.checkpoint.parquet`
/// or a multi-part / UUID-named `_delta_log/<v>.checkpoint.<...>.parquet`. Sidecar files
/// (`_delta_log/_sidecars/<uuid>.parquet`) are deliberately excluded.
pub fn is_checkpoint_file(location: &Path) -> bool {
    let in_log = location.parts().any(|part| part.as_ref() == "_delta_log");
    let name = location.filename().unwrap_or_default();
    in_log && name.ends_with(".parquet") && name.contains(".checkpoint.")
}

#[derive(Debug, Clone)]
enum Fetched {
    Cached {
        meta: ObjectMeta,
        bytes: Bytes,
    },
    /// The object is larger than the cache allows; its reads pass through untouched.
    TooLarge,
}

/// Per-load memory of whole checkpoint objects, shared by every store view of one table.
///
/// Concurrent readers of the same object wait on one fetch (`OnceCell`) instead of each
/// issuing their own whole-object GET.
#[derive(Debug)]
pub struct CheckpointCache {
    max_bytes: u64,
    entries: Mutex<HashMap<Path, Arc<OnceCell<Fetched>>>>,
}

impl CheckpointCache {
    /// A cache that fetches objects up to `max_bytes` whole; `0` disables prefetching.
    pub fn new(max_bytes: u64) -> Self {
        Self {
            max_bytes,
            entries: Mutex::new(HashMap::new()),
        }
    }

    /// Size bound from [`CHECKPOINT_PREFETCH_MAX_BYTES_ENV`], else the default. Parsed
    /// here rather than through `limits::env_usize` because `0` is a valid setting.
    pub fn from_env() -> Self {
        let max = match std::env::var(CHECKPOINT_PREFETCH_MAX_BYTES_ENV) {
            Ok(v) => v.trim().parse::<u64>().unwrap_or_else(|_| {
                tracing::warn!(
                    var = CHECKPOINT_PREFETCH_MAX_BYTES_ENV,
                    value = %v,
                    "invalid value, using default"
                );
                DEFAULT_CHECKPOINT_PREFETCH_MAX_BYTES
            }),
            Err(_) => DEFAULT_CHECKPOINT_PREFETCH_MAX_BYTES,
        };
        Self::new(max)
    }

    /// Largest object this cache fetches whole.
    pub fn max_bytes(&self) -> u64 {
        self.max_bytes
    }

    /// Drop every cached object.
    pub fn clear(&self) {
        self.lock().clear();
    }

    /// Bytes currently held (for observability and tests).
    pub fn cached_bytes(&self) -> u64 {
        self.lock()
            .values()
            .filter_map(|cell| match cell.get() {
                Some(Fetched::Cached { bytes, .. }) => Some(bytes.len() as u64),
                _ => None,
            })
            .sum()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<Path, Arc<OnceCell<Fetched>>>> {
        // A poisoned map only means another reader panicked mid-insert; the entries are
        // plain values, so continuing is safe.
        self.entries
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn cell(&self, location: &Path) -> Arc<OnceCell<Fetched>> {
        self.lock().entry(location.clone()).or_default().clone()
    }

    /// Record that `location` is too large without touching the store. A ranged read
    /// ending past the bound proves the object is larger than the bound, so the
    /// whole-object GET can be skipped rather than started and abandoned.
    fn mark_too_large(&self, location: &Path) {
        let cell = self.cell(location);
        drop(cell.set(Fetched::TooLarge));
    }

    fn exceeds(&self, ranges: &[Range<u64>]) -> bool {
        ranges.iter().any(|r| r.end > self.max_bytes)
    }

    async fn get_or_fetch(
        &self,
        inner: &Arc<dyn ObjectStore>,
        location: &Path,
    ) -> object_store::Result<Fetched> {
        let cell = self.cell(location);
        let fetched = cell
            .get_or_try_init(|| async {
                let result = inner.get(location).await?;
                if result.meta.size > self.max_bytes {
                    debug!(
                        path = %location,
                        size = result.meta.size,
                        max = self.max_bytes,
                        "checkpoint exceeds the prefetch bound; reading it by range"
                    );
                    counter!("deltalite_checkpoint_prefetch_total", "outcome" => "too_large")
                        .increment(1);
                    return Ok::<_, object_store::Error>(Fetched::TooLarge);
                }
                let meta = result.meta.clone();
                let bytes = result.bytes().await?;
                debug!(path = %location, size = bytes.len(), "prefetched checkpoint");
                counter!("deltalite_checkpoint_prefetch_total", "outcome" => "fetched")
                    .increment(1);
                Ok(Fetched::Cached { meta, bytes })
            })
            .await?;
        Ok(fetched.clone())
    }
}

/// An [`ObjectStore`] wrapper that serves ranged reads of checkpoint files from a
/// whole-object fetch and delegates everything else.
#[derive(Debug)]
pub struct CheckpointPrefetchStore {
    inner: Arc<dyn ObjectStore>,
    cache: Arc<CheckpointCache>,
}

impl CheckpointPrefetchStore {
    /// Wrap `inner`, sharing `cache` with any other view of the same table.
    pub fn new(inner: Arc<dyn ObjectStore>, cache: Arc<CheckpointCache>) -> Self {
        Self { inner, cache }
    }

    /// Only plain reads are served from memory; HEAD and preconditioned or versioned
    /// reads carry semantics the cached copy cannot honour.
    fn serves(&self, location: &Path, options: &GetOptions) -> bool {
        is_checkpoint_file(location)
            && !options.head
            && options.if_match.is_none()
            && options.if_none_match.is_none()
            && options.if_modified_since.is_none()
            && options.if_unmodified_since.is_none()
            && options.version.is_none()
    }

    fn resolve(range: Option<&GetRange>, len: u64) -> Range<u64> {
        match range {
            None => 0..len,
            Some(GetRange::Bounded(r)) => Self::clamp(r, len),
            Some(GetRange::Offset(offset)) => (*offset).min(len)..len,
            Some(GetRange::Suffix(n)) => len.saturating_sub(*n)..len,
        }
    }

    fn clamp(range: &Range<u64>, len: u64) -> Range<u64> {
        let start = range.start.min(len);
        start..range.end.min(len).max(start)
    }

    fn slice(bytes: &Bytes, range: &Range<u64>) -> Bytes {
        bytes.slice(range.start as usize..range.end as usize)
    }
}

impl std::fmt::Display for CheckpointPrefetchStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "CheckpointPrefetchStore({})", self.inner)
    }
}

#[async_trait]
impl ObjectStore for CheckpointPrefetchStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> object_store::Result<PutResult> {
        self.inner.put_opts(location, payload, opts).await
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
        if !self.serves(location, &options) {
            return self.inner.get_opts(location, options).await;
        }
        if let Some(GetRange::Bounded(range)) = &options.range {
            if self.cache.exceeds(std::slice::from_ref(range)) {
                self.cache.mark_too_large(location);
            }
        }
        match self.cache.get_or_fetch(&self.inner, location).await? {
            Fetched::TooLarge => self.inner.get_opts(location, options).await,
            Fetched::Cached { meta, bytes } => {
                let range = Self::resolve(options.range.as_ref(), bytes.len() as u64);
                let slice = Self::slice(&bytes, &range);
                Ok(GetResult {
                    payload: GetResultPayload::Stream(
                        futures::stream::once(async move { Ok(slice) }).boxed(),
                    ),
                    meta,
                    range,
                    attributes: Attributes::default(),
                })
            }
        }
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        if !is_checkpoint_file(location) {
            return self.inner.get_ranges(location, ranges).await;
        }
        if self.cache.exceeds(ranges) {
            self.cache.mark_too_large(location);
        }
        match self.cache.get_or_fetch(&self.inner, location).await? {
            Fetched::TooLarge => self.inner.get_ranges(location, ranges).await,
            Fetched::Cached { bytes, .. } => {
                let len = bytes.len() as u64;
                Ok(ranges
                    .iter()
                    .map(|r| Self::slice(&bytes, &Self::clamp(r, len)))
                    .collect())
            }
        }
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

/// A [`LogStore`] wrapper whose stores prefetch checkpoint files. The kernel engine that
/// reads checkpoints is built from `root_object_store()` (the trait's default `engine()`),
/// so wrapping both store accessors is enough to route every snapshot load through the
/// cache; commit-entry reads and writes stay on the inner log store's own path.
pub struct CheckpointPrefetchLogStore {
    inner: Arc<dyn LogStore>,
    cache: Arc<CheckpointCache>,
}

impl CheckpointPrefetchLogStore {
    /// Wrap `inner`, prefetching through `cache`.
    pub fn new(inner: Arc<dyn LogStore>, cache: Arc<CheckpointCache>) -> Self {
        Self { inner, cache }
    }

    /// The cache this wrapper serves from.
    pub fn cache(&self) -> &Arc<CheckpointCache> {
        &self.cache
    }
}

impl std::fmt::Debug for CheckpointPrefetchLogStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "CheckpointPrefetchLogStore({})", self.inner.name())
    }
}

#[async_trait]
impl LogStore for CheckpointPrefetchLogStore {
    fn name(&self) -> String {
        // Verbatim for the same reason as `MultipartLogStore::name`: delta-rs picks the
        // commit path by string-matching this name.
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
        Arc::new(CheckpointPrefetchStore::new(
            self.inner.object_store(operation_id),
            self.cache.clone(),
        ))
    }

    fn root_object_store(&self, operation_id: Option<Uuid>) -> Arc<dyn ObjectStore> {
        Arc::new(CheckpointPrefetchStore::new(
            self.inner.root_object_store(operation_id),
            self.cache.clone(),
        ))
    }

    fn config(&self) -> &LogStoreConfig {
        self.inner.config()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use object_store::memory::InMemory;

    use super::*;

    /// Counts GETs reaching the wrapped store: whole or ranged `get_opts` as one each,
    /// `get_ranges` as one per range (what an uncoalesced store would issue).
    #[derive(Debug)]
    struct Counting {
        inner: InMemory,
        gets: AtomicUsize,
    }

    impl std::fmt::Display for Counting {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            write!(f, "Counting")
        }
    }

    #[async_trait]
    impl ObjectStore for Counting {
        async fn put_opts(
            &self,
            location: &Path,
            payload: PutPayload,
            opts: PutOptions,
        ) -> object_store::Result<PutResult> {
            self.inner.put_opts(location, payload, opts).await
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
            self.gets.fetch_add(1, Ordering::SeqCst);
            self.inner.get_opts(location, options).await
        }
        async fn get_ranges(
            &self,
            location: &Path,
            ranges: &[Range<u64>],
        ) -> object_store::Result<Vec<Bytes>> {
            self.gets.fetch_add(ranges.len(), Ordering::SeqCst);
            self.inner.get_ranges(location, ranges).await
        }
        fn delete_stream(
            &self,
            locations: BoxStream<'static, object_store::Result<Path>>,
        ) -> BoxStream<'static, object_store::Result<Path>> {
            self.inner.delete_stream(locations)
        }
        fn list(
            &self,
            prefix: Option<&Path>,
        ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
            self.inner.list(prefix)
        }
        fn list_with_offset(
            &self,
            prefix: Option<&Path>,
            offset: &Path,
        ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
            self.inner.list_with_offset(prefix, offset)
        }
        async fn list_with_delimiter(
            &self,
            prefix: Option<&Path>,
        ) -> object_store::Result<ListResult> {
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

    const CHECKPOINT: &str = "bucket/table/_delta_log/00000000000000000010.checkpoint.parquet";

    fn body(len: usize) -> Bytes {
        Bytes::from((0..len).map(|i| (i % 251) as u8).collect::<Vec<u8>>())
    }

    async fn fixture(max_bytes: u64) -> (Arc<Counting>, CheckpointPrefetchStore, Bytes) {
        let counting = Arc::new(Counting {
            inner: InMemory::new(),
            gets: AtomicUsize::new(0),
        });
        let data = body(10_000);
        for path in [CHECKPOINT, "bucket/table/p=1/part-0.parquet"] {
            counting
                .put(&Path::from(path), PutPayload::from_bytes(data.clone()))
                .await
                .unwrap();
        }
        let store = CheckpointPrefetchStore::new(
            counting.clone(),
            Arc::new(CheckpointCache::new(max_bytes)),
        );
        (counting, store, data)
    }

    fn gets(counting: &Counting) -> usize {
        counting.gets.load(Ordering::SeqCst)
    }

    #[test]
    fn checkpoint_paths_are_recognised_and_nothing_else_is() {
        for yes in [
            "_delta_log/00000000000000000010.checkpoint.parquet",
            "b/t/_delta_log/00000000000000000010.checkpoint.parquet",
            "b/t/_delta_log/00000000000000000010.checkpoint.0000000001.0000000003.parquet",
            "b/t/_delta_log/00000000000000000010.checkpoint.0d5c4a1e-1111-2222-3333-444444444444.parquet",
        ] {
            assert!(is_checkpoint_file(&Path::from(yes)), "{yes}");
        }
        for no in [
            "b/t/_delta_log/00000000000000000010.json",
            "b/t/_delta_log/_last_checkpoint",
            "b/t/_delta_log/_sidecars/0d5c4a1e-1111-2222-3333-444444444444.parquet",
            "b/t/p=1/part-00000.checkpoint.parquet",
            "b/t/part-0.parquet",
        ] {
            assert!(!is_checkpoint_file(&Path::from(no)), "{no}");
        }
    }

    #[tokio::test]
    async fn ranged_reads_of_one_checkpoint_cost_one_get() {
        let (counting, store, data) = fixture(u64::MAX).await;
        let path = Path::from(CHECKPOINT);

        let footer = store.get_range(&path, 9_992..10_000).await.unwrap();
        let chunks = store
            .get_ranges(&path, &[0..100, 5_000..5_010, 9_000..9_500])
            .await
            .unwrap();
        let whole = store.get(&path).await.unwrap().bytes().await.unwrap();

        assert_eq!(gets(&counting), 1, "every range must come from one fetch");
        assert_eq!(footer, data.slice(9_992..10_000));
        assert_eq!(chunks[0], data.slice(0..100));
        assert_eq!(chunks[1], data.slice(5_000..5_010));
        assert_eq!(chunks[2], data.slice(9_000..9_500));
        assert_eq!(whole, data);
    }

    #[tokio::test]
    async fn suffix_and_offset_ranges_resolve_against_the_cached_length() {
        let (counting, store, data) = fixture(u64::MAX).await;
        let path = Path::from(CHECKPOINT);

        let suffix = store
            .get_opts(
                &path,
                GetOptions {
                    range: Some(GetRange::Suffix(8)),
                    ..Default::default()
                },
            )
            .await
            .unwrap();
        assert_eq!(suffix.range, 9_992..10_000);
        assert_eq!(suffix.bytes().await.unwrap(), data.slice(9_992..10_000));

        let offset = store
            .get_opts(
                &path,
                GetOptions {
                    range: Some(GetRange::Offset(9_990)),
                    ..Default::default()
                },
            )
            .await
            .unwrap();
        assert_eq!(offset.range, 9_990..10_000);
        assert_eq!(offset.bytes().await.unwrap(), data.slice(9_990..10_000));
        assert_eq!(gets(&counting), 1);
    }

    #[tokio::test]
    async fn data_files_and_head_requests_pass_through() {
        let (counting, store, _) = fixture(u64::MAX).await;
        let data_file = Path::from("bucket/table/p=1/part-0.parquet");

        store.get_range(&data_file, 0..10).await.unwrap();
        store.get_range(&data_file, 10..20).await.unwrap();
        assert_eq!(gets(&counting), 2, "data files keep their range reads");

        store.head(&Path::from(CHECKPOINT)).await.unwrap();
        assert_eq!(gets(&counting), 3, "HEAD is not served from the cache");
        assert_eq!(store.cache.cached_bytes(), 0);
    }

    #[tokio::test]
    async fn oversized_checkpoints_fall_through_to_range_reads() {
        let (counting, store, data) = fixture(1_000).await;
        let path = Path::from(CHECKPOINT);

        // The footer read ends past the bound, so the whole-object fetch is never issued.
        let footer = store.get_range(&path, 9_992..10_000).await.unwrap();
        let chunk = store.get_range(&path, 0..10).await.unwrap();

        assert_eq!(footer, data.slice(9_992..10_000));
        assert_eq!(chunk, data.slice(0..10));
        assert_eq!(
            gets(&counting),
            2,
            "one passthrough GET per range, no prefetch"
        );
        assert_eq!(store.cache.cached_bytes(), 0);
    }

    #[tokio::test]
    async fn a_small_first_range_still_bounds_on_the_real_size() {
        let (counting, store, data) = fixture(1_000).await;
        let path = Path::from(CHECKPOINT);

        // Nothing in the request reveals the size; the fetch discovers it and backs off.
        let chunk = store.get_range(&path, 0..10).await.unwrap();
        let again = store.get_range(&path, 20..30).await.unwrap();

        assert_eq!(chunk, data.slice(0..10));
        assert_eq!(again, data.slice(20..30));
        assert_eq!(
            gets(&counting),
            3,
            "one abandoned whole fetch, then a passthrough per range"
        );
        assert_eq!(store.cache.cached_bytes(), 0);
    }

    #[tokio::test]
    async fn clear_releases_the_bytes_and_the_next_read_fetches_again() {
        let (counting, store, _) = fixture(u64::MAX).await;
        let path = Path::from(CHECKPOINT);

        store.get_range(&path, 0..10).await.unwrap();
        assert_eq!(store.cache.cached_bytes(), 10_000);
        store.cache.clear();
        assert_eq!(store.cache.cached_bytes(), 0);

        store.get_range(&path, 0..10).await.unwrap();
        assert_eq!(gets(&counting), 2);
    }

    #[tokio::test]
    async fn a_zero_bound_disables_prefetching() {
        let (counting, store, _) = fixture(0).await;
        let path = Path::from(CHECKPOINT);
        store.get_range(&path, 0..10).await.unwrap();
        store.get_range(&path, 10..20).await.unwrap();
        assert_eq!(gets(&counting), 2, "every range passes straight through");
        assert_eq!(store.cache.cached_bytes(), 0);
    }
}
