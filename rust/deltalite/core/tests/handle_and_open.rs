//! Integration tests for the open/refresh path: the single-load guarantee of
//! `open_table_multipart`, snapshot preservation in `wrap_multipart`, and the
//! `TableHandle` upsert orchestration (incremental refresh, relax with a warm cache).

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use arrow_array::{Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::logstore::{
    default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
    ObjectStoreFactory, StorageConfig,
};
use deltalake::operations::create::CreateBuilder;
use deltalake::{DeltaResult, Path};
use deltalite_core::handle::TableHandle;
use deltalite_core::table::{open_table, open_table_multipart, wrap_multipart, MultipartConfig};
use deltalite_core::upsert::UpsertOptions;
use futures::stream::BoxStream;
use object_store::local::LocalFileSystem;
use object_store::{
    CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
    PutMultipartOptions, PutOptions, PutPayload, PutResult, RenameOptions,
};

// ---- read-counting store, registered as its own URL scheme ------------------------

static READS: AtomicUsize = AtomicUsize::new(0);

fn reads() -> usize {
    READS.load(Ordering::SeqCst)
}

#[derive(Debug)]
struct CountingStore {
    inner: Arc<dyn ObjectStore>,
}

impl std::fmt::Display for CountingStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "CountingStore({})", self.inner)
    }
}

#[async_trait::async_trait]
impl ObjectStore for CountingStore {
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
        READS.fetch_add(1, Ordering::SeqCst);
        self.inner.get_opts(location, options).await
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[std::ops::Range<u64>],
    ) -> object_store::Result<Vec<bytes::Bytes>> {
        READS.fetch_add(ranges.len(), Ordering::SeqCst);
        self.inner.get_ranges(location, ranges).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<Path>>,
    ) -> BoxStream<'static, object_store::Result<Path>> {
        self.inner.delete_stream(locations)
    }

    // Sorted before returning: cloud stores list keys lexicographically and
    // delta-kernel relies on it, while `LocalFileSystem` yields directory order.
    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        READS.fetch_add(1, Ordering::SeqCst);
        sorted(self.inner.list(prefix))
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        READS.fetch_add(1, Ordering::SeqCst);
        sorted(self.inner.list_with_offset(prefix, offset))
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> object_store::Result<ListResult> {
        READS.fetch_add(1, Ordering::SeqCst);
        self.inner.list_with_delimiter(prefix).await
    }

    async fn copy_opts(
        &self,
        from: &Path,
        to: &Path,
        options: CopyOptions,
    ) -> object_store::Result<()> {
        self.inner.copy_opts(from, to, options).await
    }

    async fn rename_opts(
        &self,
        from: &Path,
        to: &Path,
        options: RenameOptions,
    ) -> object_store::Result<()> {
        self.inner.rename_opts(from, to, options).await
    }
}

fn sorted(
    stream: BoxStream<'static, object_store::Result<ObjectMeta>>,
) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
    use futures::{StreamExt, TryStreamExt};
    futures::stream::once(async move {
        let mut items: Vec<ObjectMeta> = stream.try_collect().await?;
        items.sort_by(|a, b| a.location.cmp(&b.location));
        Ok::<_, object_store::Error>(futures::stream::iter(items.into_iter().map(Ok)))
    })
    .try_flatten()
    .boxed()
}

#[derive(Debug, Default)]
struct Factory;

impl ObjectStoreFactory for Factory {
    fn parse_url_opts(
        &self,
        url: &url::Url,
        _config: &StorageConfig,
    ) -> DeltaResult<(Arc<dyn ObjectStore>, Path)> {
        let store = CountingStore {
            inner: Arc::new(LocalFileSystem::new()),
        };
        Ok((Arc::new(store), Path::from_url_path(url.path())?))
    }
}

impl LogStoreFactory for Factory {
    fn with_options(
        &self,
        prefixed_store: Arc<dyn ObjectStore>,
        root_store: Arc<dyn ObjectStore>,
        location: &url::Url,
        options: &StorageConfig,
    ) -> DeltaResult<Arc<dyn LogStore>> {
        Ok(default_logstore(
            prefixed_store,
            root_store,
            location,
            options,
        ))
    }
}

fn register_counting_scheme() {
    let scheme = url::Url::parse("dltest://").expect("static url");
    object_store_factories().insert(scheme.clone(), Arc::new(Factory));
    logstore_factories().insert(scheme, Arc::new(Factory));
}

// ---- fixtures ----------------------------------------------------------------------

fn schema(v_nullable: bool) -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("pk", DataType::Utf8, false),
        Field::new("v", DataType::Int64, v_nullable),
    ]))
}

fn batch(schema: &SchemaRef, pks: &[&str], vs: Vec<Option<i64>>) -> RecordBatch {
    RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(pks.to_vec())),
            Arc::new(Int64Array::from(vs)),
        ],
    )
    .expect("test batch")
}

fn opts() -> UpsertOptions {
    UpsertOptions {
        primary_keys: vec!["pk".to_string()],
        ..Default::default()
    }
}

/// Create an unpartitioned table at `uri` with a non-nullable `pk` and a `v` column of
/// the given nullability, then seed it with a few commits so opening has log to replay.
async fn create_seeded_table(uri: &str, v_nullable: bool) -> SchemaRef {
    CreateBuilder::new()
        .with_location(uri)
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("v", KernelType::LONG, v_nullable),
        ])
        .await
        .expect("create table");

    let s = schema(v_nullable);
    for i in 0..3 {
        let mut handle = TableHandle::open(uri.to_string(), HashMap::new())
            .await
            .expect("open for seeding");
        let b = batch(&s, &["a", "b"], vec![Some(i), Some(i + 1)]);
        handle
            .upsert(vec![b], s.clone(), opts(), MultipartConfig::default())
            .await
            .expect("seed upsert");
    }
    s
}

// ---- tests -------------------------------------------------------------------------

/// Pins the double-load fix: opening through the multipart wrapper must cost the same
/// storage reads as a plain open, not twice as many. Serial with the other counting
/// test via the shared atomic; each measurement is deltas around one call, and the
/// tests run in one process where no other code touches the `dltest://` scheme.
#[tokio::test]
async fn open_table_multipart_replays_the_log_once() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = format!("dltest://{}", dir.path().join("t1").to_string_lossy());
    create_seeded_table(&uri, true).await;

    let before_plain = reads();
    let plain = open_table(&uri, HashMap::new()).await.expect("plain open");
    let plain_reads = reads() - before_plain;

    let before_multipart = reads();
    let multipart = open_table_multipart(&uri, HashMap::new(), MultipartConfig::default())
        .await
        .expect("multipart open");
    let multipart_reads = reads() - before_multipart;

    assert_eq!(plain.version(), multipart.version());
    assert!(plain.version().is_some(), "open must load the snapshot");
    assert_eq!(
        multipart_reads, plain_reads,
        "the multipart open must not replay the log a second time \
         (multipart {multipart_reads} reads vs plain {plain_reads})"
    );
}

#[tokio::test]
async fn wrap_multipart_carries_the_loaded_snapshot_without_io() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t2").to_string_lossy().to_string();
    create_seeded_table(&uri, true).await;

    let table = open_table(&uri, HashMap::new()).await.expect("open");
    let version = table.version();
    let wrapped = wrap_multipart(table, MultipartConfig::default());
    assert_eq!(wrapped.version(), version);
    assert!(
        wrapped.snapshot().is_ok(),
        "the wrapped table must be usable without another load"
    );
}

/// One handle across several upserts: every commit must land on the version the
/// previous one produced, and an external writer's commit must be observed by the next
/// upsert through the incremental refresh (previously guaranteed by a full re-open).
#[tokio::test]
async fn handle_upserts_observe_own_and_external_commits() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t3").to_string_lossy().to_string();
    let s = create_seeded_table(&uri, true).await;

    let mut handle = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open handle");
    let v0 = handle.version();

    let stats = handle
        .upsert(
            vec![batch(&s, &["a", "c"], vec![Some(10), Some(11)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("first upsert");
    assert_eq!(stats.version, v0 + 1);
    assert_eq!(handle.version(), v0 + 1, "handle observes its own commit");

    // Another writer commits behind this handle's back.
    let mut other = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open external handle");
    other
        .upsert(
            vec![batch(&s, &["d"], vec![Some(12)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("external upsert");

    let stats = handle
        .upsert(
            vec![batch(&s, &["a"], vec![Some(13)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("second upsert");
    assert_eq!(
        stats.version,
        v0 + 3,
        "the upsert must plan against the externally-advanced version"
    );
}

/// The relax memo must never swallow a genuinely-needed relaxation: after upserts that
/// verify the non-nullable column clean (warming the cache), a batch that carries a
/// null in it still relaxes the column and commits the nulls.
#[tokio::test]
async fn warm_relax_cache_still_relaxes_when_the_batch_carries_nulls() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t4").to_string_lossy().to_string();
    let s = create_seeded_table(&uri, false).await;

    let mut handle = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open handle");

    // Two clean upserts through one handle: the second runs with a warm memo.
    for i in 0..2 {
        let stats = handle
            .upsert(
                vec![batch(&s, &["a"], vec![Some(20 + i)])],
                s.clone(),
                opts(),
                MultipartConfig::default(),
            )
            .await
            .expect("clean upsert");
        assert_eq!(stats.columns_relaxed, 0);
    }

    // Now the batch carries a null in the non-nullable column: the source-side check
    // (which the memo never bypasses) must relax `v` and the write must succeed.
    let nullable_schema = schema(true);
    let stats = handle
        .upsert(
            vec![batch(&nullable_schema, &["e"], vec![None])],
            nullable_schema.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("null-carrying upsert");
    assert_eq!(stats.columns_relaxed, 1, "the column must relax");

    // The relaxed schema is durable: a fresh handle sees `v` nullable and takes more
    // nulls without relaxing again.
    let mut fresh = TableHandle::open(uri, HashMap::new())
        .await
        .expect("fresh handle");
    let stats = fresh
        .upsert(
            vec![batch(&nullable_schema, &["f"], vec![None])],
            nullable_schema,
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("post-relax upsert");
    assert_eq!(stats.columns_relaxed, 0);
}
