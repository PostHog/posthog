//! Multipart upload for large data files.
//!
//! The partition writer (`crate::writer`, like delta-rs's `RecordBatchWriter`)
//! uploads each finished Parquet file through `ObjectStore::put` -- a single PUT (~`target_file_size` bytes, 100 MB by default).
//! On real S3 that serialises the whole file on one connection and re-uploads
//! everything on a connection reset; measured under injected per-request latency it
//! cost deltalite ~4x more wall-clock than MERGE. delta-rs's own DataFusion writer
//! uses ~5 MB multipart parts for the same reason.
//!
//! The writer uploads through `table.object_store()`, which comes from the table's
//! `LogStore`. [`MultipartPutStore`] wraps an object store so that plain
//! overwrite `put`s above a size threshold become multipart uploads, and
//! [`MultipartLogStore`] wraps a log store to hand that store to the writer.
//!
//! Commit safety is deliberately untouched: log-store commit writes go through
//! `write_commit_entry` (delegated verbatim to the inner log store, preserving the
//! conditional-put `If-None-Match` behaviour), and any `put_opts` with a non-Overwrite
//! mode or a preconditioned option set is forwarded unmodified.
//!
//! [`MultipartLogStore`] can also answer the question that delta-rs asks before each
//! commit put ("what is the latest version?") without a LIST of the log; see
//! [`CommitProbe`].

use std::sync::{Arc, Mutex};
use std::time::Instant;

use async_trait::async_trait;
use bytes::Bytes;
use deltalake::kernel::transaction::TransactionError;
use deltalake::logstore::{CommitOrBytes, LogStore, LogStoreConfig};
use futures::stream::{BoxStream, StreamExt};
use metrics::counter;
use object_store::path::Path;
use object_store::{
    GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore, ObjectStoreExt,
    PutMode, PutMultipartOptions, PutOptions, PutPayload, PutResult,
};
use uuid::Uuid;

use crate::logprobe::{commit_path, probe_log, LogAnchor, LogProbe};

/// Default size above which a single `put` becomes a multipart upload.
pub const DEFAULT_MULTIPART_THRESHOLD: usize = 64 * 1024 * 1024;
/// Part size for multipart uploads. Must be >= 5 MiB for S3; 16 MiB balances request
/// count against retry granularity.
pub const DEFAULT_MULTIPART_PART_SIZE: usize = 16 * 1024 * 1024;

/// Objects deleted concurrently by the per-object `delete_stream` override.
const DELETE_CONCURRENCY: usize = 16;

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
        // object_store 0.13.2's S3 bulk `DeleteObjects` mis-parses a partial-error response
        // ("unknown variant `Code`, expected `Deleted` or `Error`") and times out on very large
        // delete batches (tables with many small files, e.g. GoogleAds) -- either failure aborts
        // the whole upsert and forces a fallback to the delta-rs MERGE. Delete each object
        // individually instead: a plain DELETE per key, run concurrently, sidesteps both the XML
        // parse bug and the batch-size timeout. Delete volume is small next to the rewrite.
        let inner = self.inner.clone();
        locations
            .map(move |loc| {
                let inner = inner.clone();
                async move {
                    let path = loc?;
                    inner.delete(&path).await?;
                    Ok(path)
                }
            })
            .buffer_unordered(DELETE_CONCURRENCY)
            .boxed()
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
/// the inner store, so data files written by the partition writer (and read by the
/// probe/rewrite) go through the multipart-aware store while commit-entry writes stay
/// on the inner log store's own path.
pub struct MultipartLogStore {
    inner: Arc<dyn LogStore>,
    threshold: usize,
    part_size: usize,
    commit_probe: Option<CommitProbe>,
}

/// Kill switch for the commit that probes the log in place of the LIST before the
/// commit put; `0` restores the LIST.
pub const OPTIMISTIC_COMMIT_VERSION_ENV: &str = "DELTALITE_OPTIMISTIC_COMMIT_VERSION";

/// The name of the delta-rs log store that commits with a create-only put.
const CONDITIONAL_PUT_LOG_STORE: &str = "DefaultLogStore";

/// Answers `get_latest_version(v)` for a snapshot at `v` with the log probe (see
/// [`crate::logprobe`]) in place of the LIST.
///
/// delta-rs lists the log before each commit put to learn the latest version. The LIST
/// proves two things: the commit file of `v` is there, and no later one is. The probe
/// proves the same two things with one GET and one HEAD, issued together: the next
/// commit file answers 404, and a commit file of the loaded table is unchanged. The
/// create-only put of `v + 1` stays the conflict check, as before.
///
/// The probe answers the first question for each `v` only. When delta-rs asks again for
/// the same `v`, its put lost a race, so that call and every later one use the LIST and
/// the conflict checks as before. The probe is also not used when the table was replaced
/// (the commit fails as a conflict, and the caller loads the table again), when a
/// request fails, or after `deadline`.
pub(crate) struct CommitProbe {
    anchor: LogAnchor,
    /// The end of the time in which a 404 for the next commit file is proof.
    deadline: Instant,
    state: Mutex<CommitProbeState>,
}

#[derive(Default)]
struct CommitProbeState {
    /// The last start version answered by the probe.
    answered: Option<u64>,
    /// Set when a call fell back to the LIST: the commit is contended.
    listing: bool,
}

impl CommitProbe {
    pub(crate) fn new(anchor: LogAnchor, deadline: Instant) -> Self {
        Self {
            anchor,
            deadline,
            state: Mutex::new(CommitProbeState::default()),
        }
    }

    fn state(&self) -> std::sync::MutexGuard<'_, CommitProbeState> {
        self.state.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Whether the probe may answer for `start_version`. A refusal is permanent.
    fn begin(&self, start_version: u64) -> bool {
        let mut state = self.state();
        if state.listing || state.answered == Some(start_version) || Instant::now() >= self.deadline
        {
            state.listing = true;
            return false;
        }
        state.answered = Some(start_version);
        true
    }

    fn use_listing(&self) {
        self.state().listing = true;
    }
}

fn replaced_table_error(version: u64) -> deltalake::DeltaTableError {
    deltalake::DeltaTableError::Transaction {
        source: TransactionError::LogStoreError {
            msg: format!(
                "the table was replaced or its log was cleaned up after version {version} \
                 was loaded; the commit was not written"
            ),
            source: "the log file that identifies the loaded table has changed".into(),
        },
    }
}

impl MultipartLogStore {
    /// Wrap `inner` with the given multipart threshold and part size.
    pub fn new(inner: Arc<dyn LogStore>, threshold: usize, part_size: usize) -> Self {
        Self {
            inner,
            threshold,
            part_size,
            commit_probe: None,
        }
    }

    /// Let `probe` answer the version question before a commit put. Ignored for a log
    /// store that does not commit with a create-only put (for example the DynamoDB
    /// lock store), which keeps its own `get_latest_version`.
    pub(crate) fn with_commit_probe(mut self, probe: CommitProbe) -> Self {
        if self.inner.name() == CONDITIONAL_PUT_LOG_STORE {
            self.commit_probe = Some(probe);
        }
        self
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
        let Some(probe) = &self.commit_probe else {
            return self.inner.get_latest_version(start_version).await;
        };
        if !probe.begin(start_version) {
            return self.inner.get_latest_version(start_version).await;
        }
        let outcome = match commit_path(self.inner.as_ref(), start_version + 1) {
            Some(next) => {
                let store = self.inner.root_object_store(None);
                probe_log(&store, &next, &probe.anchor).await
            }
            None => LogProbe::Unknown,
        };
        counter!("deltalite_commit_probe_total", "outcome" => outcome.label()).increment(1);
        match outcome {
            LogProbe::Current => Ok(start_version),
            LogProbe::Replaced => Err(replaced_table_error(start_version)),
            LogProbe::NewCommits | LogProbe::Unknown => {
                probe.use_listing();
                self.inner.get_latest_version(start_version).await
            }
        }
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

    /// A log store over an in-memory object store that counts the LIST-based version
    /// questions it answers.
    struct FakeLogStore {
        name: &'static str,
        store: Arc<dyn ObjectStore>,
        config: LogStoreConfig,
        latest: u64,
        listings: std::sync::atomic::AtomicUsize,
    }

    #[async_trait]
    impl LogStore for FakeLogStore {
        fn name(&self) -> String {
            self.name.to_string()
        }
        async fn read_commit_entry(&self, _: u64) -> deltalake::DeltaResult<Option<Bytes>> {
            Ok(None)
        }
        async fn write_commit_entry(
            &self,
            _: u64,
            _: CommitOrBytes,
            _: Uuid,
        ) -> Result<(), TransactionError> {
            Ok(())
        }
        async fn abort_commit_entry(
            &self,
            _: u64,
            _: CommitOrBytes,
            _: Uuid,
        ) -> Result<(), TransactionError> {
            Ok(())
        }
        async fn get_latest_version(&self, _: u64) -> deltalake::DeltaResult<u64> {
            self.listings
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            Ok(self.latest)
        }
        fn object_store(&self, _: Option<Uuid>) -> Arc<dyn ObjectStore> {
            self.store.clone()
        }
        fn root_object_store(&self, _: Option<Uuid>) -> Arc<dyn ObjectStore> {
            self.store.clone()
        }
        fn config(&self) -> &LogStoreConfig {
            &self.config
        }
    }

    fn commit_file(version: u64) -> Path {
        Path::from(format!("bucket/t/_delta_log/{version:020}.json"))
    }

    /// A log with commits `0..=5` behind a store named `name`, and the probe for it.
    async fn probed_store(
        name: &'static str,
        deadline: Instant,
    ) -> (Arc<FakeLogStore>, MultipartLogStore) {
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        for version in 0..=5 {
            store
                .put(&commit_file(version), payload_of(10))
                .await
                .unwrap();
        }
        let anchor = LogAnchor::from_meta(&store.head(&commit_file(3)).await.unwrap()).unwrap();
        let location = url::Url::parse("memory:///bucket/t").unwrap();
        let fake = Arc::new(FakeLogStore {
            name,
            store,
            config: LogStoreConfig::new(&location, Default::default()),
            latest: 9,
            listings: Default::default(),
        });
        let wrapped = MultipartLogStore::new(fake.clone(), 0, 0)
            .with_commit_probe(CommitProbe::new(anchor, deadline));
        (fake, wrapped)
    }

    fn listings(fake: &FakeLogStore) -> usize {
        fake.listings.load(std::sync::atomic::Ordering::SeqCst)
    }

    fn soon() -> Instant {
        Instant::now() + std::time::Duration::from_secs(60)
    }

    #[tokio::test]
    async fn the_probe_answers_once_for_each_version_and_then_the_listing_does() {
        let (fake, store) = probed_store(CONDITIONAL_PUT_LOG_STORE, soon()).await;

        assert_eq!(store.get_latest_version(5).await.unwrap(), 5);
        assert_eq!(
            listings(&fake),
            0,
            "no LIST while the next commit is absent"
        );

        // delta-rs asks again for the same version when its put lost a race.
        assert_eq!(store.get_latest_version(5).await.unwrap(), 9);
        assert_eq!(store.get_latest_version(9).await.unwrap(), 9);
        assert_eq!(listings(&fake), 2, "a contended commit stays on the LIST");
    }

    #[tokio::test]
    async fn a_commit_that_exists_sends_the_question_to_the_listing() {
        let (fake, store) = probed_store(CONDITIONAL_PUT_LOG_STORE, soon()).await;
        assert_eq!(store.get_latest_version(4).await.unwrap(), 9);
        assert_eq!(listings(&fake), 1);
    }

    #[tokio::test]
    async fn a_log_store_without_a_create_only_put_keeps_its_listing() {
        let (fake, store) = probed_store("S3DynamoDbLogStore", soon()).await;
        assert_eq!(store.get_latest_version(5).await.unwrap(), 9);
        assert_eq!(listings(&fake), 1);
    }

    #[tokio::test]
    async fn the_probe_is_not_used_after_its_deadline() {
        let (fake, store) = probed_store(CONDITIONAL_PUT_LOG_STORE, Instant::now()).await;
        assert_eq!(store.get_latest_version(5).await.unwrap(), 9);
        assert_eq!(listings(&fake), 1);
    }

    #[tokio::test]
    async fn a_replaced_table_fails_the_commit_as_a_conflict() {
        let (fake, store) = probed_store(CONDITIONAL_PUT_LOG_STORE, soon()).await;
        fake.store
            .put(&commit_file(3), payload_of(11))
            .await
            .unwrap();

        let err = store.get_latest_version(5).await.unwrap_err();
        assert_eq!(listings(&fake), 0);
        let mapped: crate::errors::Error = err.into();
        assert!(
            matches!(mapped, crate::errors::Error::Conflict(_)),
            "{mapped:?}"
        );
    }
}
