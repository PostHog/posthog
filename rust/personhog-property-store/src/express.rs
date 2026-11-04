//! S3 Standard stays the store of record. SSTs never change once written, so a same-key copy
//! in a directory bucket holds the same bytes or nothing, and a read can fall back on any miss.
//! Copies finish before the upload returns, so a manifest never names an SST without its copies.

use std::fmt;
use std::ops::Range;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bytes::Bytes;
use futures::future::join_all;
use futures::stream::{self, BoxStream, StreamExt};
use metrics::{counter, histogram};

use crate::object_store;
use object_store::path::Path;
use object_store::{
    CopyOptions, GetOptions, GetResult, GetResultPayload, ListResult, MultipartUpload, ObjectMeta,
    ObjectStore, ObjectStoreExt, PutMode, PutMultipartOptions, PutOptions, PutPayload, PutResult,
    RenameOptions, Result, UploadPart,
};

/// Only SSTs are copied. WAL files sit under `wal/` and are read in the background, not per request.
pub fn is_replicated(location: &Path) -> bool {
    let key = location.as_ref();
    key.contains("/compacted/") && key.ends_with(".sst")
}

#[derive(Clone, Debug)]
pub struct Bucket {
    pub(crate) name: Arc<str>,
    pub(crate) store: Arc<dyn ObjectStore>,
}

impl Bucket {
    pub fn new(name: &str, store: Arc<dyn ObjectStore>) -> Self {
        Self {
            name: Arc::from(name),
            store,
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}

fn record_copy(op: &'static str, bucket: &Bucket, outcome: &'static str) {
    counter!(
        "personhog_property_store_express_copies_total",
        "op" => op,
        "bucket" => bucket.name.to_string(),
        "outcome" => outcome
    )
    .increment(1);
}

async fn bounded<T>(
    limit: Duration,
    fut: impl std::future::Future<Output = Result<T>>,
) -> Option<T> {
    match tokio::time::timeout(limit, fut).await {
        Ok(Ok(value)) => Some(value),
        Ok(Err(e)) => {
            tracing::debug!(error = %e, "express copy failed");
            None
        }
        Err(_) => None,
    }
}

#[derive(Debug)]
pub struct TeeStore {
    primary: Arc<dyn ObjectStore>,
    copies: Vec<Bucket>,
    copy_timeout: Duration,
}

impl TeeStore {
    pub fn new(primary: Arc<dyn ObjectStore>, copies: Vec<Bucket>, copy_timeout: Duration) -> Self {
        Self {
            primary,
            copies,
            copy_timeout,
        }
    }
}

impl fmt::Display for TeeStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "TeeStore({}, {} copies)",
            self.primary,
            self.copies.len()
        )
    }
}

#[async_trait]
impl ObjectStore for TeeStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> Result<PutResult> {
        if !is_replicated(location) {
            return self.primary.put_opts(location, payload, opts).await;
        }
        let copies = join_all(self.copies.iter().map(|bucket| {
            let payload = payload.clone();
            async move {
                // A copy is overwritten on retry: the bytes are identical, and Standard decides the conflict.
                let put =
                    bucket
                        .store
                        .put_opts(location, payload, PutOptions::from(PutMode::Overwrite));
                let outcome = match bounded(self.copy_timeout, put).await {
                    Some(_) => "copied",
                    None => "failed",
                };
                record_copy("put", bucket, outcome);
            }
        }));
        let (written, _) = tokio::join!(self.primary.put_opts(location, payload, opts), copies);
        written
    }

    async fn put_multipart_opts(
        &self,
        location: &Path,
        opts: PutMultipartOptions,
    ) -> Result<Box<dyn MultipartUpload>> {
        let primary = self.primary.put_multipart_opts(location, opts).await?;
        if !is_replicated(location) {
            return Ok(primary);
        }
        let started = join_all(self.copies.iter().map(|bucket| async move {
            let upload = bounded(
                self.copy_timeout,
                bucket
                    .store
                    .put_multipart_opts(location, PutMultipartOptions::default()),
            )
            .await;
            if upload.is_none() {
                record_copy("multipart", bucket, "failed");
            }
            upload.map(|upload| CopyUpload {
                bucket: bucket.clone(),
                upload,
                failed: Arc::new(AtomicBool::new(false)),
            })
        }))
        .await;
        Ok(Box::new(TeeUpload {
            primary,
            copies: started.into_iter().flatten().collect(),
            copy_timeout: self.copy_timeout,
        }))
    }

    async fn get_opts(&self, location: &Path, options: GetOptions) -> Result<GetResult> {
        self.primary.get_opts(location, options).await
    }

    async fn get_ranges(&self, location: &Path, ranges: &[Range<u64>]) -> Result<Vec<Bytes>> {
        self.primary.get_ranges(location, ranges).await
    }

    /// Standard first: a copy that outlives its original is harmless, and the repair job removes it.
    fn delete_stream(
        &self,
        locations: BoxStream<'static, Result<Path>>,
    ) -> BoxStream<'static, Result<Path>> {
        let copies = self.copies.clone();
        let copy_timeout = self.copy_timeout;
        self.primary
            .delete_stream(locations)
            .then(move |deleted| {
                let copies = copies.clone();
                async move {
                    if let Ok(path) = &deleted {
                        if is_replicated(path) {
                            join_all(copies.iter().map(|bucket| async move {
                                let outcome = match tokio::time::timeout(
                                    copy_timeout,
                                    bucket.store.delete(path),
                                )
                                .await
                                {
                                    Ok(Ok(())) | Ok(Err(object_store::Error::NotFound { .. })) => {
                                        "deleted"
                                    }
                                    _ => "failed",
                                };
                                record_copy("delete", bucket, outcome);
                            }))
                            .await;
                        }
                    }
                    deleted
                }
            })
            .boxed()
    }

    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, Result<ObjectMeta>> {
        self.primary.list(prefix)
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, Result<ObjectMeta>> {
        self.primary.list_with_offset(prefix, offset)
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> Result<ListResult> {
        self.primary.list_with_delimiter(prefix).await
    }

    async fn copy_opts(&self, from: &Path, to: &Path, options: CopyOptions) -> Result<()> {
        self.primary.copy_opts(from, to, options).await
    }

    async fn rename_opts(&self, from: &Path, to: &Path, options: RenameOptions) -> Result<()> {
        self.primary.rename_opts(from, to, options).await
    }
}

#[derive(Debug)]
struct CopyUpload {
    bucket: Bucket,
    upload: Box<dyn MultipartUpload>,
    /// Set by any failed part; the upload is then aborted rather than completed.
    failed: Arc<AtomicBool>,
}

#[derive(Debug)]
struct TeeUpload {
    primary: Box<dyn MultipartUpload>,
    copies: Vec<CopyUpload>,
    copy_timeout: Duration,
}

#[async_trait]
impl MultipartUpload for TeeUpload {
    fn put_part(&mut self, data: PutPayload) -> UploadPart {
        let written = self.primary.put_part(data.clone());
        let copy_timeout = self.copy_timeout;
        // Every copy receives every part in order, so its part numbers stay consecutive as directory buckets require.
        let copies: Vec<_> = self
            .copies
            .iter_mut()
            .filter(|copy| !copy.failed.load(Ordering::Relaxed))
            .map(|copy| {
                let failed = Arc::clone(&copy.failed);
                let part = copy.upload.put_part(data.clone());
                async move {
                    if !matches!(tokio::time::timeout(copy_timeout, part).await, Ok(Ok(()))) {
                        failed.store(true, Ordering::Relaxed);
                    }
                }
            })
            .collect();
        Box::pin(async move {
            let (written, _) = tokio::join!(written, join_all(copies));
            written
        })
    }

    async fn complete(&mut self) -> Result<PutResult> {
        let Self {
            primary,
            copies,
            copy_timeout,
        } = self;
        let copy_timeout = *copy_timeout;
        let finish_copies = join_all(copies.iter_mut().map(|copy| async move {
            let completed = !copy.failed.load(Ordering::Relaxed)
                && bounded(copy_timeout, copy.upload.complete())
                    .await
                    .is_some();
            if !completed {
                abort_copy(copy, copy_timeout).await;
            }
            let outcome = if completed { "copied" } else { "failed" };
            record_copy("multipart", &copy.bucket, outcome);
        }));
        let (written, _) = tokio::join!(primary.complete(), finish_copies);
        written
    }

    async fn abort(&mut self) -> Result<()> {
        let copy_timeout = self.copy_timeout;
        join_all(
            self.copies
                .iter_mut()
                .map(|copy| abort_copy(copy, copy_timeout)),
        )
        .await;
        self.primary.abort().await
    }
}

/// An abort that fails leaves an incomplete upload, which the bucket's lifecycle rule expires.
async fn abort_copy(copy: &mut CopyUpload, copy_timeout: Duration) {
    if bounded(copy_timeout, copy.upload.abort()).await.is_none() {
        tracing::debug!(bucket = %copy.bucket.name, "aborting an express copy upload failed");
    }
}

#[derive(Debug)]
pub struct ReadThroughStore {
    primary: Arc<dyn ObjectStore>,
    express: Bucket,
    read_timeout: Duration,
}

impl ReadThroughStore {
    pub fn new(primary: Arc<dyn ObjectStore>, express: Bucket, read_timeout: Duration) -> Self {
        Self {
            primary,
            express,
            read_timeout,
        }
    }

    fn record_read(&self, outcome: &'static str) {
        counter!("personhog_property_store_express_reads_total", "outcome" => outcome).increment(1);
    }

    fn fell_back(&self, error: Option<object_store::Error>) {
        let outcome = match error {
            None => "timeout",
            Some(object_store::Error::NotFound { .. }) => "missing",
            Some(e) => {
                tracing::debug!(error = %e, "express read failed; reading standard");
                "error"
            }
        };
        self.record_read(outcome);
    }
}

impl fmt::Display for ReadThroughStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "ReadThroughStore({}, {})",
            self.express.name, self.primary
        )
    }
}

/// Reads the whole body inside the deadline, so a stall mid-body still falls back.
async fn buffered(result: GetResult) -> Result<GetResult> {
    let GetResult {
        payload,
        meta,
        range,
        attributes,
        extensions,
    } = result;
    let body = GetResult {
        payload,
        meta: meta.clone(),
        range: range.clone(),
        attributes: attributes.clone(),
        extensions: Default::default(),
    }
    .bytes()
    .await?;
    Ok(GetResult {
        payload: GetResultPayload::Stream(stream::once(async move { Ok(body) }).boxed()),
        meta,
        range,
        attributes,
        extensions,
    })
}

#[async_trait]
impl ObjectStore for ReadThroughStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> Result<PutResult> {
        self.primary.put_opts(location, payload, opts).await
    }

    async fn put_multipart_opts(
        &self,
        location: &Path,
        opts: PutMultipartOptions,
    ) -> Result<Box<dyn MultipartUpload>> {
        self.primary.put_multipart_opts(location, opts).await
    }

    async fn get_opts(&self, location: &Path, options: GetOptions) -> Result<GetResult> {
        // Conditional reads and HEADs need Standard's ETags and versions, which a copy does not share.
        let conditional = options.if_match.is_some()
            || options.if_none_match.is_some()
            || options.if_modified_since.is_some()
            || options.if_unmodified_since.is_some()
            || options.version.is_some();
        if !is_replicated(location) || options.head || conditional {
            return self.primary.get_opts(location, options).await;
        }
        let started = Instant::now();
        let read = async {
            buffered(
                self.express
                    .store
                    .get_opts(location, options.clone())
                    .await?,
            )
            .await
        };
        match tokio::time::timeout(self.read_timeout, read).await {
            Ok(Ok(result)) => {
                histogram!("personhog_property_store_express_read_ms")
                    .record(started.elapsed().as_secs_f64() * 1000.0);
                self.record_read("hit");
                return Ok(result);
            }
            Ok(Err(e)) => self.fell_back(Some(e)),
            Err(_) => self.fell_back(None),
        }
        self.primary.get_opts(location, options).await
    }

    async fn get_ranges(&self, location: &Path, ranges: &[Range<u64>]) -> Result<Vec<Bytes>> {
        if !is_replicated(location) {
            return self.primary.get_ranges(location, ranges).await;
        }
        let started = Instant::now();
        match tokio::time::timeout(
            self.read_timeout,
            self.express.store.get_ranges(location, ranges),
        )
        .await
        {
            Ok(Ok(bytes)) => {
                histogram!("personhog_property_store_express_read_ms")
                    .record(started.elapsed().as_secs_f64() * 1000.0);
                self.record_read("hit");
                return Ok(bytes);
            }
            Ok(Err(e)) => self.fell_back(Some(e)),
            Err(_) => self.fell_back(None),
        }
        self.primary.get_ranges(location, ranges).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, Result<Path>>,
    ) -> BoxStream<'static, Result<Path>> {
        self.primary.delete_stream(locations)
    }

    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, Result<ObjectMeta>> {
        self.primary.list(prefix)
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, Result<ObjectMeta>> {
        self.primary.list_with_offset(prefix, offset)
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> Result<ListResult> {
        self.primary.list_with_delimiter(prefix).await
    }

    async fn copy_opts(&self, from: &Path, to: &Path, options: CopyOptions) -> Result<()> {
        self.primary.copy_opts(from, to, options).await
    }

    async fn rename_opts(&self, from: &Path, to: &Path, options: RenameOptions) -> Result<()> {
        self.primary.rename_opts(from, to, options).await
    }
}

#[cfg(test)]
mod tests {
    use object_store::memory::InMemory;
    use rstest::rstest;

    use super::*;
    use crate::writer::{PartitionKey, PropertyRecord};
    use crate::{PropertyReader, PropertyStoreConfig, PropertyWriter};

    const SST: &str = "props/shard-00000/compacted/01J000000000000000000000AA.sst";

    #[derive(Debug)]
    struct Faulty {
        inner: InMemory,
        refuse: bool,
        delay: Duration,
    }

    impl Faulty {
        fn refusing() -> Self {
            Self {
                inner: InMemory::new(),
                refuse: true,
                delay: Duration::ZERO,
            }
        }

        fn slow(delay: Duration) -> Self {
            Self {
                inner: InMemory::new(),
                refuse: false,
                delay,
            }
        }

        async fn gate(&self) -> Result<()> {
            tokio::time::sleep(self.delay).await;
            if self.refuse {
                return Err(object_store::Error::NotImplemented {
                    operation: "faulty".to_string(),
                    implementer: "test".to_string(),
                });
            }
            Ok(())
        }
    }

    impl fmt::Display for Faulty {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "Faulty")
        }
    }

    #[async_trait]
    impl ObjectStore for Faulty {
        async fn put_opts(&self, l: &Path, p: PutPayload, o: PutOptions) -> Result<PutResult> {
            self.gate().await?;
            self.inner.put_opts(l, p, o).await
        }
        async fn put_multipart_opts(
            &self,
            l: &Path,
            o: PutMultipartOptions,
        ) -> Result<Box<dyn MultipartUpload>> {
            self.gate().await?;
            self.inner.put_multipart_opts(l, o).await
        }
        async fn get_opts(&self, l: &Path, o: GetOptions) -> Result<GetResult> {
            self.gate().await?;
            self.inner.get_opts(l, o).await
        }
        fn delete_stream(
            &self,
            l: BoxStream<'static, Result<Path>>,
        ) -> BoxStream<'static, Result<Path>> {
            self.inner.delete_stream(l)
        }
        fn list(&self, p: Option<&Path>) -> BoxStream<'static, Result<ObjectMeta>> {
            self.inner.list(p)
        }
        async fn list_with_delimiter(&self, p: Option<&Path>) -> Result<ListResult> {
            self.inner.list_with_delimiter(p).await
        }
        async fn copy_opts(&self, f: &Path, t: &Path, o: CopyOptions) -> Result<()> {
            self.inner.copy_opts(f, t, o).await
        }
        async fn rename_opts(&self, f: &Path, t: &Path, o: RenameOptions) -> Result<()> {
            self.inner.rename_opts(f, t, o).await
        }
    }

    /// Standard as a leader would see it if no SST were readable there.
    #[derive(Debug)]
    struct HidesSsts(Arc<dyn ObjectStore>);

    impl fmt::Display for HidesSsts {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "HidesSsts")
        }
    }

    #[async_trait]
    impl ObjectStore for HidesSsts {
        async fn put_opts(&self, l: &Path, p: PutPayload, o: PutOptions) -> Result<PutResult> {
            self.0.put_opts(l, p, o).await
        }
        async fn put_multipart_opts(
            &self,
            l: &Path,
            o: PutMultipartOptions,
        ) -> Result<Box<dyn MultipartUpload>> {
            self.0.put_multipart_opts(l, o).await
        }
        async fn get_opts(&self, l: &Path, o: GetOptions) -> Result<GetResult> {
            if is_replicated(l) && !o.head {
                return Err(object_store::Error::NotFound {
                    path: l.to_string(),
                    source: "hidden".into(),
                });
            }
            self.0.get_opts(l, o).await
        }
        fn delete_stream(
            &self,
            l: BoxStream<'static, Result<Path>>,
        ) -> BoxStream<'static, Result<Path>> {
            self.0.delete_stream(l)
        }
        fn list(&self, p: Option<&Path>) -> BoxStream<'static, Result<ObjectMeta>> {
            self.0.list(p)
        }
        async fn list_with_delimiter(&self, p: Option<&Path>) -> Result<ListResult> {
            self.0.list_with_delimiter(p).await
        }
        async fn copy_opts(&self, f: &Path, t: &Path, o: CopyOptions) -> Result<()> {
            self.0.copy_opts(f, t, o).await
        }
        async fn rename_opts(&self, f: &Path, t: &Path, o: RenameOptions) -> Result<()> {
            self.0.rename_opts(f, t, o).await
        }
    }

    fn tee(primary: &Arc<InMemory>, copies: &[Arc<dyn ObjectStore>]) -> TeeStore {
        TeeStore::new(
            primary.clone(),
            copies
                .iter()
                .enumerate()
                .map(|(i, store)| Bucket::new(&format!("copy-{i}"), Arc::clone(store)))
                .collect(),
            Duration::from_secs(5),
        )
    }

    async fn upload(
        store: &dyn ObjectStore,
        location: &Path,
        body: &'static [u8],
        multipart: bool,
    ) {
        if multipart {
            let mut upload = store.put_multipart(location).await.unwrap();
            for chunk in body.chunks(3) {
                upload
                    .put_part(PutPayload::from_static(chunk))
                    .await
                    .unwrap();
            }
            upload.complete().await.unwrap();
        } else {
            store
                .put(location, PutPayload::from_static(body))
                .await
                .unwrap();
        }
    }

    async fn read(store: &dyn ObjectStore, location: &Path) -> Option<Bytes> {
        match store.get(location).await {
            Ok(result) => Some(result.bytes().await.unwrap()),
            Err(object_store::Error::NotFound { .. }) => None,
            Err(e) => panic!("unexpected read error: {e}"),
        }
    }

    #[rstest]
    #[case::single_put(false)]
    #[case::multipart(true)]
    #[tokio::test]
    async fn an_sst_reaches_every_healthy_copy_even_when_another_copy_fails(
        #[case] multipart: bool,
    ) {
        let primary = Arc::new(InMemory::new());
        let healthy = Arc::new(InMemory::new());
        let copies: [Arc<dyn ObjectStore>; 2] = [Arc::new(Faulty::refusing()), healthy.clone()];
        let store = tee(&primary, &copies);
        let sst = Path::from(SST);

        upload(&store, &sst, b"sorted string table", multipart).await;

        assert_eq!(
            read(primary.as_ref(), &sst).await.as_deref(),
            Some(&b"sorted string table"[..])
        );
        assert_eq!(
            read(healthy.as_ref(), &sst).await.as_deref(),
            Some(&b"sorted string table"[..])
        );
    }

    #[rstest]
    #[case::manifest("props/shard-00000/manifest/00000000000000000001.manifest")]
    #[case::wal("props/shard-00000/wal/00000000000000000001.sst")]
    #[case::maintenance("props/maintenance/shard-00000/full-compaction")]
    #[tokio::test]
    async fn only_compacted_ssts_are_copied(#[case] key: &str) {
        let primary = Arc::new(InMemory::new());
        let copy: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let store = tee(&primary, std::slice::from_ref(&copy));
        let location = Path::from(key);

        upload(&store, &location, b"metadata", false).await;

        assert!(read(primary.as_ref(), &location).await.is_some());
        assert!(read(copy.as_ref(), &location).await.is_none());
    }

    #[tokio::test]
    async fn deleting_an_sst_deletes_its_copies() {
        let primary = Arc::new(InMemory::new());
        let copy: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let store = tee(&primary, std::slice::from_ref(&copy));
        let sst = Path::from(SST);
        upload(&store, &sst, b"sorted string table", false).await;

        store.delete(&sst).await.unwrap();

        assert!(read(copy.as_ref(), &sst).await.is_none());
    }

    #[rstest]
    #[case::copy_present(Some(Duration::ZERO), &b"from express"[..])]
    #[case::copy_missing(None, &b"from standard"[..])]
    #[case::copy_too_slow(Some(Duration::from_secs(2)), &b"from standard"[..])]
    #[tokio::test]
    async fn an_sst_read_prefers_its_copy_and_falls_back_to_standard(
        #[case] copy_delay: Option<Duration>,
        #[case] expected: &[u8],
    ) {
        let primary = Arc::new(InMemory::new());
        let sst = Path::from(SST);
        primary
            .put(&sst, PutPayload::from_static(b"from standard"))
            .await
            .unwrap();
        let express = Faulty::slow(copy_delay.unwrap_or_default());
        if copy_delay.is_some() {
            express
                .inner
                .put(&sst, PutPayload::from_static(b"from express"))
                .await
                .unwrap();
        }
        let store = ReadThroughStore::new(
            primary,
            Bucket::new("express", Arc::new(express)),
            Duration::from_millis(200),
        );

        let ranged = store
            .get_range(&sst, 0..expected.len() as u64)
            .await
            .unwrap();
        let whole = read(&store, &sst).await.unwrap();

        assert_eq!(&ranged[..], expected);
        assert_eq!(&whole[..], expected);
    }

    fn config() -> PropertyStoreConfig {
        PropertyStoreConfig {
            reader_poll_ms: 20,
            ..PropertyStoreConfig::local("props", 1)
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_leader_reads_slatedb_ssts_from_the_copies_the_writer_made() {
        let standard: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let copy: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let writer = PropertyWriter::new(
            &config(),
            Arc::new(TeeStore::new(
                Arc::clone(&standard),
                vec![Bucket::new("express", Arc::clone(&copy))],
                Duration::from_secs(5),
            )),
        );
        let partition = PartitionKey {
            topic: Arc::from("changelog"),
            partition: 0,
        };
        writer.assign(&partition, 1, 1, || true).await.unwrap();
        writer
            .put(
                &partition,
                1,
                &[PropertyRecord {
                    team_id: 7,
                    person_id: 1,
                    version: 1,
                    deleted: false,
                    properties: Bytes::from_static(br#"{"plan":"paid"}"#),
                }],
            )
            .await
            .unwrap();
        // Moves the record out of the WAL, so a fresh reader can only find it in an SST.
        writer.flush_memtables().await;
        writer.close().await;
        let hidden: Arc<dyn ObjectStore> = Arc::new(HidesSsts(Arc::clone(&standard)));

        let without_copy = PropertyReader::new(&config(), Arc::clone(&hidden))
            .get(7, 1)
            .await;
        let with_copy = PropertyReader::new(
            &config(),
            Arc::new(ReadThroughStore::new(
                hidden,
                Bucket::new("express", copy),
                Duration::from_secs(1),
            )),
        )
        .get(7, 1)
        .await
        .unwrap();

        assert!(
            !matches!(without_copy, Ok(Some(_))),
            "the record must live only in SSTs for this test to prove anything"
        );
        assert_eq!(&with_copy.unwrap().properties[..], br#"{"plan":"paid"}"#);
    }
}
