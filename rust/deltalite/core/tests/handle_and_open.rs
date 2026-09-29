//! Integration tests for the open/refresh path: the single-load guarantee of
//! `open_table_multipart`, snapshot preservation in `wrap_multipart`, the checkpoint
//! prefetch, and the `TableHandle` upsert orchestration (incremental refresh, relax with
//! a warm cache, open timing, snapshot accessors).

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, Mutex};

use arrow_array::{Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::logstore::{
    default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
    ObjectStoreFactory, StorageConfig,
};
use deltalake::operations::create::CreateBuilder;
use deltalake::{DeltaResult, Path, TableProperty};
use deltalite_core::handle::TableHandle;
use deltalite_core::table::{open_table, open_table_multipart, wrap_multipart, MultipartConfig};
use deltalite_core::upsert::{upsert_cached_with_state, RelaxCache, UpsertOptions};
use futures::stream::BoxStream;
use object_store::local::LocalFileSystem;
use object_store::{
    CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
    PutMultipartOptions, PutOptions, PutPayload, PutResult, RenameOptions,
};

// ---- read-counting store, registered as its own URL scheme ------------------------

/// Reads (GET/HEAD/LIST) keyed by the path or listing prefix they targeted. Per path
/// rather than one global counter so the tests, which run concurrently in one process
/// and share this scheme, each measure only their own table.
static READS: LazyLock<Mutex<HashMap<String, usize>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// GETs per checkpoint Parquet file (one per `get_opts`, one per range in `get_ranges`),
/// keyed by path, so a test can assert how many round trips one checkpoint cost.
static CHECKPOINT_GETS: LazyLock<Mutex<HashMap<String, usize>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Every store call in issue order, so a test can ask what happened after a given point
/// (e.g. after the commit PUT). Parquet reads a footer through one `get_opts` and column
/// chunks through `get_ranges`, so the two GET kinds tell footer round trips from data
/// reads.
static OPS: LazyLock<Mutex<Vec<(Op, String)>>> = LazyLock::new(|| Mutex::new(Vec::new()));

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Op {
    Get,
    GetRange,
    Head,
    List,
    Put,
}

impl Op {
    fn is_read(self) -> bool {
        !matches!(self, Op::Put)
    }
}

fn record_read(target: String, n: usize) {
    *READS.lock().unwrap().entry(target).or_default() += n;
}

fn record_op(op: Op, target: &str) {
    OPS.lock().unwrap().push((op, target.to_string()));
}

/// Position in the op log; pass to [`ops_since`] to see only what happened afterwards.
fn ops_len() -> usize {
    OPS.lock().unwrap().len()
}

/// Ops issued since `start` against paths under `root`, in issue order.
fn ops_since(start: usize, root: &str) -> Vec<(Op, String)> {
    OPS.lock()
        .unwrap()
        .iter()
        .skip(start)
        .filter(|(_, path)| path.starts_with(root))
        .cloned()
        .collect()
}

/// The reads issued after the commit JSON for `version` was written: the log reads
/// deltalite spends on observing its own commit.
fn log_reads_after_commit(ops: &[(Op, String)], root: &str, version: i64) -> Vec<(Op, String)> {
    let commit = format!("{root}/_delta_log/{version:020}.json");
    let commit_at = ops
        .iter()
        .position(|(op, path)| *op == Op::Put && *path == commit)
        .unwrap_or_else(|| panic!("no PUT of {commit} in {ops:?}"));
    let log_root = format!("{root}/_delta_log");
    ops[commit_at + 1..]
        .iter()
        .filter(|(op, path)| op.is_read() && path.starts_with(&log_root))
        .cloned()
        .collect()
}

/// Footer GETs (`get_opts`, see [`OPS`]) per data file under `root`.
fn data_file_footer_gets(ops: &[(Op, String)], root: &str) -> HashMap<String, usize> {
    let log_root = format!("{root}/_delta_log");
    let mut out: HashMap<String, usize> = HashMap::new();
    for (op, path) in ops {
        if *op == Op::Get && path.ends_with(".parquet") && !path.starts_with(&log_root) {
            *out.entry(path.clone()).or_default() += 1;
        }
    }
    out
}

/// Reads issued against paths under `root` (an object-store path, no leading slash).
fn reads_under(root: &str) -> usize {
    READS
        .lock()
        .unwrap()
        .iter()
        .filter(|(path, _)| path.starts_with(root))
        .map(|(_, n)| n)
        .sum()
}

/// The object-store path a `dltest://<dir>` table's reads are recorded under.
fn table_root(dir: &std::path::Path) -> String {
    Path::from(dir.to_string_lossy().as_ref()).to_string()
}

fn count_checkpoint_get(location: &Path, n: usize) {
    if location.as_ref().contains(".checkpoint.") {
        *CHECKPOINT_GETS
            .lock()
            .unwrap()
            .entry(location.to_string())
            .or_default() += n;
    }
}

fn checkpoint_gets() -> HashMap<String, usize> {
    CHECKPOINT_GETS.lock().unwrap().clone()
}

/// Checkpoint GETs issued since `before`, per file.
fn checkpoint_gets_since(before: &HashMap<String, usize>) -> HashMap<String, usize> {
    checkpoint_gets()
        .into_iter()
        .filter_map(|(path, n)| {
            let delta = n - before.get(&path).copied().unwrap_or(0);
            (delta > 0).then_some((path, delta))
        })
        .collect()
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
        record_op(Op::Put, location.as_ref());
        self.inner.put_opts(location, payload, opts).await
    }

    async fn put_multipart_opts(
        &self,
        location: &Path,
        opts: PutMultipartOptions,
    ) -> object_store::Result<Box<dyn MultipartUpload>> {
        record_op(Op::Put, location.as_ref());
        self.inner.put_multipart_opts(location, opts).await
    }

    async fn get_opts(
        &self,
        location: &Path,
        options: GetOptions,
    ) -> object_store::Result<GetResult> {
        record_read(location.to_string(), 1);
        if options.head {
            record_op(Op::Head, location.as_ref());
        } else {
            record_op(Op::Get, location.as_ref());
            count_checkpoint_get(location, 1);
        }
        self.inner.get_opts(location, options).await
    }

    async fn get_ranges(
        &self,
        location: &Path,
        ranges: &[std::ops::Range<u64>],
    ) -> object_store::Result<Vec<bytes::Bytes>> {
        record_read(location.to_string(), ranges.len());
        for _ in ranges {
            record_op(Op::GetRange, location.as_ref());
        }
        count_checkpoint_get(location, ranges.len());
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
        record_read(prefix_key(prefix), 1);
        record_op(Op::List, &prefix_key(prefix));
        sorted(self.inner.list(prefix))
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        record_read(prefix_key(prefix), 1);
        record_op(Op::List, &prefix_key(prefix));
        sorted(self.inner.list_with_offset(prefix, offset))
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> object_store::Result<ListResult> {
        record_read(prefix_key(prefix), 1);
        record_op(Op::List, &prefix_key(prefix));
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

fn prefix_key(prefix: Option<&Path>) -> String {
    prefix.map(ToString::to_string).unwrap_or_default()
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
    create_seeded_table_with(uri, v_nullable, None, 3).await
}

/// [`create_seeded_table`] with a checkpoint interval and commit count. deltalite writes
/// a checkpoint when `(version + 1) % interval == 0`, so an interval of 2 over 4 commits
/// checkpoints versions 1 and 3 and leaves one JSON commit after the last checkpoint.
async fn create_seeded_table_with(
    uri: &str,
    v_nullable: bool,
    checkpoint_interval: Option<u32>,
    commits: i64,
) -> SchemaRef {
    let mut builder = CreateBuilder::new().with_location(uri).with_columns(vec![
        StructField::new("pk", KernelType::STRING, false),
        StructField::new("v", KernelType::LONG, v_nullable),
    ]);
    if let Some(interval) = checkpoint_interval {
        builder = builder.with_configuration_property(
            TableProperty::CheckpointInterval,
            Some(interval.to_string()),
        );
    }
    builder.await.expect("create table");

    let s = schema(v_nullable);
    for i in 0..commits {
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

/// Create an unpartitioned table at `uri` with one live file per key group. The groups
/// must have disjoint key ranges: each upsert's min/max then prunes the earlier files
/// by stats, so they are carried over instead of coalesced into one output file.
async fn create_disjoint_files_table(uri: &str, groups: &[&[&str]]) -> SchemaRef {
    CreateBuilder::new()
        .with_location(uri)
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("v", KernelType::LONG, true),
        ])
        .with_configuration_property(TableProperty::CheckpointInterval, Some("100".to_string()))
        .await
        .expect("create table");
    let s = schema(true);
    let mut handle = TableHandle::open(uri.to_string(), HashMap::new())
        .await
        .expect("open for seeding");
    for (i, keys) in groups.iter().enumerate() {
        let vs = keys.iter().map(|_| Some(i as i64)).collect();
        handle
            .upsert(
                vec![batch(&s, keys, vs)],
                s.clone(),
                opts(),
                MultipartConfig::default(),
            )
            .await
            .expect("seed group");
    }
    assert_eq!(handle.num_files().expect("num_files"), groups.len());
    s
}

/// Sorted live data-file paths of a fresh load: the log's own answer, for comparing
/// against what a handle's adopted state claims.
async fn live_paths_from_the_log(uri: &str) -> Vec<String> {
    let table = open_table(uri, HashMap::new()).await.expect("fresh open");
    let mut paths: Vec<String> = table
        .snapshot()
        .expect("snapshot")
        .log_data()
        .iter()
        .map(|f| f.path().to_string())
        .collect();
    paths.sort();
    paths
}

fn sorted_paths(handle: &TableHandle) -> Vec<String> {
    let mut paths: Vec<String> = handle
        .files()
        .expect("files")
        .into_iter()
        .map(|f| f.path)
        .collect();
    paths.sort();
    paths
}

/// Create a table partitioned on `p` at `uri` with one file in each of two partitions.
async fn create_partitioned_table(uri: &str) -> SchemaRef {
    CreateBuilder::new()
        .with_location(uri)
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("p", KernelType::STRING, true),
            StructField::new("v", KernelType::LONG, true),
        ])
        .with_partition_columns(vec!["p".to_string()])
        .await
        .expect("create partitioned table");

    let s: SchemaRef = Arc::new(Schema::new(vec![
        Field::new("pk", DataType::Utf8, false),
        Field::new("p", DataType::Utf8, true),
        Field::new("v", DataType::Int64, true),
    ]));
    let b = RecordBatch::try_new(
        s.clone(),
        vec![
            Arc::new(StringArray::from(vec!["a", "b"])),
            Arc::new(StringArray::from(vec!["x", "y"])),
            Arc::new(Int64Array::from(vec![1, 2])),
        ],
    )
    .expect("partitioned batch");
    let mut handle = TableHandle::open(uri.to_string(), HashMap::new())
        .await
        .expect("open for seeding");
    handle
        .upsert(
            vec![b],
            s.clone(),
            UpsertOptions {
                primary_keys: vec!["pk".to_string()],
                partition_key: Some("p".to_string()),
                ..Default::default()
            },
            MultipartConfig::default(),
        )
        .await
        .expect("partitioned seed upsert");
    s
}

// ---- tests -------------------------------------------------------------------------

/// Pins the double-load fix: opening through the multipart wrapper must cost the same
/// storage reads as a plain open, not twice as many.
#[tokio::test]
async fn open_table_multipart_replays_the_log_once() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let table_dir = dir.path().join("t1");
    let uri = format!("dltest://{}", table_dir.to_string_lossy());
    let root = table_root(&table_dir);
    create_seeded_table(&uri, true).await;

    let before_plain = reads_under(&root);
    let plain = open_table(&uri, HashMap::new()).await.expect("plain open");
    let plain_reads = reads_under(&root) - before_plain;

    let before_multipart = reads_under(&root);
    let multipart = open_table_multipart(&uri, HashMap::new(), MultipartConfig::default())
        .await
        .expect("multipart open");
    let multipart_reads = reads_under(&root) - before_multipart;

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

/// The checkpoint prefetch: a snapshot load must read each checkpoint Parquet file with
/// one whole-object GET instead of one ranged GET per footer, metadata and column chunk.
/// Covers both the initial open and the refresh that adopts a checkpoint the previous
/// upsert's own maintenance wrote at the version the handle already holds.
#[tokio::test]
async fn checkpoint_files_are_read_with_one_get_each() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = format!("dltest://{}", dir.path().join("t5").to_string_lossy());
    let s = create_seeded_table_with(&uri, true, Some(2), 4).await;

    let before = checkpoint_gets();
    let mut handle = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open handle");
    let opened = checkpoint_gets_since(&before);
    assert_eq!(handle.version(), 4);
    assert!(!opened.is_empty(), "the open must load from a checkpoint");
    for (path, gets) in &opened {
        assert_eq!(
            *gets, 1,
            "{path} was read with {gets} GETs; expected one prefetch"
        );
    }

    // Version 5 sits on the interval boundary: maintenance writes checkpoint 5 after the
    // commit whose state the handle adopted, so the next refresh rebuilds the snapshot
    // from that checkpoint (through the multipart-wrapped view's store).
    let before = checkpoint_gets();
    let stats = handle
        .upsert(
            vec![batch(&s, &["c"], vec![Some(9)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("boundary upsert");
    assert_eq!(stats.version, 5);
    let is_checkpoint_5 = |path: &str| path.contains("00000000000000000005.checkpoint");
    assert!(
        !checkpoint_gets_since(&before)
            .keys()
            .any(|p| is_checkpoint_5(p)),
        "adopting the commit state must not read the checkpoint it just wrote"
    );
    let before = checkpoint_gets();
    handle.refresh().await.expect("refresh");
    let refreshed = checkpoint_gets_since(&before);
    assert!(
        refreshed.keys().any(|p| is_checkpoint_5(p)),
        "the refresh must adopt the new checkpoint (read: {refreshed:?})"
    );
    for (path, gets) in &refreshed {
        assert_eq!(
            *gets, 1,
            "{path} was read with {gets} GETs; expected one prefetch"
        );
    }
}

/// The full load that opens a handle is reported once, on the first upsert through it,
/// so a caller summing per-upsert stats attributes the open cost exactly once.
#[tokio::test]
async fn initial_open_is_timed_and_reported_on_the_first_upsert_only() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t6").to_string_lossy().to_string();
    let s = create_seeded_table_with(&uri, true, Some(2), 6).await;

    let mut handle = TableHandle::open(uri, HashMap::new())
        .await
        .expect("open handle");
    assert!(
        handle.initial_open_ms() > 0,
        "a checkpoint load plus log replay must register on the clock"
    );

    let first = handle
        .upsert(
            vec![batch(&s, &["a"], vec![Some(1)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("first upsert");
    assert_eq!(first.initial_open_ms, handle.initial_open_ms());

    let second = handle
        .upsert(
            vec![batch(&s, &["a"], vec![Some(2)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("second upsert");
    assert_eq!(second.initial_open_ms, 0, "reported once per handle");
}

/// The snapshot accessors describe the loaded table without I/O and agree with what
/// delta-rs itself reports for the same snapshot.
#[tokio::test]
async fn snapshot_accessors_describe_the_loaded_table() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let table_dir = dir.path().join("t7");
    let uri = format!("dltest://{}", table_dir.to_string_lossy());
    let root = table_root(&table_dir);
    create_seeded_table_with(&uri, true, Some(2), 3).await;

    let handle = TableHandle::open(uri, HashMap::new())
        .await
        .expect("open handle");
    let snapshot = handle.table().snapshot().expect("loaded snapshot");

    let before = reads_under(&root);
    let files = handle.files().expect("files");
    let uris: Vec<String> = handle.table().get_file_uris().expect("file uris").collect();
    assert_eq!(files.len(), uris.len());
    assert_eq!(handle.num_files().expect("num_files"), files.len());
    for f in &files {
        assert!(
            uris.iter().any(|u| u.ends_with(&f.path)),
            "{} is not a live file ({uris:?})",
            f.path
        );
        assert!(f.size > 0);
        assert!(f.modification_time > 0);
        assert!(f.partition_values.is_empty(), "unpartitioned table");
    }

    let schema: serde_json::Value =
        serde_json::from_str(&handle.schema_json().expect("schema_json")).expect("valid json");
    assert_eq!(schema["type"], "struct");
    let names: Vec<&str> = schema["fields"]
        .as_array()
        .expect("fields")
        .iter()
        .map(|f| f["name"].as_str().expect("name"))
        .collect();
    assert_eq!(names, ["pk", "v"]);

    assert_eq!(
        handle.table_id().expect("table_id"),
        snapshot.metadata().id()
    );
    let configuration = handle.configuration().expect("configuration");
    assert_eq!(&configuration, snapshot.metadata().configuration());
    assert_eq!(
        configuration
            .get("delta.checkpointInterval")
            .map(String::as_str),
        Some("2")
    );
    assert_eq!(
        reads_under(&root),
        before,
        "accessors must be served from memory"
    );
}

#[tokio::test]
async fn files_carry_partition_values() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t8").to_string_lossy().to_string();
    create_partitioned_table(&uri).await;

    let handle = TableHandle::open(uri, HashMap::new())
        .await
        .expect("open handle");
    let mut files = handle.files().expect("files");
    files.sort_by(|a, b| a.path.cmp(&b.path));
    assert_eq!(files.len(), 2);
    let mut partitions: Vec<Option<String>> = files
        .iter()
        .map(|f| {
            assert_eq!(f.partition_values.len(), 1);
            assert!(f.path.starts_with(&format!(
                "p={}/",
                f.partition_values["p"]
                    .as_deref()
                    .unwrap_or("__HIVE_DEFAULT_PARTITION__")
            )));
            f.partition_values["p"].clone()
        })
        .collect();
    partitions.sort();
    assert_eq!(partitions, [Some("x".to_string()), Some("y".to_string())]);
}

/// Footer reuse is limited to one reader wave so metadata retained between the probe
/// and rewrite phases cannot grow with the partition's file count.
#[tokio::test]
async fn hit_file_footer_reuse_is_bounded_by_reader_concurrency() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let table_dir = dir.path().join("t9");
    let uri = format!("dltest://{}", table_dir.to_string_lossy());
    let root = table_root(&table_dir);
    let s = create_disjoint_files_table(
        &uri,
        &[
            &["a0", "a1", "a2", "a3"],
            &["b0", "b1", "b2", "b3"],
            &["c0", "c1", "c2", "c3"],
            &["d0", "d1", "d2", "d3"],
            &["e0", "e1", "e2", "e3"],
        ],
    )
    .await;

    let mut handle = TableHandle::open(uri, HashMap::new())
        .await
        .expect("open handle");
    let hit_files: Vec<String> = handle
        .files()
        .expect("files")
        .into_iter()
        .map(|f| format!("{root}/{}", f.path))
        .collect();
    assert_eq!(hit_files.len(), 5);

    let start = ops_len();
    let stats = handle
        .upsert(
            vec![batch(
                &s,
                &["a2", "b2", "c2", "d2", "e2"],
                vec![Some(7), Some(7), Some(7), Some(7), Some(7)],
            )],
            s.clone(),
            UpsertOptions {
                max_parallel_files: 2,
                ..opts()
            },
            MultipartConfig::default(),
        )
        .await
        .expect("upsert");
    assert_eq!(stats.files_probed, 5);
    assert_eq!(stats.files_removed, 5);

    let footer_gets = data_file_footer_gets(&ops_since(start, &root), &root);
    let counts: Vec<usize> = hit_files
        .iter()
        .map(|path| footer_gets.get(path).copied().unwrap_or(0))
        .collect();
    assert_eq!(counts.iter().filter(|&&count| count == 1).count(), 2);
    assert_eq!(counts.iter().filter(|&&count| count == 2).count(), 3);
}

/// After the commit the handle adopts the state delta-rs derived for it instead of
/// listing the log and reading `_last_checkpoint` again, and that state is the log's
/// truth.
#[tokio::test]
async fn adopting_the_commit_snapshot_skips_the_post_commit_refresh() {
    register_counting_scheme();
    let dir = tempfile::tempdir().expect("tempdir");
    let table_dir = dir.path().join("t10");
    let uri = format!("dltest://{}", table_dir.to_string_lossy());
    let root = table_root(&table_dir);
    let s = create_disjoint_files_table(&uri, &[&["a0", "a1"], &["b0", "b1"]]).await;

    let mut handle = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open handle");
    assert!(handle.adopt_commit_snapshot(), "adoption is on by default");

    let mut reads_by_mode = Vec::new();
    let mut versions = Vec::new();
    for (adopt, key) in [(true, "a1"), (false, "b1")] {
        handle.set_adopt_commit_snapshot(adopt);
        let start = ops_len();
        let stats = handle
            .upsert(
                vec![batch(&s, &[key], vec![Some(3)])],
                s.clone(),
                opts(),
                MultipartConfig::default(),
            )
            .await
            .expect("upsert");
        // Captured before the fresh load below, whose replay must not be counted.
        versions.push(stats.version);
        reads_by_mode.push(log_reads_after_commit(
            &ops_since(start, &root),
            &root,
            stats.version,
        ));
        assert_eq!(handle.version(), stats.version);
        assert_eq!(
            sorted_paths(&handle),
            live_paths_from_the_log(&uri).await,
            "the handle's state must match the log (adopt={adopt})"
        );
    }

    // delta-rs derives the commit's state with one log LIST (plus reads of the commit
    // JSON it just wrote); a post-commit refresh would LIST the log a second time.
    let lists = |reads: &[(Op, String)]| reads.iter().filter(|(op, _)| *op == Op::List).count();
    let (adopted, refreshed) = (&reads_by_mode[0], &reads_by_mode[1]);
    assert_eq!(
        lists(adopted),
        1,
        "the handle must not refresh after adopting the commit state (reads: {adopted:?})"
    );
    assert!(
        adopted
            .iter()
            .all(|(op, path)| *op == Op::List
                || path.ends_with(&format!("{:020}.json", versions[0]))),
        "after the commit only the commit's own JSON may be read (reads: {adopted:?})"
    );
    assert_eq!(
        lists(refreshed),
        2,
        "the kill-switch path still refreshes after the commit (reads: {refreshed:?})"
    );
}

/// The adopted state stays a valid base for later refreshes: after a boundary commit
/// (maintenance writes a checkpoint at the adopted version) and an external writer's
/// commit, the next upsert lands on the externally-advanced version and the handle's
/// file list still matches the log.
#[tokio::test]
async fn adopted_snapshot_observes_maintenance_and_external_commits() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t11").to_string_lossy().to_string();
    let s = create_seeded_table_with(&uri, true, Some(2), 4).await;

    let mut handle = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open handle");
    let stats = handle
        .upsert(
            vec![batch(&s, &["c"], vec![Some(1)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("boundary upsert");
    assert_eq!(stats.version, 5);
    assert_eq!(handle.version(), 5);
    assert_eq!(sorted_paths(&handle), live_paths_from_the_log(&uri).await);

    let mut other = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open external handle");
    let stats = other
        .upsert(
            vec![batch(&s, &["d"], vec![Some(2)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("external upsert");
    assert_eq!(stats.version, 6);

    let stats = handle
        .upsert(
            vec![batch(&s, &["c", "d"], vec![Some(3), Some(3)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("upsert after external commit");
    assert_eq!(stats.version, 7);
    assert_eq!(handle.version(), 7);
    assert_eq!(sorted_paths(&handle), live_paths_from_the_log(&uri).await);
}

/// When another writer's commit lands between the snapshot read and the commit and
/// delta-rs retries at the next version, the state returned with the commit includes
/// that writer's file, so a handle adopting it is not behind the log.
#[tokio::test]
async fn commit_state_includes_a_writer_that_landed_first() {
    let dir = tempfile::tempdir().expect("tempdir");
    let uri = dir.path().join("t12").to_string_lossy().to_string();
    let s = create_disjoint_files_table(&uri, &[&["a0", "a1"]]).await;

    let stale = open_table(&uri, HashMap::new()).await.expect("open");
    let v0 = stale.version().expect("loaded");

    // Insert-only, disjoint from every live file: an Add-only commit that delta-rs's
    // conflict checker lets a retried commit land on top of.
    let mut other = TableHandle::open(uri.clone(), HashMap::new())
        .await
        .expect("open external handle");
    other
        .upsert(
            vec![batch(&s, &["m0", "m1"], vec![Some(1), Some(1)])],
            s.clone(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .expect("external upsert");

    let (stats, state) = upsert_cached_with_state(
        &stale,
        vec![batch(&s, &["x0", "x1"], vec![Some(2), Some(2)])],
        s.clone(),
        opts(),
        &mut RelaxCache::default(),
    )
    .await
    .expect("upsert behind the external commit");
    assert_eq!(stats.version, v0 as i64 + 2, "committed after the retry");
    assert_eq!(state.version(), v0 + 2);

    let mut adopted: Vec<String> = state
        .log_data()
        .iter()
        .map(|f| f.path().to_string())
        .collect();
    adopted.sort();
    assert_eq!(adopted.len(), 3, "seed file, external file, own file");
    assert_eq!(adopted, live_paths_from_the_log(&uri).await);
}
