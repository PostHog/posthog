//! Object-store I/O benchmark for the upsert shapes production sees most.
//!
//! Wall clock on a local filesystem does not transfer to S3; the number of GETs, the
//! bytes they fetch, LISTs and PUTs do (each round trip costs tens of ms through the
//! proxy). The `counted://` store below counts them after object_store's range
//! coalescing, so the counts match what the S3 client issues, and can inject a fixed
//! per-request latency so the wall clock becomes a rough S3 proxy too.
//!
//! Scenarios (from the production upsert distribution):
//!   median    partitioned, 60 partitions x 1 file x 200 rows; 34-row update in one
//!             partition (one file probed, ~1 file rewritten)
//!   insert    unpartitioned, 173 files x 5k rows; 10k-row insert-only batch (the
//!             probe-heavy tail: every file's footer and PK column is read)
//!   smallbig  unpartitioned, 60 files x 20k rows; 34-row update touching 2 files
//!   mixed10k  unpartitioned, 60 files x 20k rows; 10k-row update spread over all files
//!
//! Usage:
//!   cargo run --release -p deltalite-core --example upsert_io -- \
//!     --scenario median [--iters 4] [--latency-ms 20] [--probe-concurrency 8] \
//!     [--max-parallel-files 4] [--dir /path]

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use arrow_array::{Float64Array, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef, TimeUnit};
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::operations::create::CreateBuilder;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalite_core::handle::TableHandle;
use deltalite_core::table::MultipartConfig;
use deltalite_core::upsert::UpsertOptions;

mod counted {
    use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use deltalake::logstore::{
        default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
        ObjectStoreFactory, StorageConfig,
    };
    use deltalake::{DeltaResult, Path};
    use futures::stream::BoxStream;
    use object_store::local::LocalFileSystem;
    use object_store::{
        coalesce_ranges, CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload,
        ObjectMeta, ObjectStore, PutMultipartOptions, PutOptions, PutPayload, PutResult,
        RenameOptions, OBJECT_STORE_COALESCE_DEFAULT,
    };

    pub static GETS: AtomicUsize = AtomicUsize::new(0);
    pub static GET_BYTES: AtomicU64 = AtomicU64::new(0);
    pub static LISTS: AtomicUsize = AtomicUsize::new(0);
    pub static WRITES: AtomicUsize = AtomicUsize::new(0);
    pub static PUT_BYTES: AtomicU64 = AtomicU64::new(0);
    pub static LATENCY_MS: AtomicU64 = AtomicU64::new(0);

    #[derive(Clone, Copy, Debug, Default)]
    pub struct Snap {
        pub gets: usize,
        pub get_bytes: u64,
        pub lists: usize,
        pub writes: usize,
        pub put_bytes: u64,
    }

    pub fn snapshot() -> Snap {
        Snap {
            gets: GETS.load(Ordering::Relaxed),
            get_bytes: GET_BYTES.load(Ordering::Relaxed),
            lists: LISTS.load(Ordering::Relaxed),
            writes: WRITES.load(Ordering::Relaxed),
            put_bytes: PUT_BYTES.load(Ordering::Relaxed),
        }
    }

    impl Snap {
        pub fn delta(&self, since: &Snap) -> Snap {
            Snap {
                gets: self.gets - since.gets,
                get_bytes: self.get_bytes - since.get_bytes,
                lists: self.lists - since.lists,
                writes: self.writes - since.writes,
                put_bytes: self.put_bytes - since.put_bytes,
            }
        }
    }

    async fn delay() {
        let ms = LATENCY_MS.load(Ordering::Relaxed);
        if ms > 0 {
            tokio::time::sleep(Duration::from_millis(ms)).await;
        }
    }

    fn sorted(
        stream: BoxStream<'static, object_store::Result<ObjectMeta>>,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        use futures::{StreamExt, TryStreamExt};
        futures::stream::once(async move {
            delay().await;
            let mut items: Vec<ObjectMeta> = stream.try_collect().await?;
            items.sort_by(|a, b| a.location.cmp(&b.location));
            Ok::<_, object_store::Error>(futures::stream::iter(items.into_iter().map(Ok)))
        })
        .try_flatten()
        .boxed()
    }

    /// Counts multipart part bytes (one `put_part` per part) and each part as a write.
    #[derive(Debug)]
    struct CountingUpload(Box<dyn MultipartUpload>);

    #[async_trait::async_trait]
    impl MultipartUpload for CountingUpload {
        fn put_part(&mut self, data: PutPayload) -> object_store::UploadPart {
            WRITES.fetch_add(1, Ordering::Relaxed);
            PUT_BYTES.fetch_add(data.content_length() as u64, Ordering::Relaxed);
            self.0.put_part(data)
        }
        async fn complete(&mut self) -> object_store::Result<PutResult> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            delay().await;
            self.0.complete().await
        }
        async fn abort(&mut self) -> object_store::Result<()> {
            self.0.abort().await
        }
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
            WRITES.fetch_add(1, Ordering::Relaxed);
            PUT_BYTES.fetch_add(payload.content_length() as u64, Ordering::Relaxed);
            delay().await;
            self.inner.put_opts(location, payload, opts).await
        }

        async fn put_multipart_opts(
            &self,
            location: &Path,
            opts: PutMultipartOptions,
        ) -> object_store::Result<Box<dyn MultipartUpload>> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            delay().await;
            let inner = self.inner.put_multipart_opts(location, opts).await?;
            Ok(Box::new(CountingUpload(inner)))
        }

        async fn get_opts(
            &self,
            location: &Path,
            options: GetOptions,
        ) -> object_store::Result<GetResult> {
            GETS.fetch_add(1, Ordering::Relaxed);
            delay().await;
            let r = self.inner.get_opts(location, options).await?;
            GET_BYTES.fetch_add(r.range.end - r.range.start, Ordering::Relaxed);
            Ok(r)
        }

        // Count the coalesced requests the S3 store would issue, not the raw ranges.
        async fn get_ranges(
            &self,
            location: &Path,
            ranges: &[std::ops::Range<u64>],
        ) -> object_store::Result<Vec<bytes::Bytes>> {
            coalesce_ranges(
                ranges,
                |r| async move {
                    use object_store::ObjectStoreExt;
                    self.get_range(location, r).await
                },
                OBJECT_STORE_COALESCE_DEFAULT,
            )
            .await
        }

        fn delete_stream(
            &self,
            locations: BoxStream<'static, object_store::Result<Path>>,
        ) -> BoxStream<'static, object_store::Result<Path>> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            self.inner.delete_stream(locations)
        }

        fn list(
            &self,
            prefix: Option<&Path>,
        ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
            LISTS.fetch_add(1, Ordering::Relaxed);
            sorted(self.inner.list(prefix))
        }

        fn list_with_offset(
            &self,
            prefix: Option<&Path>,
            offset: &Path,
        ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
            LISTS.fetch_add(1, Ordering::Relaxed);
            sorted(self.inner.list_with_offset(prefix, offset))
        }

        async fn list_with_delimiter(
            &self,
            prefix: Option<&Path>,
        ) -> object_store::Result<ListResult> {
            LISTS.fetch_add(1, Ordering::Relaxed);
            delay().await;
            self.inner.list_with_delimiter(prefix).await
        }

        async fn copy_opts(
            &self,
            from: &Path,
            to: &Path,
            options: CopyOptions,
        ) -> object_store::Result<()> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            self.inner.copy_opts(from, to, options).await
        }

        async fn rename_opts(
            &self,
            from: &Path,
            to: &Path,
            options: RenameOptions,
        ) -> object_store::Result<()> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            self.inner.rename_opts(from, to, options).await
        }
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

    pub fn register() {
        let scheme = url::Url::parse("counted://").expect("static url");
        object_store_factories().insert(scheme.clone(), Arc::new(Factory));
        logstore_factories().insert(scheme, Arc::new(Factory));
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Scenario {
    Median,
    Insert,
    SmallBig,
    Mixed10k,
}

impl Scenario {
    fn parse(s: &str) -> Self {
        match s {
            "median" => Self::Median,
            "insert" => Self::Insert,
            "smallbig" => Self::SmallBig,
            "mixed10k" => Self::Mixed10k,
            other => panic!("unknown scenario {other}"),
        }
    }
    fn name(self) -> &'static str {
        match self {
            Self::Median => "median",
            Self::Insert => "insert",
            Self::SmallBig => "smallbig",
            Self::Mixed10k => "mixed10k",
        }
    }
    fn partitioned(self) -> bool {
        matches!(self, Self::Median)
    }
    fn files(self) -> usize {
        match self {
            Self::Median => 60,
            Self::Insert => 173,
            Self::SmallBig | Self::Mixed10k => 60,
        }
    }
    fn rows_per_file(self) -> usize {
        match self {
            Self::Median => 200,
            Self::Insert => 5_000,
            Self::SmallBig | Self::Mixed10k => 20_000,
        }
    }
}

struct Args {
    scenario: Scenario,
    iters: usize,
    latency_ms: u64,
    probe_concurrency: usize,
    max_parallel_files: usize,
    dir: Option<PathBuf>,
}

fn parse_args() -> Args {
    let mut args = Args {
        scenario: Scenario::Median,
        iters: 4,
        latency_ms: 0,
        probe_concurrency: 8,
        max_parallel_files: 4,
        dir: None,
    };
    // nosemgrep: rust.lang.security.args.args
    let mut it = std::env::args().skip(1);
    while let Some(flag) = it.next() {
        let mut take = |name: &str| it.next().unwrap_or_else(|| panic!("{name} needs a value"));
        match flag.as_str() {
            "--scenario" => args.scenario = Scenario::parse(&take("--scenario")),
            "--iters" => args.iters = take("--iters").parse().expect("--iters"),
            "--latency-ms" => args.latency_ms = take("--latency-ms").parse().expect("--latency-ms"),
            "--probe-concurrency" => {
                args.probe_concurrency = take("--probe-concurrency")
                    .parse()
                    .expect("--probe-concurrency")
            }
            "--max-parallel-files" => {
                args.max_parallel_files = take("--max-parallel-files")
                    .parse()
                    .expect("--max-parallel-files")
            }
            "--dir" => args.dir = Some(PathBuf::from(take("--dir"))),
            other => panic!("unknown flag {other}"),
        }
    }
    args
}

fn arrow_schema(partitioned: bool) -> SchemaRef {
    let mut fields = vec![Field::new("id", DataType::Utf8, true)];
    if partitioned {
        fields.push(Field::new("p", DataType::Utf8, true));
    }
    for i in 0..4 {
        fields.push(Field::new(format!("i{i}"), DataType::Int64, true));
    }
    for i in 0..4 {
        fields.push(Field::new(format!("f{i}"), DataType::Float64, true));
    }
    for i in 0..3 {
        fields.push(Field::new(format!("s{i}"), DataType::Utf8, true));
    }
    fields.push(Field::new(
        "ts",
        DataType::Timestamp(TimeUnit::Microsecond, None),
        true,
    ));
    Arc::new(Schema::new(fields))
}

/// Deterministic UUID-shaped PK, random-looking so min/max stats prune nothing.
fn pk(ns: &str, i: usize) -> String {
    uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_OID, format!("{ns}:{i}").as_bytes()).to_string()
}

/// `rows` rows whose ids are `pk(ns, ids[r])`; `salt` varies payloads so a rewrite
/// really changes bytes.
fn batch(
    schema: &SchemaRef,
    partitioned: bool,
    partition: usize,
    ns: &str,
    ids: &[usize],
    salt: usize,
) -> RecordBatch {
    let n = ids.len();
    let mut cols: Vec<Arc<dyn arrow_array::Array>> = Vec::new();
    cols.push(Arc::new(StringArray::from(
        ids.iter().map(|i| pk(ns, *i)).collect::<Vec<_>>(),
    )));
    if partitioned {
        cols.push(Arc::new(StringArray::from(vec![
            format!("p{partition}");
            n
        ])));
    }
    for c in 0..4u64 {
        cols.push(Arc::new(Int64Array::from(
            ids.iter()
                .map(|i| ((*i as u64).wrapping_mul(0x9E37 + c) ^ salt as u64) as i64 % 1_000_000)
                .collect::<Vec<_>>(),
        )));
    }
    for c in 0..4u64 {
        cols.push(Arc::new(Float64Array::from(
            ids.iter()
                .map(|i| ((*i as u64 * (c + 3) + salt as u64) % 10_007) as f64 / 7.0)
                .collect::<Vec<_>>(),
        )));
    }
    for c in 0..3usize {
        cols.push(Arc::new(StringArray::from(
            ids.iter()
                .map(|i| {
                    format!(
                        "value-{c}-{:05}-{:06x}",
                        (i * 7919 + salt) % 50_000,
                        (i * 104729 + c) % 0xFFFFFF
                    )
                })
                .collect::<Vec<_>>(),
        )));
    }
    cols.push(Arc::new(TimestampMicrosecondArray::from(
        ids.iter()
            .map(|i| 1_700_000_000_000_000 + (*i as i64) * 1_000 + salt as i64)
            .collect::<Vec<_>>(),
    )));
    RecordBatch::try_new(schema.clone(), cols).expect("batch")
}

async fn create_table(uri: &str, partitioned: bool) -> deltalake::DeltaTable {
    let mut cols = vec![StructField::new("id", KernelType::STRING, true)];
    if partitioned {
        cols.push(StructField::new("p", KernelType::STRING, true));
    }
    for i in 0..4 {
        cols.push(StructField::new(format!("i{i}"), KernelType::LONG, true));
    }
    for i in 0..4 {
        cols.push(StructField::new(format!("f{i}"), KernelType::DOUBLE, true));
    }
    for i in 0..3 {
        cols.push(StructField::new(format!("s{i}"), KernelType::STRING, true));
    }
    cols.push(StructField::new("ts", KernelType::TIMESTAMP_NTZ, true));
    let mut b = CreateBuilder::new()
        .with_location(uri)
        .with_columns(cols)
        .with_configuration_property(deltalake::TableProperty::CheckpointInterval, Some("10"));
    if partitioned {
        b = b.with_partition_columns(vec!["p".to_string()]);
    }
    b.await.expect("create table")
}

/// One file per commit: file `f` holds rows `f*rows_per_file .. (f+1)*rows_per_file`
/// of namespace "base" (partition `f` when partitioned).
async fn build_fixture(uri: &str, sc: Scenario, schema: &SchemaRef) {
    let mut table = create_table(uri, sc.partitioned()).await;
    let mut writer = RecordBatchWriter::for_table(&table).expect("writer");
    for f in 0..sc.files() {
        let ids: Vec<usize> = (f * sc.rows_per_file()..(f + 1) * sc.rows_per_file()).collect();
        let b = batch(schema, sc.partitioned(), f, "base", &ids, 0);
        writer.write(b).await.expect("write");
        writer.flush_and_commit(&mut table).await.expect("commit");
        if (f + 1) % 50 == 0 {
            eprintln!("  fixture: {} / {} files", f + 1, sc.files());
        }
    }
}

fn copy_tree(src: &std::path::Path, dst: &std::path::Path) {
    std::fs::create_dir_all(dst).expect("mkdir copy target");
    for entry in std::fs::read_dir(src).expect("read fixture dir") {
        let entry = entry.expect("dir entry");
        let to = dst.join(entry.file_name());
        if entry.file_type().expect("file type").is_dir() {
            copy_tree(&entry.path(), &to);
        } else {
            std::fs::copy(entry.path(), &to).expect("copy fixture file");
        }
    }
}

/// The batch for iteration `i` of a scenario.
fn scenario_batch(sc: Scenario, schema: &SchemaRef, i: usize) -> RecordBatch {
    let rpf = sc.rows_per_file();
    match sc {
        Scenario::Median => {
            let p = i % sc.files();
            let ids: Vec<usize> = (p * rpf..p * rpf + 34).collect();
            batch(schema, true, p, "base", &ids, 1000 + i)
        }
        Scenario::Insert => {
            let ids: Vec<usize> = (i * 10_000..(i + 1) * 10_000).collect();
            batch(schema, false, 0, &format!("new{i}"), &ids, 1000 + i)
        }
        Scenario::SmallBig => {
            // 34 rows in two files, moving along the table each iteration.
            let f0 = (2 * i) % sc.files();
            let f1 = (2 * i + 1) % sc.files();
            let mut ids: Vec<usize> = (f0 * rpf..f0 * rpf + 17).collect();
            ids.extend(f1 * rpf..f1 * rpf + 17);
            batch(schema, false, 0, "base", &ids, 1000 + i)
        }
        Scenario::Mixed10k => {
            let total = sc.files() * rpf;
            let step = total / 10_000;
            let ids: Vec<usize> = (0..10_000).map(|k| (k * step + i) % total).collect();
            batch(schema, false, 0, "base", &ids, 1000 + i)
        }
    }
}

fn ms(from: Instant) -> f64 {
    from.elapsed().as_secs_f64() * 1000.0
}

#[tokio::main]
async fn main() {
    let args = parse_args();
    let sc = args.scenario;
    let schema = arrow_schema(sc.partitioned());

    let dir = args.dir.clone().unwrap_or_else(|| {
        // nosemgrep: rust.lang.security.temp-dir.temp-dir
        std::env::temp_dir().join(format!("deltalite-upsert-io-{}", sc.name()))
    });
    let marker = dir.join(".fixture-complete");
    if !marker.exists() {
        if dir.exists() {
            std::fs::remove_dir_all(&dir).expect("clear partial fixture");
        }
        std::fs::create_dir_all(&dir).expect("mkdir fixture");
        eprintln!("building fixture {} at {}", sc.name(), dir.display());
        let started = Instant::now();
        build_fixture(&dir.to_string_lossy(), sc, &schema).await;
        std::fs::write(&marker, b"ok").expect("write marker");
        eprintln!("fixture built in {:.1}s", started.elapsed().as_secs_f64());
    }

    let run_dir = dir.with_file_name(format!(
        "{}-run",
        dir.file_name().unwrap().to_string_lossy()
    ));
    if run_dir.exists() {
        std::fs::remove_dir_all(&run_dir).expect("clear run dir");
    }
    copy_tree(&dir, &run_dir);
    counted::register();
    counted::LATENCY_MS.store(args.latency_ms, std::sync::atomic::Ordering::Relaxed);
    let uri = format!("counted://{}", run_dir.to_string_lossy());
    let so: HashMap<String, String> = HashMap::new();

    let opts = UpsertOptions {
        primary_keys: vec!["id".to_string()],
        partition_key: sc.partitioned().then(|| "p".to_string()),
        probe_concurrency: args.probe_concurrency,
        max_parallel_files: args.max_parallel_files,
        ..Default::default()
    };
    println!(
        "upsert_io scenario={} iters={} latency_ms={} probe_concurrency={} max_parallel_files={}",
        sc.name(),
        args.iters,
        args.latency_ms,
        args.probe_concurrency,
        args.max_parallel_files,
    );

    let c0 = counted::snapshot();
    let t = Instant::now();
    let mut handle = TableHandle::open(uri.clone(), so.clone())
        .await
        .expect("open");
    let open_ms = ms(t);
    let d = counted::snapshot().delta(&c0);
    println!(
        "open_handle      gets {:4} ({:7.2} MB)  lists {:3}  writes {:3}  wall {:8.1} ms",
        d.gets,
        d.get_bytes as f64 / 1e6,
        d.lists,
        d.writes,
        open_ms
    );
    println!(
        "{:<4} {:>5} {:>9} {:>5} {:>6} {:>9} {:>9} {:>10} {:>7} {:>6} {:>6} {:>6} {:>8}",
        "iter",
        "gets",
        "get_MB",
        "lists",
        "writes",
        "put_MB",
        "wall_ms",
        "rewrite_ms",
        "open_ms",
        "probed",
        "rm",
        "add",
        "copied"
    );
    for i in 0..args.iters {
        let b = scenario_batch(sc, &schema, i);
        let c = counted::snapshot();
        let t = Instant::now();
        let stats = handle
            .upsert(
                vec![b],
                schema.clone(),
                opts.clone(),
                MultipartConfig::default(),
            )
            .await
            .expect("upsert");
        let wall = ms(t);
        let d = counted::snapshot().delta(&c);
        println!(
            "{:<4} {:>5} {:>9.2} {:>5} {:>6} {:>9.2} {:>9.1} {:>10} {:>7} {:>6} {:>6} {:>6} {:>8}",
            i,
            d.gets,
            d.get_bytes as f64 / 1e6,
            d.lists,
            d.writes,
            d.put_bytes as f64 / 1e6,
            wall,
            stats.rewrite_ms,
            stats.open_ms,
            stats.files_probed,
            stats.files_removed,
            stats.files_added,
            stats.rows_copied,
        );
    }
    // A refresh with nothing new to read: what one log refresh costs.
    let c = counted::snapshot();
    let t = Instant::now();
    handle.refresh().await.expect("refresh");
    let d = counted::snapshot().delta(&c);
    println!(
        "refresh_noop     gets {:4} ({:7.2} MB)  lists {:3}  writes {:3}  wall {:8.1} ms",
        d.gets,
        d.get_bytes as f64 / 1e6,
        d.lists,
        d.writes,
        ms(t)
    );
}
