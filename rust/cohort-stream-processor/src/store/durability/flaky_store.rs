use std::collections::HashMap;
use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use async_trait::async_trait;
use futures::stream::{self, BoxStream, StreamExt};
use object_store::memory::InMemory;
use object_store::path::Path;
use object_store::{
    CopyOptions, GetOptions, GetResult, GetResultPayload, ListResult, MultipartUpload, ObjectMeta,
    ObjectStore, PutMultipartOptions, PutOptions, PutPayload, PutResult, Result,
};

/// An in-memory store whose first put or get of `flaky` fails. The failed get sends half the object
/// first.
#[derive(Debug)]
pub(super) struct FlakyStore {
    inner: InMemory,
    flaky: Path,
    tripped: AtomicBool,
    gets: Mutex<HashMap<Path, usize>>,
}

impl FlakyStore {
    /// Objects already in `inner` skip the failed put.
    pub(super) fn new(inner: InMemory, flaky: &str) -> Self {
        Self {
            inner,
            flaky: Path::from(flaky),
            tripped: AtomicBool::new(false),
            gets: Mutex::default(),
        }
    }

    pub(super) fn tripped(&self) -> bool {
        self.tripped.load(Ordering::SeqCst)
    }

    pub(super) fn gets(&self, key: &str) -> usize {
        self.gets
            .lock()
            .unwrap()
            .get(&Path::from(key))
            .copied()
            .unwrap_or_default()
    }

    fn trips(&self, location: &Path) -> bool {
        *location == self.flaky && !self.tripped.swap(true, Ordering::SeqCst)
    }
}

fn proxy_error() -> object_store::Error {
    object_store::Error::Generic {
        store: "S3",
        source: "error writing a body to connection: unexpected EOF".into(),
    }
}

impl fmt::Display for FlakyStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "FlakyStore({})", self.flaky)
    }
}

#[async_trait]
impl ObjectStore for FlakyStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> Result<PutResult> {
        if self.trips(location) {
            return Err(proxy_error());
        }
        self.inner.put_opts(location, payload, opts).await
    }

    async fn put_multipart_opts(
        &self,
        location: &Path,
        opts: PutMultipartOptions,
    ) -> Result<Box<dyn MultipartUpload>> {
        self.inner.put_multipart_opts(location, opts).await
    }

    async fn get_opts(&self, location: &Path, options: GetOptions) -> Result<GetResult> {
        *self
            .gets
            .lock()
            .unwrap()
            .entry(location.clone())
            .or_default() += 1;
        let result = self.inner.get_opts(location, options).await?;
        if !self.trips(location) {
            return Ok(result);
        }
        let (meta, range, attributes) = (
            result.meta.clone(),
            result.range.clone(),
            result.attributes.clone(),
        );
        let mut half = result.bytes().await?;
        half.truncate(half.len() / 2);
        Ok(GetResult {
            payload: GetResultPayload::Stream(stream::iter([Ok(half), Err(proxy_error())]).boxed()),
            meta,
            range,
            attributes,
        })
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, Result<Path>>,
    ) -> BoxStream<'static, Result<Path>> {
        self.inner.delete_stream(locations)
    }

    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, Result<ObjectMeta>> {
        self.inner.list(prefix)
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> Result<ListResult> {
        self.inner.list_with_delimiter(prefix).await
    }

    async fn copy_opts(&self, from: &Path, to: &Path, options: CopyOptions) -> Result<()> {
        self.inner.copy_opts(from, to, options).await
    }
}
