//! The reader fetch budget (`UpsertOptions::max_fetch_bytes` and the process-wide
//! `DELTALITE_PROCESS_MAX_FETCH_BYTES`): it bounds the compressed row-group bytes that
//! readers hold at once, a row group larger than the budget still runs (alone), and
//! nothing deadlocks when every budget is tiny and many upserts share them.
//!
//! The bytes are measured, not inferred from the semaphore: the test store hands out
//! every `get_ranges` result as a `Bytes` whose owner decrements a live counter when the
//! parquet reader drops the last slice of it.

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, LazyLock, Mutex};
use std::time::Duration;

use arrow_array::{Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use bytes::Bytes;
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::logstore::{
    default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
    ObjectStoreFactory, StorageConfig,
};
use deltalake::operations::create::CreateBuilder;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalake::{DeltaResult, DeltaTable, Path};
use deltalite_core::limits::ProcessLimits;
use deltalite_core::table::open_table;
use deltalite_core::upsert::{upsert, PruneStrategy, UpsertOptions, UpsertStats};
use futures::stream::BoxStream;
use object_store::local::LocalFileSystem;
use object_store::{
    CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
    PutMultipartOptions, PutOptions, PutPayload, PutResult, RenameOptions,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

// ---- live-fetched-bytes accounting ----------------------------------------------

#[derive(Default)]
struct Gauge {
    live: AtomicUsize,
    peak: AtomicUsize,
    fetched: AtomicUsize,
}

impl Gauge {
    fn add(&self, n: usize) {
        let now = self.live.fetch_add(n, Ordering::SeqCst) + n;
        self.peak.fetch_max(now, Ordering::SeqCst);
        self.fetched.fetch_add(n, Ordering::SeqCst);
    }
}

/// Gauges by object-store path prefix; a test registers the directory its tables live
/// under, so tests running concurrently in this process measure only their own reads.
type Gauges = Vec<(String, Arc<Gauge>)>;
static GAUGES: LazyLock<Mutex<Gauges>> = LazyLock::new(Default::default);

fn gauge_for(dir: &std::path::Path) -> Arc<Gauge> {
    let g = Arc::new(Gauge::default());
    GAUGES.lock().unwrap().push((
        Path::from(dir.to_string_lossy().as_ref()).to_string(),
        g.clone(),
    ));
    g
}

fn find_gauge(location: &Path) -> Option<Arc<Gauge>> {
    GAUGES
        .lock()
        .unwrap()
        .iter()
        .find(|(prefix, _)| location.as_ref().starts_with(prefix.as_str()))
        .map(|(_, g)| g.clone())
}

/// Owner of fetched bytes that keeps the gauge honest for as long as any slice lives.
struct Tracked {
    bytes: Bytes,
    gauge: Arc<Gauge>,
}

impl AsRef<[u8]> for Tracked {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}

impl Drop for Tracked {
    fn drop(&mut self) {
        self.gauge
            .live
            .fetch_sub(self.bytes.len(), Ordering::SeqCst);
    }
}

#[derive(Debug)]
struct GaugedStore {
    inner: Arc<dyn ObjectStore>,
}

impl std::fmt::Display for GaugedStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "GaugedStore({})", self.inner)
    }
}

#[async_trait::async_trait]
impl ObjectStore for GaugedStore {
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
        ranges: &[std::ops::Range<u64>],
    ) -> object_store::Result<Vec<Bytes>> {
        let got = self.inner.get_ranges(location, ranges).await?;
        let Some(gauge) = find_gauge(location).filter(|_| location.as_ref().ends_with(".parquet"))
        else {
            return Ok(got);
        };
        Ok(got
            .into_iter()
            .map(|bytes| {
                gauge.add(bytes.len());
                Bytes::from_owner(Tracked {
                    bytes,
                    gauge: gauge.clone(),
                })
            })
            .collect())
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<Path>>,
    ) -> BoxStream<'static, object_store::Result<Path>> {
        self.inner.delete_stream(locations)
    }

    // Sorted: cloud stores list lexicographically and delta-kernel relies on it.
    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        sorted(self.inner.list(prefix))
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        sorted(self.inner.list_with_offset(prefix, offset))
    }

    async fn list_with_delimiter(&self, prefix: Option<&Path>) -> object_store::Result<ListResult> {
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
        let store = GaugedStore {
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

fn register_scheme() {
    let scheme = url::Url::parse("dlfetch://").expect("static url");
    object_store_factories().insert(scheme.clone(), Arc::new(Factory));
    logstore_factories().insert(scheme, Arc::new(Factory));
}

// ---- fixtures ----------------------------------------------------------------------

const FILES: usize = 8;
/// Rows per seeded file: one row group, and several read batches per row group, so a
/// reader keeps its fetched row group while it waits for decode budget between batches.
const ROWS: usize = 20_000;

fn schema(partitioned: bool) -> SchemaRef {
    let mut fields = vec![
        Field::new("pk", DataType::Utf8, false),
        Field::new("v", DataType::Int64, true),
        Field::new("payload", DataType::Utf8, true),
    ];
    if partitioned {
        fields.push(Field::new("p", DataType::Utf8, false));
    }
    Arc::new(Schema::new(fields))
}

/// Incompressible payload so the compressed row group is a meaningful size.
fn payload(seed: u64, i: usize) -> String {
    let mut x = seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ (i as u64);
    (0..4)
        .map(|_| {
            x = x
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            format!("{x:016x}")
        })
        .collect()
}

fn rows(
    schema: &SchemaRef,
    file: usize,
    ids: &[usize],
    v: i64,
    partition: Option<&str>,
) -> RecordBatch {
    let mut cols: Vec<Arc<dyn arrow_array::Array>> = vec![
        Arc::new(StringArray::from(
            ids.iter()
                .map(|i| format!("f{file}-{i}"))
                .collect::<Vec<_>>(),
        )),
        Arc::new(Int64Array::from(vec![v; ids.len()])),
        Arc::new(StringArray::from(
            ids.iter()
                .map(|i| payload(file as u64, *i))
                .collect::<Vec<_>>(),
        )),
    ];
    if let Some(p) = partition {
        cols.push(Arc::new(StringArray::from(vec![p; ids.len()])));
    }
    RecordBatch::try_new(schema.clone(), cols).unwrap()
}

/// A table of `FILES` single-row-group files per partition, written straight through
/// delta-rs. Returns the table's URI and the largest compressed row group in bytes.
async fn seed(dir: &std::path::Path, partitions: &[&str]) -> (String, usize) {
    let partitioned = !partitions.is_empty();
    let mut create = CreateBuilder::new()
        .with_location(dir.to_str().unwrap())
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("v", KernelType::LONG, true),
            StructField::new("payload", KernelType::STRING, true),
        ]);
    if partitioned {
        create = create
            .with_columns(vec![StructField::new("p", KernelType::STRING, false)])
            .with_partition_columns(vec!["p".to_string()]);
    }
    let mut table = create.await.unwrap();
    let s = schema(partitioned);
    let ids: Vec<usize> = (0..ROWS).collect();
    let parts: Vec<Option<&str>> = if partitioned {
        partitions.iter().map(|p| Some(*p)).collect()
    } else {
        vec![None]
    };
    for p in parts {
        for f in 0..FILES {
            let mut w = RecordBatchWriter::for_table(&table).unwrap();
            w.write(rows(&s, f, &ids, 0, p)).await.unwrap();
            w.flush_and_commit(&mut table).await.unwrap();
        }
    }

    let mut max_rg = 0usize;
    for uri in table.get_file_uris().unwrap() {
        let path = uri.strip_prefix("file://").unwrap_or(&uri);
        let bytes = Bytes::from(std::fs::read(path).unwrap());
        let meta = ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .metadata()
            .clone();
        assert_eq!(
            meta.num_row_groups(),
            1,
            "fixture files are single-row-group"
        );
        let rg: usize = meta
            .row_group(0)
            .columns()
            .iter()
            .map(|c| c.byte_range().1 as usize)
            .sum();
        max_rg = max_rg.max(rg);
    }
    (format!("dlfetch://{}", dir.to_string_lossy()), max_rg)
}

/// One update per seeded file (so every file is rewritten) and one insert per partition.
fn source(partitions: &[&str]) -> (SchemaRef, Vec<RecordBatch>) {
    let partitioned = !partitions.is_empty();
    let s = schema(partitioned);
    let parts: Vec<Option<&str>> = if partitioned {
        partitions.iter().map(|p| Some(*p)).collect()
    } else {
        vec![None]
    };
    let mut batches = Vec::new();
    for p in parts {
        for f in 0..FILES {
            batches.push(rows(&s, f, &[7], 1, p));
        }
        batches.push(rows(&s, 999, &[0], 1, p));
    }
    (s, batches)
}

fn opts(max_fetch_bytes: usize, limits: Arc<ProcessLimits>) -> UpsertOptions {
    UpsertOptions {
        primary_keys: vec!["pk".to_string()],
        // Read every file without probing, so readers are the only fetchers.
        prune_strategy: PruneStrategy::None,
        max_parallel_partitions: 4,
        max_parallel_files: FILES,
        // Small decode budget: a reader waits for budget between batches while it keeps
        // its fetched row group, so unbounded fetches overlap across all readers.
        max_buffered_bytes: 256 * 1024,
        max_fetch_bytes,
        limits,
        ..Default::default()
    }
}

fn roomy_limits() -> Arc<ProcessLimits> {
    Arc::new(ProcessLimits::with_fetch(64, 64, 1 << 30, 1 << 30))
}

async fn run(
    uri: &str,
    schema: SchemaRef,
    batches: Vec<RecordBatch>,
    o: UpsertOptions,
) -> UpsertStats {
    let table: DeltaTable = open_table(uri, HashMap::new()).await.unwrap();
    tokio::time::timeout(Duration::from_secs(300), upsert(&table, batches, schema, o))
        .await
        .expect("upsert deadlocked")
        .expect("upsert failed")
}

fn assert_rewrote_everything(stats: &UpsertStats, partitions: usize) {
    assert_eq!(stats.files_removed, FILES * partitions);
    assert_eq!(stats.rows_updated, FILES * partitions);
    assert_eq!(stats.rows_inserted, partitions);
    assert_eq!(stats.rows_copied, (ROWS - 1) * FILES * partitions);
}

// ---- tests -------------------------------------------------------------------------

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn fetch_budget_bounds_live_fetched_bytes() {
    register_scheme();
    // (case, budget in row groups, expected peak range in row groups)
    let cases: [(&str, f64, f64, f64); 3] = [
        // Without a binding budget every reader holds its row group at once.
        ("unbounded", 1e9, 3.0, FILES as f64 + 0.5),
        // A budget of 1.5 row groups admits exactly one reader at a time.
        ("one-and-a-half row groups", 1.5, 0.9, 1.5),
        // Smaller than one row group: the reader still runs, alone.
        ("smaller than one row group", 0.25, 0.9, 1.01),
    ];
    for (case, budget_rgs, min_peak, max_peak) in cases {
        let dir = tempfile::tempdir().unwrap();
        let (uri, rg) = seed(dir.path(), &[]).await;
        let gauge = gauge_for(dir.path());
        let (s, batches) = source(&[]);
        let budget = ((rg as f64) * budget_rgs).min((1u64 << 40) as f64) as usize;
        let stats = run(&uri, s, batches, opts(budget, roomy_limits())).await;
        assert_rewrote_everything(&stats, 1);

        let peak = gauge.peak.load(Ordering::SeqCst) as f64 / rg as f64;
        eprintln!(
            "{case}: row group {rg} B, budget {budget} B, peak live fetched {peak:.2} row groups"
        );
        assert!(
            gauge.fetched.load(Ordering::SeqCst) >= FILES * rg * 9 / 10,
            "{case}: every file's row group must be fetched through get_ranges"
        );
        assert!(
            (min_peak..=max_peak).contains(&peak),
            "{case}: peak live fetched bytes = {peak:.2} row groups, expected {min_peak}..={max_peak}"
        );
        assert_eq!(
            gauge.live.load(Ordering::SeqCst),
            0,
            "{case}: fetched bytes leaked"
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn process_fetch_budget_bounds_concurrent_upserts() {
    register_scheme();
    let root = tempfile::tempdir().unwrap();
    let gauge = gauge_for(root.path());
    let mut uris = Vec::new();
    let mut rg = 0;
    for i in 0..4 {
        let (uri, r) = seed(&root.path().join(format!("t{i}")), &[]).await;
        uris.push(uri);
        rg = r;
    }
    // Per-call budgets are roomy; only the shared process-wide fetch budget binds.
    let shared = Arc::new(ProcessLimits::with_fetch(64, 64, 1 << 30, rg * 3 / 2));
    let runs = uris.iter().map(|uri| {
        let (s, batches) = source(&[]);
        run(uri, s, batches, opts(1 << 40, shared.clone()))
    });
    for stats in futures::future::join_all(runs).await {
        assert_rewrote_everything(&stats, 1);
    }
    let peak = gauge.peak.load(Ordering::SeqCst);
    eprintln!(
        "4 concurrent upserts: row group {rg} B, process budget {} B, peak {peak} B",
        rg * 3 / 2
    );
    assert!(
        peak <= rg * 3 / 2,
        "process-wide peak {peak} B exceeds the {} B budget",
        rg * 3 / 2
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn tiny_budgets_shared_by_many_upserts_never_deadlock() {
    register_scheme();
    let root = tempfile::tempdir().unwrap();
    let partitions = ["a", "b", "c"];
    let mut uris = Vec::new();
    for i in 0..3 {
        let (uri, _) = seed(&root.path().join(format!("t{i}")), &partitions).await;
        uris.push(uri);
    }
    // Every budget is smaller than any single row group or decoded batch, and the
    // process-wide ones are shared by all three upserts, with the probe on.
    let shared = Arc::new(ProcessLimits::with_fetch(2, 3, 32 * 1024, 16 * 1024));
    let runs = uris.iter().map(|uri| {
        let (s, batches) = source(&partitions);
        let mut o = opts(8 * 1024, shared.clone());
        o.prune_strategy = PruneStrategy::Probe;
        o.max_buffered_bytes = 16 * 1024;
        run(uri, s, batches, o)
    });
    for stats in futures::future::join_all(runs).await {
        assert_rewrote_everything(&stats, partitions.len());
        assert_eq!(stats.files_probed, FILES * partitions.len());
    }
}
