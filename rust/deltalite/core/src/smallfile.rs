//! One-request reads of small data files.
//!
//! A data file is opened with a read of its last `FOOTER_SIZE_HINT` bytes. For a file no
//! larger than the hint, that read already returns the whole file, and the range read
//! that follows (the PK columns for the probe, every column for a rewrite or a
//! compaction) fetches bytes that the process had a moment before.
//! [`fetch_small_file`] makes the one request explicit and [`SmallFileStore`] serves the
//! reader of that file from the same bytes.
//!
//! The file size comes from the Add action in the Delta log, never from a HEAD. The
//! bytes belong to one reader and are dropped with it. That reader takes its fetch
//! permit for the whole file before the request, so the bytes are inside the fetch
//! budget from the first one, and the row groups that the reader decodes are slices of
//! the same buffer. Data files are immutable (a new file gets a new name), so the bytes
//! cannot be stale.

use std::ops::Range;
use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use futures::stream::{BoxStream, StreamExt};
use object_store::path::Path;
use object_store::{
    Attributes, GetOptions, GetRange, GetResult, GetResultPayload, ListResult, MultipartUpload,
    ObjectMeta, ObjectStore, PutMultipartOptions, PutOptions, PutPayload, PutResult,
};

/// Kill switch; `0` restores the footer read and the range reads.
pub const SMALL_FILE_SINGLE_GET_ENV: &str = "DELTALITE_SMALL_FILE_SINGLE_GET";

/// A small data file held in memory: its bytes and the object metadata of the read.
#[derive(Debug, Clone)]
pub(crate) struct SmallFile {
    meta: ObjectMeta,
    bytes: Bytes,
}

/// Whether a file of `size` bytes is read in one request, given the footer read size.
pub(crate) fn reads_whole(size: u64, footer_hint: u64) -> bool {
    size > 0 && size <= footer_hint && crate::limits::env_switch(SMALL_FILE_SINGLE_GET_ENV)
}

/// Read all of `path` in one request. `size` is the size that the Delta log records;
/// `None` when the object does not hold exactly that many bytes, and the caller then
/// opens the file by ranges as before.
pub(crate) async fn fetch_small_file(
    store: &Arc<dyn ObjectStore>,
    path: &Path,
    size: u64,
) -> object_store::Result<Option<SmallFile>> {
    let options = GetOptions {
        range: Some(GetRange::Bounded(0..size)),
        ..Default::default()
    };
    let result = store.get_opts(path, options).await?;
    let meta = result.meta.clone();
    if meta.size != size {
        return Ok(None);
    }
    let bytes = result.bytes().await?;
    Ok((bytes.len() as u64 == size).then_some(SmallFile { meta, bytes }))
}

/// Serves plain reads of one path from memory and delegates everything else.
#[derive(Debug)]
pub(crate) struct SmallFileStore {
    inner: Arc<dyn ObjectStore>,
    path: Path,
    file: SmallFile,
}

impl SmallFileStore {
    pub(crate) fn new(inner: Arc<dyn ObjectStore>, path: Path, file: SmallFile) -> Self {
        Self { inner, path, file }
    }

    fn clamp(&self, range: &Range<u64>) -> Range<u64> {
        let len = self.file.bytes.len() as u64;
        let start = range.start.min(len);
        start..range.end.min(len).max(start)
    }

    fn slice(&self, range: &Range<u64>) -> Bytes {
        self.file
            .bytes
            .slice(range.start as usize..range.end as usize)
    }
}

impl std::fmt::Display for SmallFileStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "SmallFileStore({})", self.inner)
    }
}

#[async_trait]
impl ObjectStore for SmallFileStore {
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
        let plain = !options.head
            && options.if_match.is_none()
            && options.if_none_match.is_none()
            && options.if_modified_since.is_none()
            && options.if_unmodified_since.is_none()
            && options.version.is_none();
        if location != &self.path || !plain {
            return self.inner.get_opts(location, options).await;
        }
        let len = self.file.bytes.len() as u64;
        let range = match options.range.as_ref() {
            None => 0..len,
            Some(GetRange::Bounded(r)) => self.clamp(r),
            Some(GetRange::Offset(offset)) => (*offset).min(len)..len,
            Some(GetRange::Suffix(n)) => len.saturating_sub(*n)..len,
        };
        let slice = self.slice(&range);
        Ok(GetResult {
            payload: GetResultPayload::Stream(
                futures::stream::once(async move { Ok(slice) }).boxed(),
            ),
            meta: self.file.meta.clone(),
            range,
            attributes: Attributes::default(),
        })
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        if location != &self.path {
            return self.inner.get_ranges(location, ranges).await;
        }
        Ok(ranges.iter().map(|r| self.slice(&self.clamp(r))).collect())
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

#[cfg(test)]
mod tests {
    use object_store::memory::InMemory;
    use object_store::ObjectStoreExt;

    use super::*;

    #[tokio::test]
    async fn a_file_is_read_whole_only_when_the_log_size_is_the_object_size() {
        let store: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let path = Path::from("t/part-0.parquet");
        let body = Bytes::from_static(b"0123456789");
        store
            .put(&path, PutPayload::from_bytes(body.clone()))
            .await
            .unwrap();

        let file = fetch_small_file(&store, &path, 10).await.unwrap();
        assert_eq!(file.map(|f| f.bytes), Some(body));
        for wrong in [4, 11] {
            let file = fetch_small_file(&store, &path, wrong).await.unwrap();
            assert!(file.is_none(), "log size {wrong}");
        }
    }

    #[tokio::test]
    async fn reads_of_the_held_file_make_no_request() {
        let inner: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let path = Path::from("t/part-0.parquet");
        let body = Bytes::from_static(b"0123456789");
        inner
            .put(&path, PutPayload::from_bytes(body.clone()))
            .await
            .unwrap();
        let file = fetch_small_file(&inner, &path, 10).await.unwrap().unwrap();
        inner.delete(&path).await.unwrap();
        let store = SmallFileStore::new(inner, path.clone(), file);

        assert_eq!(
            store.get_range(&path, 2..5).await.unwrap(),
            body.slice(2..5)
        );
        let ranges = store.get_ranges(&path, &[0..1, 8..10]).await.unwrap();
        assert_eq!(ranges, vec![body.slice(0..1), body.slice(8..10)]);
        let suffix = GetOptions {
            range: Some(GetRange::Suffix(4)),
            ..Default::default()
        };
        let tail = store.get_opts(&path, suffix).await.unwrap();
        assert_eq!(tail.bytes().await.unwrap(), body.slice(6..10));
    }
}
