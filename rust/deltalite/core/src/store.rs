//! Multipart upload for large data files, and split ranged reads of them.
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
//! One S3 connection moves a few tens of MB/s, so a data file that is uploaded or read
//! on one connection spends most of its time on bandwidth, not on request latency. The
//! wrapper therefore uploads several parts of a file at once, and splits a large ranged
//! read of a data file (a whole row group for a rewrite) into concurrent requests. The
//! readers of the probe and the rewrite read through the same store.
//!
//! Commit safety is deliberately untouched: log-store commit writes go through
//! `write_commit_entry` (delegated verbatim to the inner log store, preserving the
//! conditional-put `If-None-Match` behaviour), and any `put_opts` with a non-Overwrite
//! mode or a preconditioned option set is forwarded unmodified.
//!
//! [`MultipartLogStore`] can also answer the question that delta-rs asks before each
//! commit put ("what is the latest version?") without a LIST of the log; see
//! [`CommitProbe`].

use std::ops::Range;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use async_trait::async_trait;
use bytes::Bytes;
use deltalake::kernel::transaction::TransactionError;
use deltalake::logstore::{CommitOrBytes, LogStore, LogStoreConfig};
use futures::stream::{BoxStream, FuturesUnordered, StreamExt, TryStreamExt};
use futures::FutureExt;
use metrics::counter;
use object_store::path::Path;
use object_store::{
    GetOptions, GetRange, GetResult, GetResultPayload, ListResult, MultipartUpload, ObjectMeta,
    ObjectStore, ObjectStoreExt, PutMode, PutMultipartOptions, PutOptions, PutPayload, PutResult,
};
use uuid::Uuid;

use crate::logprobe::{commit_path, probe_log, LogAnchor, LogProbe};
use crate::table::MultipartConfig;

/// Default size above which a single `put` becomes a multipart upload. One S3 stream
/// moves data much slower than a few streams in parallel, so a file of a few part sizes
/// already uploads faster as concurrent parts than as one PUT.
pub const DEFAULT_MULTIPART_THRESHOLD: usize = 16 * 1024 * 1024;
/// Default part size for multipart uploads. S3 needs at least 5 MiB per part.
pub const DEFAULT_MULTIPART_PART_SIZE: usize = 8 * 1024 * 1024;
/// Default number of parts of one upload in flight at once.
pub const DEFAULT_MULTIPART_CONCURRENCY: usize = 4;
/// Multipart threshold when parts upload one after another: a serial multipart upload
/// is slower than one PUT of the same bytes, so it is used only for large files, where a
/// connection reset must not restart the whole upload.
pub const SERIAL_MULTIPART_THRESHOLD: usize = 64 * 1024 * 1024;
/// Part size when parts upload one after another.
pub const SERIAL_MULTIPART_PART_SIZE: usize = 16 * 1024 * 1024;
/// Default request size of a split ranged read of a data file.
pub const DEFAULT_RANGE_GET_PART_SIZE: usize = 8 * 1024 * 1024;
/// Default number of requests of one split ranged read in flight at once.
pub const DEFAULT_RANGE_GET_CONCURRENCY: usize = 4;

/// Gap below which two requested ranges are read with one request, as `object_store`
/// coalesces them.
const RANGE_COALESCE_BYTES: u64 = object_store::OBJECT_STORE_COALESCE_DEFAULT;

/// Objects deleted concurrently by the per-object `delete_stream` override.
const DELETE_CONCURRENCY: usize = 16;

/// An [`ObjectStore`] wrapper that turns large plain-overwrite `put`s into multipart
/// uploads with concurrent parts, splits large ranged reads of data files into
/// concurrent requests, and delegates everything else.
///
/// Neither rewrite adds memory: the parts of an upload are slices of the payload the
/// caller already holds, and a split read streams each request into its place in one
/// buffer of the size that a single request returns.
#[derive(Debug)]
pub struct MultipartPutStore {
    inner: Arc<dyn ObjectStore>,
    config: MultipartConfig,
}

impl MultipartPutStore {
    /// Wrap `inner`; a `threshold` of 0 disables the upload rewrite and a
    /// `range_concurrency` of 1 disables the read split.
    pub fn new(inner: Arc<dyn ObjectStore>, config: MultipartConfig) -> Self {
        Self {
            inner,
            config: MultipartConfig {
                part_size: config.part_size.max(5 * 1024 * 1024),
                concurrency: config.concurrency.max(1),
                range_part_size: config.range_part_size.max(1),
                range_concurrency: config.range_concurrency.max(1),
                ..config
            },
        }
    }

    /// Split `payload` into parts of at most `part_size` bytes, zero-copy (`Bytes`
    /// slices share the underlying allocation).
    fn split_parts(&self, payload: &PutPayload) -> Vec<PutPayload> {
        let part_size = self.config.part_size;
        let mut parts: Vec<PutPayload> = Vec::new();
        let mut current: Vec<Bytes> = Vec::new();
        let mut current_len = 0usize;
        for chunk in payload.as_ref() {
            let mut offset = 0usize;
            while offset < chunk.len() {
                let room = part_size - current_len;
                let take = room.min(chunk.len() - offset);
                current.push(chunk.slice(offset..offset + take));
                current_len += take;
                offset += take;
                if current_len == part_size {
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

    /// Upload every part with at most `concurrency` in flight. The part number of each
    /// part is fixed when `put_part` is called, in payload order, so the completion
    /// order does not change the assembled object.
    ///
    /// After a part fails no new part starts, and the parts already started run to the
    /// end: S3 may still store a part whose request was dropped, after the abort.
    async fn upload_parts(
        &self,
        upload: &mut Box<dyn MultipartUpload>,
        parts: Vec<PutPayload>,
    ) -> object_store::Result<()> {
        let mut parts = parts.into_iter();
        let mut in_flight = FuturesUnordered::new();
        let mut first_error = None;
        loop {
            while first_error.is_none() && in_flight.len() < self.config.concurrency {
                let Some(part) = parts.next() else { break };
                in_flight.push(upload.put_part(part));
            }
            match in_flight.next().await {
                Some(Err(e)) => {
                    first_error.get_or_insert(e);
                }
                Some(Ok(())) => {}
                None => break,
            }
        }
        match first_error {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    /// Whether ranged reads of `location` may be split: data files only. Log files keep
    /// their exact reads, which the checkpoint prefetch below this store serves.
    fn splits_reads_of(&self, location: &Path) -> bool {
        self.config.range_concurrency > 1 && !location.parts().any(|p| p.as_ref() == "_delta_log")
    }

    /// Read each range of `ranges` as requests of at most `range_part_size` bytes, each
    /// streamed into its own slice of the buffer of its range. The requests of all the
    /// ranges share one queue of `range_concurrency`.
    async fn get_split(
        &self,
        location: &Path,
        ranges: &[Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        let piece = self.config.range_part_size;
        let mut bufs = ranges
            .iter()
            .map(|r| {
                usize::try_from(r.end - r.start)
                    .map(|len| vec![0u8; len])
                    .map_err(|e| object_store::Error::Generic {
                        store: "deltalite",
                        source: Box::new(e),
                    })
            })
            .collect::<object_store::Result<Vec<Vec<u8>>>>()?;
        let reads: Vec<_> = ranges
            .iter()
            .zip(bufs.iter_mut())
            .flat_map(move |(range, buf)| {
                buf.chunks_mut(piece).enumerate().map(move |(i, dst)| {
                    let start = range.start + (i * piece) as u64;
                    self.read_into(location, start..start + dst.len() as u64, dst)
                        .boxed()
                })
            })
            .collect();
        futures::stream::iter(reads)
            .buffer_unordered(self.config.range_concurrency)
            .try_collect::<()>()
            .await?;
        Ok(bufs.into_iter().map(Bytes::from).collect())
    }

    async fn read_into(
        &self,
        location: &Path,
        range: Range<u64>,
        dst: &mut [u8],
    ) -> object_store::Result<()> {
        let options = GetOptions {
            range: Some(GetRange::Bounded(range.clone())),
            ..Default::default()
        };
        let mut result = self.inner.get_opts(location, options).await?;
        // A local file would stream in 8 KiB reads; read it straight into `dst` without
        // blocking a Tokio worker.
        if let GetResultPayload::File(file, _) = &mut result.payload {
            return read_file_into(file, location, &range, dst).await;
        }
        let mut stream = result.into_stream();
        let mut filled = 0usize;
        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            let end = filled + chunk.len();
            if end > dst.len() {
                return Err(short_read(location, &range, end));
            }
            dst[filled..end].copy_from_slice(&chunk);
            filled = end;
        }
        if filled != dst.len() {
            return Err(short_read(location, &range, filled));
        }
        Ok(())
    }
}

async fn read_file_into(
    file: &std::fs::File,
    location: &Path,
    range: &Range<u64>,
    dst: &mut [u8],
) -> object_store::Result<()> {
    use tokio::io::{AsyncReadExt, AsyncSeekExt};

    let generic = |e: std::io::Error| object_store::Error::Generic {
        store: "deltalite",
        source: Box::new(e),
    };
    let mut file = tokio::fs::File::from_std(file.try_clone().map_err(generic)?);
    file.seek(std::io::SeekFrom::Start(range.start))
        .await
        .map_err(generic)?;
    let mut filled = 0usize;
    while filled < dst.len() {
        match file.read(&mut dst[filled..]).await {
            Ok(0) => return Err(short_read(location, range, filled)),
            Ok(n) => filled += n,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
            Err(e) => return Err(generic(e)),
        }
    }
    Ok(())
}

fn short_read(location: &Path, range: &Range<u64>, got: usize) -> object_store::Error {
    object_store::Error::Generic {
        store: "deltalite",
        source: format!(
            "ranged read of {location} for bytes {range:?} returned {got} bytes, expected {}",
            range.end - range.start
        )
        .into(),
    }
}

/// `ranges` merged where they overlap or lie within [`RANGE_COALESCE_BYTES`] of each
/// other, sorted by start.
fn merge_ranges(ranges: &[Range<u64>]) -> Vec<Range<u64>> {
    let mut sorted: Vec<Range<u64>> = ranges.to_vec();
    sorted.sort_unstable_by_key(|r| r.start);
    let mut merged: Vec<Range<u64>> = Vec::with_capacity(sorted.len());
    for r in sorted {
        match merged.last_mut() {
            Some(last) if r.start <= last.end.saturating_add(RANGE_COALESCE_BYTES) => {
                last.end = last.end.max(r.end);
            }
            _ => merged.push(r),
        }
    }
    merged
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
        if self.config.threshold == 0
            || !matches!(opts.mode, PutMode::Overwrite)
            || payload.content_length() < self.config.threshold
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
        let parts = self.split_parts(&payload);
        if let Err(e) = self.upload_parts(&mut upload, parts).await {
            // Best-effort cleanup of the incomplete upload; the original error is what
            // the caller needs to see. The parts in flight finished above, and without
            // `complete` no object is created.
            drop(upload.abort().await);
            return Err(e);
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
        if !self.splits_reads_of(location) || ranges.iter().any(|r| r.start >= r.end) {
            return self.inner.get_ranges(location, ranges).await;
        }
        let merged = merge_ranges(ranges);
        let split_above = self.config.range_part_size as u64;
        if merged.iter().all(|m| m.end - m.start <= split_above) {
            return self.inner.get_ranges(location, ranges).await;
        }
        let fetched = self.get_split(location, &merged).await?;
        Ok(ranges
            .iter()
            .map(|r| {
                let i = merged.partition_point(|m| m.start <= r.start) - 1;
                let base = merged[i].start;
                fetched[i].slice((r.start - base) as usize..(r.end - base) as usize)
            })
            .collect())
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
    config: MultipartConfig,
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
    /// Wrap `inner` with the given upload and read settings.
    pub fn new(inner: Arc<dyn LogStore>, config: MultipartConfig) -> Self {
        Self {
            inner,
            config,
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
            self.config,
        ))
    }

    fn root_object_store(&self, operation_id: Option<Uuid>) -> Arc<dyn ObjectStore> {
        Arc::new(MultipartPutStore::new(
            self.inner.root_object_store(operation_id),
            self.config,
        ))
    }

    fn config(&self) -> &LogStoreConfig {
        self.inner.config()
    }
}

#[cfg(test)]
// Single ranges in arrays are requests of one range here, not ranges to expand.
#[allow(clippy::single_range_in_vec_init)]
mod tests {
    use super::*;
    use object_store::memory::InMemory;
    use object_store::ObjectStoreExt;

    fn payload_of(len: usize) -> PutPayload {
        PutPayload::from_bytes(Bytes::from(vec![7u8; len]))
    }

    const MIB: usize = 1024 * 1024;

    fn config(threshold: usize, part_size: usize, concurrency: usize) -> MultipartConfig {
        MultipartConfig {
            threshold,
            part_size,
            concurrency,
            range_part_size: DEFAULT_RANGE_GET_PART_SIZE,
            range_concurrency: 1,
        }
    }

    fn reads(range_part_size: usize, range_concurrency: usize) -> MultipartConfig {
        MultipartConfig {
            range_part_size,
            range_concurrency,
            ..config(0, 0, 1)
        }
    }

    fn pattern(len: usize) -> Vec<u8> {
        (0..len).map(|i| (i % 251) as u8).collect()
    }

    /// Counts requests and the most of them in flight at once. Each part upload and each
    /// read yields to the runtime before it runs, so the requests a caller issues
    /// together overlap; a part with a lower number yields more often, so the parts
    /// complete in reverse order.
    #[derive(Debug, Default)]
    struct Probe {
        gets: std::sync::atomic::AtomicUsize,
        in_flight: std::sync::atomic::AtomicUsize,
        max_in_flight: std::sync::atomic::AtomicUsize,
        aborted: std::sync::atomic::AtomicBool,
    }

    impl Probe {
        fn enter(&self) {
            use std::sync::atomic::Ordering::SeqCst;
            let now = self.in_flight.fetch_add(1, SeqCst) + 1;
            self.max_in_flight.fetch_max(now, SeqCst);
        }
        fn leave(&self) {
            self.in_flight
                .fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
        }
        fn max_in_flight(&self) -> usize {
            self.max_in_flight.load(std::sync::atomic::Ordering::SeqCst)
        }
        fn gets(&self) -> usize {
            self.gets.load(std::sync::atomic::Ordering::SeqCst)
        }
        fn aborted(&self) -> bool {
            self.aborted.load(std::sync::atomic::Ordering::SeqCst)
        }
    }

    async fn yield_times(n: usize) {
        for _ in 0..n {
            tokio::task::yield_now().await;
        }
    }

    #[derive(Debug)]
    struct ProbedUpload {
        inner: Box<dyn MultipartUpload>,
        probe: Arc<Probe>,
        next: usize,
        fail_part: Option<usize>,
    }

    #[async_trait]
    impl MultipartUpload for ProbedUpload {
        fn put_part(&mut self, data: PutPayload) -> object_store::UploadPart {
            let idx = self.next;
            self.next += 1;
            let fail = self.fail_part == Some(idx);
            let probe = self.probe.clone();
            let put = self.inner.put_part(data);
            Box::pin(async move {
                probe.enter();
                yield_times(16usize.saturating_sub(idx)).await;
                probe.leave();
                if fail {
                    return Err(object_store::Error::Generic {
                        store: "test",
                        source: format!("part {idx} failed").into(),
                    });
                }
                put.await
            })
        }
        async fn complete(&mut self) -> object_store::Result<PutResult> {
            self.inner.complete().await
        }
        async fn abort(&mut self) -> object_store::Result<()> {
            self.probe
                .aborted
                .store(true, std::sync::atomic::Ordering::SeqCst);
            self.inner.abort().await
        }
    }

    #[derive(Debug)]
    struct ProbedStore {
        inner: Arc<InMemory>,
        probe: Arc<Probe>,
        fail_part: Option<usize>,
    }

    impl ProbedStore {
        fn new(fail_part: Option<usize>) -> Arc<Self> {
            Arc::new(Self {
                inner: Arc::new(InMemory::new()),
                probe: Arc::default(),
                fail_part,
            })
        }
    }

    impl std::fmt::Display for ProbedStore {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            write!(f, "ProbedStore")
        }
    }

    #[async_trait]
    impl ObjectStore for ProbedStore {
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
            Ok(Box::new(ProbedUpload {
                inner: self.inner.put_multipart_opts(location, opts).await?,
                probe: self.probe.clone(),
                next: 0,
                fail_part: self.fail_part,
            }))
        }
        async fn get_opts(
            &self,
            location: &Path,
            options: GetOptions,
        ) -> object_store::Result<GetResult> {
            self.probe
                .gets
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            self.probe.enter();
            yield_times(4).await;
            self.probe.leave();
            self.inner.get_opts(location, options).await
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

    #[tokio::test]
    async fn small_put_is_delegated_and_readable() {
        let inner = Arc::new(InMemory::new());
        let store = MultipartPutStore::new(inner.clone(), config(1024, 5 * MIB, 4));
        let path = Path::from("small");
        store.put(&path, payload_of(100)).await.unwrap();
        let got = inner.get(&path).await.unwrap().bytes().await.unwrap();
        assert_eq!(got.len(), 100);
    }

    #[tokio::test]
    async fn multipart_uploads_assemble_parts_in_order_at_every_boundary() {
        // (payload length, chunk length of the payload, concurrency). Part size is 5 MiB.
        let cases = [
            (10 * MIB, MIB, 1),
            (10 * MIB, MIB, 4),
            (10 * MIB + 1, 3 * MIB + 7, 4),
            (15 * MIB - 1, 5 * MIB, 4),
            (5 * MIB + 1, 5 * MIB + 1, 4),
            (31 * MIB + 123, 7 * MIB + 5, 3),
            (31 * MIB + 123, 7 * MIB + 5, 16),
        ];
        for (len, chunk, concurrency) in cases {
            let store = ProbedStore::new(None);
            let wrapped = MultipartPutStore::new(store.clone(), config(1024, 5 * MIB, concurrency));
            let data = pattern(len);
            let payload = PutPayload::from_iter(data.chunks(chunk).map(Bytes::copy_from_slice));
            let path = Path::from("large");
            wrapped.put(&path, payload).await.unwrap();

            let got = store.inner.get(&path).await.unwrap().bytes().await.unwrap();
            assert!(
                got.as_ref() == data.as_slice(),
                "content differs for {len} bytes at concurrency {concurrency}"
            );
            let parts = len.div_ceil(5 * MIB);
            assert_eq!(
                store.probe.max_in_flight(),
                concurrency.min(parts),
                "parts in flight for {len} bytes at concurrency {concurrency}"
            );
        }
    }

    #[tokio::test]
    async fn a_failed_part_aborts_the_upload_and_creates_no_object() {
        // (failing part of 4, concurrency)
        for (fail_part, concurrency) in [(0, 1), (2, 1), (0, 4), (2, 4), (3, 4)] {
            let store = ProbedStore::new(Some(fail_part));
            let wrapped = MultipartPutStore::new(store.clone(), config(1024, 5 * MIB, concurrency));
            let path = Path::from("failed");
            let err = wrapped.put(&path, payload_of(20 * MIB)).await.unwrap_err();
            assert!(
                err.to_string()
                    .contains(&format!("part {fail_part} failed")),
                "{err}"
            );
            assert!(store.probe.aborted(), "the upload must be aborted");
            assert_eq!(
                store.probe.in_flight.load(std::sync::atomic::Ordering::SeqCst),
                0,
                "parts already started must finish before the abort (part {fail_part}, concurrency {concurrency})"
            );
            assert!(
                matches!(store.inner.head(&path).await, Err(object_store::Error::NotFound { .. })),
                "no object may exist after a failed upload (part {fail_part}, concurrency {concurrency})"
            );
        }
    }

    #[tokio::test]
    async fn conditional_puts_are_never_rewritten() {
        let inner = Arc::new(InMemory::new());
        let store = MultipartPutStore::new(inner.clone(), config(1, 5 * MIB, 4));
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
        let store = MultipartPutStore::new(Arc::new(InMemory::new()), config(1, 5 * MIB, 1));
        let a = Bytes::from(vec![1u8; 3 * 1024 * 1024]);
        let b = Bytes::from(vec![2u8; 9 * 1024 * 1024]);
        let payload = PutPayload::from_iter(vec![a, b]);
        let parts = store.split_parts(&payload);
        assert_eq!(parts.len(), 3); // 12 MiB at 5 MiB parts
        assert!(parts.iter().all(|p| p.content_length() <= 5 * 1024 * 1024));
        let total: usize = parts.iter().map(|p| p.content_length()).sum();
        assert_eq!(total, 12 * 1024 * 1024);
    }

    #[tokio::test]
    async fn split_ranged_reads_return_the_requested_bytes() {
        let len = 3 * MIB;
        let data = pattern(len);
        let far = 2 * MIB as u64;
        // (requested ranges, requests expected) at 1,000-byte requests, 3 at once.
        let cases: Vec<(Vec<Range<u64>>, usize)> = vec![
            (vec![0..1_000], 1),
            (vec![0..1_001], 2),
            (vec![17..5_017], 5),
            (vec![3..2_999, 3_100..9_000, 2_500..2_600], 9),
            (vec![0..10, far..far + 2_999], 4),
            (vec![(len as u64) - 4_321..len as u64], 5),
        ];
        for (ranges, requests) in cases {
            let store = ProbedStore::new(None);
            let path = Path::from("data/part-0.parquet");
            store
                .inner
                .put(&path, PutPayload::from(data.clone()))
                .await
                .unwrap();
            let wrapped = MultipartPutStore::new(store.clone(), reads(1_000, 3));

            let got = wrapped.get_ranges(&path, &ranges).await.unwrap();
            for (r, bytes) in ranges.iter().zip(&got) {
                assert!(
                    bytes.as_ref() == &data[r.start as usize..r.end as usize],
                    "bytes differ for {r:?} of {ranges:?}"
                );
            }
            assert_eq!(store.probe.gets(), requests, "requests for {ranges:?}");
            assert!(store.probe.max_in_flight() <= 3, "{ranges:?}");
        }
    }

    #[tokio::test]
    async fn ranged_reads_are_not_split_for_log_files_or_at_concurrency_one() {
        for (path, concurrency) in [
            ("t/_delta_log/00000000000000000010.checkpoint.parquet", 4),
            ("t/part-0.parquet", 1),
        ] {
            let store = ProbedStore::new(None);
            let path = Path::from(path);
            store
                .inner
                .put(&path, PutPayload::from(pattern(10_000)))
                .await
                .unwrap();
            let wrapped = MultipartPutStore::new(store.clone(), reads(1_000, concurrency));
            let got = wrapped.get_ranges(&path, &[0..9_000]).await.unwrap();
            assert_eq!(got[0].len(), 9_000);
            assert_eq!(store.probe.gets(), 1, "{path}");
        }
    }

    #[tokio::test]
    async fn a_short_object_fails_a_split_read() {
        let store = ProbedStore::new(None);
        let path = Path::from("data/part-0.parquet");
        store
            .inner
            .put(&path, PutPayload::from(pattern(2_500)))
            .await
            .unwrap();
        let wrapped = MultipartPutStore::new(store.clone(), reads(1_000, 4));
        assert!(wrapped.get_ranges(&path, &[0..3_000]).await.is_err());
    }

    #[tokio::test]
    async fn split_ranged_reads_of_local_files_return_the_requested_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let local =
            Arc::new(object_store::local::LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let path = Path::from("data/part-0.parquet");
        let data = pattern(5_000);
        local
            .put(&path, PutPayload::from(data.clone()))
            .await
            .unwrap();
        let wrapped = MultipartPutStore::new(local, reads(1_000, 3));
        let ranges = [17..2_517, 4_000..5_000];
        let got = wrapped.get_ranges(&path, &ranges).await.unwrap();
        for (r, bytes) in ranges.iter().zip(&got) {
            assert!(
                bytes.as_ref() == &data[r.start as usize..r.end as usize],
                "{r:?}"
            );
        }
        assert!(wrapped.get_ranges(&path, &[3_000..6_000]).await.is_err());
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
        let wrapped = MultipartLogStore::new(fake.clone(), MultipartConfig::default())
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
