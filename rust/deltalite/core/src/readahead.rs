//! Read-ahead of the next row group of a data file.
//!
//! The async Parquet reader fetches a row group, decodes all of it, and only then asks
//! for the next one, so a reader of a file with several row groups waits for storage
//! once per row group. [`ReadAheadStore`] serves the reader of one file: when the reader
//! asks for the column chunks of row group `i`, the store starts a background read of
//! row group `i + 1`, and serves the next request from that read.
//!
//! The store reads at most one row group ahead, so a reader holds at most two row groups:
//! the one it decodes and the one being read. The caller reserves that pair from the
//! fetch budget (see [`max_row_group_pair_fetch_bytes`]). The background read is aborted
//! when the store is dropped, which happens with the reader, before the reader returns
//! its fetch permit.

use std::ops::Range;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use bytes::Bytes;
use futures::stream::BoxStream;
use metrics::counter;
use object_store::path::Path;
use object_store::{
    GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
    PutMultipartOptions, PutOptions, PutPayload, PutResult,
};
use parquet::file::metadata::ParquetMetaData;
use tokio::task::JoinHandle;

/// Byte span of each row group: from the first byte of its first column chunk to the
/// last byte of its last one.
fn row_group_spans(meta: &ParquetMetaData) -> Vec<Range<u64>> {
    meta.row_groups()
        .iter()
        .map(|rg| {
            let mut span: Option<Range<u64>> = None;
            for c in rg.columns() {
                let (start, len) = c.byte_range();
                let end = start + len;
                span = Some(match span {
                    None => start..end,
                    Some(s) => s.start.min(start)..s.end.max(end),
                });
            }
            span.unwrap_or(0..0)
        })
        .collect()
}

/// Compressed bytes a reader with read-ahead holds at most: the largest sum of two
/// consecutive row group spans, or the one span of a single-row-group file. Spans, not
/// column chunk lengths, because the read ahead fetches and holds the whole span.
pub(crate) fn max_row_group_pair_fetch_bytes(meta: &ParquetMetaData) -> usize {
    let sizes: Vec<usize> = row_group_spans(meta)
        .iter()
        .map(|g| (g.end - g.start) as usize)
        .collect();
    if sizes.len() < 2 {
        return sizes.first().copied().unwrap_or(0);
    }
    sizes.windows(2).map(|w| w[0] + w[1]).max().unwrap_or(0)
}

/// Aborts the task when dropped, so a read nobody waits for stops holding memory.
struct AbortOnDrop(JoinHandle<object_store::Result<Bytes>>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

struct Pending {
    group: usize,
    read: AbortOnDrop,
}

/// Serves the reader of one data file and reads its next row group ahead. Every other
/// request is delegated.
pub(crate) struct ReadAheadStore {
    inner: Arc<dyn ObjectStore>,
    path: Path,
    groups: Vec<Range<u64>>,
    pending: Mutex<Option<Pending>>,
}

impl ReadAheadStore {
    pub(crate) fn new(inner: Arc<dyn ObjectStore>, path: Path, meta: &ParquetMetaData) -> Self {
        Self {
            inner,
            path,
            groups: row_group_spans(meta),
            pending: Mutex::new(None),
        }
    }

    fn take_pending(&self) -> Option<Pending> {
        self.pending
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .take()
    }

    /// The row group whose span holds every range of `ranges`.
    fn group_of(&self, ranges: &[Range<u64>]) -> Option<usize> {
        let lo = ranges.iter().map(|r| r.start).min()?;
        let hi = ranges.iter().map(|r| r.end).max()?;
        self.groups
            .iter()
            .position(|g| g.start <= lo && hi <= g.end && g.start < g.end)
    }

    fn read_ahead(&self, group: usize) {
        let Some(span) = self.groups.get(group).cloned() else {
            return;
        };
        let inner = self.inner.clone();
        let path = self.path.clone();
        let task = tokio::spawn(async move {
            let mut got = inner.get_ranges(&path, std::slice::from_ref(&span)).await?;
            got.pop().ok_or_else(|| object_store::Error::Generic {
                store: "deltalite",
                source: "ranged read returned no data".into(),
            })
        });
        *self.pending.lock().unwrap_or_else(|p| p.into_inner()) = Some(Pending {
            group,
            read: AbortOnDrop(task),
        });
    }
}

impl std::fmt::Debug for ReadAheadStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ReadAheadStore({})", self.inner)
    }
}

impl std::fmt::Display for ReadAheadStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ReadAheadStore({})", self.inner)
    }
}

#[async_trait]
impl ObjectStore for ReadAheadStore {
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
        self.inner.get_opts(location, options).await
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        let valid = ranges.iter().all(|r| r.start < r.end);
        let group = match (valid && location == &self.path).then(|| self.group_of(ranges)) {
            Some(Some(group)) => group,
            _ => return self.inner.get_ranges(location, ranges).await,
        };
        let data = match self.take_pending() {
            Some(mut pending) if pending.group == group => {
                counter!("deltalite_row_group_read_ahead_total", "outcome" => "hit").increment(1);
                let span =
                    (&mut pending.read.0)
                        .await
                        .map_err(|e| object_store::Error::Generic {
                            store: "deltalite",
                            source: Box::new(e),
                        })??;
                let Range { start: base, end } = self.groups[group].clone();
                if span.len() as u64 != end - base {
                    return Err(object_store::Error::Generic {
                        store: "deltalite",
                        source: format!(
                            "read ahead of {} for bytes {base}..{end} returned {} bytes",
                            self.path,
                            span.len()
                        )
                        .into(),
                    });
                }
                ranges
                    .iter()
                    .map(|r| span.slice((r.start - base) as usize..(r.end - base) as usize))
                    .collect()
            }
            other => {
                if other.is_some() {
                    counter!("deltalite_row_group_read_ahead_total", "outcome" => "miss")
                        .increment(1);
                }
                drop(other);
                self.inner.get_ranges(location, ranges).await?
            }
        };
        self.read_ahead(group + 1);
        Ok(data)
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
