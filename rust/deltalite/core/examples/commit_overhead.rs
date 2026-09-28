//! Per-commit overhead benchmark for the deltalite upsert path.
//!
//! Reproduces the production V3-loader call pattern: a Delta table with a deep commit
//! log (checkpoints at the table's `checkpoint_interval`, tombstone-heavy history) takes
//! repeated small upserts, and each iteration mirrors the exact orchestration of one
//! Python `DeltaLiteTable.open(...).upsert(...)` call so the open/replay overhead around
//! plan/rewrite/commit becomes visible per phase.
//!
//! Runs against the local filesystem, which UNDERSTATES the win on S3: a full log
//! replay here is cheap syscalls, while in production each replay is a LIST plus many
//! sequential GETs. Treat the numbers as a lower bound on the production improvement
//! and the replay *counts* as the transferable fact.
//!
//! Usage:
//!   cargo run --release -p deltalite-core --example commit_overhead -- \
//!     [--versions 1200] [--iters 40] [--rows 50] [--partitions 8] \
//!     [--non-nullable-pk] [--reuse-handle] [--dir /path/to/fixture]
//!
//! The fixture table is cached in `--dir` (or a temp dir keyed by the parameters) and
//! reused across runs, so only the first run pays the table-building cost.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use arrow_array::{Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef, TimeUnit};
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::operations::create::CreateBuilder;
use deltalite_core::handle::TableHandle;
use deltalite_core::table::{open_table_multipart, MultipartConfig};
use deltalite_core::upsert::{upsert, UpsertOptions};

/// Wall-clock on a local filesystem is noisy; the number of object-store operations is
/// not, and it is the quantity S3 latency multiplies in production. This store counts
/// reads (GET/HEAD/LIST) and writes per phase; it is registered under a `counted://`
/// scheme through delta-rs's factory registries so every open/replay in the run goes
/// through it.
mod counted {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use deltalake::logstore::{
        default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
        ObjectStoreFactory, StorageConfig,
    };
    use deltalake::{DeltaResult, Path};
    use futures::stream::BoxStream;
    use object_store::local::LocalFileSystem;
    use object_store::{
        CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
        PutMultipartOptions, PutOptions, PutPayload, PutResult, RenameOptions,
    };

    pub static GETS: AtomicUsize = AtomicUsize::new(0);
    pub static LISTS: AtomicUsize = AtomicUsize::new(0);
    pub static WRITES: AtomicUsize = AtomicUsize::new(0);

    /// (gets, lists, writes) since process start.
    pub fn snapshot() -> (usize, usize, usize) {
        (
            GETS.load(Ordering::Relaxed),
            LISTS.load(Ordering::Relaxed),
            WRITES.load(Ordering::Relaxed),
        )
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
            self.inner.put_opts(location, payload, opts).await
        }

        async fn put_multipart_opts(
            &self,
            location: &Path,
            opts: PutMultipartOptions,
        ) -> object_store::Result<Box<dyn MultipartUpload>> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            self.inner.put_multipart_opts(location, opts).await
        }

        async fn get_opts(
            &self,
            location: &Path,
            options: GetOptions,
        ) -> object_store::Result<GetResult> {
            GETS.fetch_add(1, Ordering::Relaxed);
            self.inner.get_opts(location, options).await
        }

        async fn get_ranges(
            &self,
            location: &Path,
            ranges: &[std::ops::Range<u64>],
        ) -> object_store::Result<Vec<bytes::Bytes>> {
            GETS.fetch_add(ranges.len(), Ordering::Relaxed);
            self.inner.get_ranges(location, ranges).await
        }

        fn delete_stream(
            &self,
            locations: BoxStream<'static, object_store::Result<Path>>,
        ) -> BoxStream<'static, object_store::Result<Path>> {
            WRITES.fetch_add(1, Ordering::Relaxed);
            self.inner.delete_stream(locations)
        }

        // Listings are sorted before they are returned: cloud stores list keys
        // lexicographically and delta-kernel relies on that, but `LocalFileSystem`
        // yields directory order.
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

struct Args {
    versions: usize,
    iters: usize,
    rows: usize,
    partitions: usize,
    non_nullable_pk: bool,
    reuse_handle: bool,
    dir: Option<PathBuf>,
}

fn parse_args() -> Args {
    let mut args = Args {
        versions: 1200,
        iters: 40,
        rows: 50,
        partitions: 8,
        non_nullable_pk: false,
        reuse_handle: false,
        dir: None,
    };
    // nosemgrep: rust.lang.security.args.args
    let mut it = std::env::args().skip(1);
    while let Some(flag) = it.next() {
        let mut take = |name: &str| it.next().unwrap_or_else(|| panic!("{name} needs a value"));
        match flag.as_str() {
            "--versions" => args.versions = take("--versions").parse().expect("--versions"),
            "--iters" => args.iters = take("--iters").parse().expect("--iters"),
            "--rows" => args.rows = take("--rows").parse().expect("--rows"),
            "--partitions" => args.partitions = take("--partitions").parse().expect("--partitions"),
            "--non-nullable-pk" => args.non_nullable_pk = true,
            "--reuse-handle" => args.reuse_handle = true,
            "--dir" => args.dir = Some(PathBuf::from(take("--dir"))),
            other => panic!("unknown flag {other}"),
        }
    }
    args
}

fn arrow_schema(non_nullable_pk: bool) -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("pk", DataType::Utf8, !non_nullable_pk),
        Field::new("p", DataType::Utf8, true),
        Field::new("v", DataType::Int64, true),
        Field::new("ts", DataType::Timestamp(TimeUnit::Microsecond, None), true),
        Field::new("payload", DataType::Utf8, true),
    ]))
}

/// Deterministic UUID-shaped PK: random-looking (so min/max stats prune nothing, like
/// production UUID keys) but stable per (partition, row) so upserts hit existing rows.
fn pk(partition: usize, row: usize) -> String {
    let ns = uuid::Uuid::NAMESPACE_OID;
    uuid::Uuid::new_v5(&ns, format!("{partition}:{row}").as_bytes()).to_string()
}

/// One batch of `rows` rows for `partition`, all updates of the fixture's fixed PKs.
/// `salt` varies the payload so every commit really rewrites bytes.
fn batch(schema: &SchemaRef, partition: usize, rows: usize, salt: usize) -> RecordBatch {
    let pks: Vec<String> = (0..rows).map(|r| pk(partition, r)).collect();
    let parts: Vec<String> = (0..rows).map(|_| format!("p{partition}")).collect();
    let vs: Vec<i64> = (0..rows).map(|r| (salt * 1000 + r) as i64).collect();
    let ts: Vec<i64> = (0..rows)
        .map(|r| 1_700_000_000_000_000 + (salt * rows + r) as i64)
        .collect();
    let payload: Vec<String> = (0..rows)
        .map(|r| format!("{}-{}", pk(partition, r), "x".repeat(180 + (salt + r) % 40)))
        .collect();
    RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(pks)),
            Arc::new(StringArray::from(parts)),
            Arc::new(Int64Array::from(vs)),
            Arc::new(TimestampMicrosecondArray::from(ts)),
            Arc::new(StringArray::from(payload)),
        ],
    )
    .expect("batch construction")
}

fn opts() -> UpsertOptions {
    UpsertOptions {
        primary_keys: vec!["pk".to_string()],
        partition_key: Some("p".to_string()),
        ..Default::default()
    }
}

async fn create_table(uri: &str, non_nullable_pk: bool) {
    let cols = vec![
        StructField::new("pk", KernelType::STRING, !non_nullable_pk),
        StructField::new("p", KernelType::STRING, true),
        StructField::new("v", KernelType::LONG, true),
        StructField::new("ts", KernelType::TIMESTAMP_NTZ, true),
        StructField::new("payload", KernelType::STRING, true),
    ];
    CreateBuilder::new()
        .with_location(uri)
        .with_columns(cols)
        .with_partition_columns(vec!["p".to_string()])
        .await
        .expect("create table");
}

/// Build `versions` commits: commit i updates partition `i % partitions` wholesale, so
/// the log grows deep (with tombstones and periodic checkpoints) while live files stay
/// at ~1 per partition -- matching production's files_probed p50 of 1.
async fn build_fixture(uri: &str, args: &Args, schema: &SchemaRef) {
    create_table(uri, args.non_nullable_pk).await;
    let so: HashMap<String, String> = HashMap::new();
    for i in 0..args.versions {
        let table = open_table_multipart(uri, so.clone(), MultipartConfig::default())
            .await
            .expect("open for fixture");
        let p = i % args.partitions;
        let b = batch(schema, p, args.rows, i);
        upsert(&table, vec![b], schema.clone(), opts())
            .await
            .expect("fixture upsert");
        if (i + 1) % 200 == 0 {
            eprintln!("  fixture: {} / {} commits", i + 1, args.versions);
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

fn ms(from: Instant) -> f64 {
    from.elapsed().as_secs_f64() * 1000.0
}

fn stat(label: &str, xs: &[f64]) {
    let mut sorted = xs.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let avg = xs.iter().sum::<f64>() / xs.len() as f64;
    let p50 = sorted[xs.len() / 2];
    let p95 = sorted[(((xs.len() as f64) * 0.95) as usize).min(xs.len() - 1)];
    println!("{label:<16} avg {avg:8.1}   p50 {p50:8.1}   p95 {p95:8.1}");
}

#[tokio::main]
async fn main() {
    let args = parse_args();
    let schema = arrow_schema(args.non_nullable_pk);

    // Benchmark-only fixture cache keyed by run parameters; not a security-sensitive
    // temp file, so a predictable name under the system temp dir is intentional here.
    let dir = args.dir.clone().unwrap_or_else(|| {
        // nosemgrep: rust.lang.security.temp-dir.temp-dir
        std::env::temp_dir().join(format!(
            "deltalite-commit-overhead-v{}-r{}-p{}-nn{}",
            args.versions, args.rows, args.partitions, args.non_nullable_pk as u8
        ))
    });
    let marker = dir.join(".fixture-complete");

    if !marker.exists() {
        if dir.exists() {
            std::fs::remove_dir_all(&dir).expect("clear partial fixture");
        }
        std::fs::create_dir_all(&dir).expect("mkdir fixture");
        eprintln!(
            "building fixture: {} commits at {}",
            args.versions,
            dir.display()
        );
        let started = Instant::now();
        build_fixture(&dir.to_string_lossy(), &args, &schema).await;
        std::fs::write(&marker, b"ok").expect("write marker");
        eprintln!("fixture built in {:.1}s", started.elapsed().as_secs_f64());
    } else {
        eprintln!("reusing fixture at {}", dir.display());
    }

    // Measure against a clone so the pristine fixture never grows: the measured upserts
    // would otherwise move the table's distance from its last checkpoint between runs,
    // and replay cost with it, making before/after comparisons unfair.
    let run_dir = dir.with_file_name(format!(
        "{}-run",
        dir.file_name().unwrap().to_string_lossy()
    ));
    if run_dir.exists() {
        std::fs::remove_dir_all(&run_dir).expect("clear run dir");
    }
    copy_tree(&dir, &run_dir);
    // Route the measured runs through the counting store so per-phase I/O op counts
    // come out alongside the (noisier) wall-clock numbers.
    counted::register();
    let uri = format!("counted://{}", run_dir.to_string_lossy());

    let so: HashMap<String, String> = HashMap::new();
    let multipart = MultipartConfig::default();

    let (
        mut t_open,
        mut t_refresh,
        mut t_plan,
        mut t_rewrite,
        mut t_commit,
        mut t_maint,
        mut t_total,
    ) = (vec![], vec![], vec![], vec![], vec![], vec![], vec![]);
    let mut t_relax: Vec<f64> = vec![];
    let mut probed = 0usize;
    // Per-phase I/O op deltas: (gets, lists, writes) for open/upsert per iteration.
    let mut io = [(0usize, 0usize, 0usize); 2];
    let track = |slot: &mut (usize, usize, usize), before: (usize, usize, usize)| {
        let now = counted::snapshot();
        slot.0 += now.0 - before.0;
        slot.1 += now.1 - before.1;
        slot.2 += now.2 - before.2;
        now
    };

    // `--reuse-handle` models a caller that keeps the handle across batches (the
    // production writer currently opens a fresh one per batch).
    let mut kept_handle: Option<TableHandle> = if args.reuse_handle {
        Some(
            TableHandle::open(uri.clone(), so.clone())
                .await
                .expect("open kept handle"),
        )
    } else {
        None
    };

    for i in 0..args.iters {
        let salt = args.versions + i + 1;
        let p = i % args.partitions;
        let b = batch(&schema, p, args.rows, salt);
        let total_started = Instant::now();
        let mut c = counted::snapshot();

        // Phase 1: what `DeltaLiteTable.open` does in production (fresh handle per
        // batch), unless the kept-handle mode amortises it away.
        let t = Instant::now();
        let mut handle = match kept_handle.take() {
            Some(h) => h,
            None => TableHandle::open(uri.clone(), so.clone())
                .await
                .expect("open handle"),
        };
        t_open.push(ms(t));
        c = track(&mut io[0], c);

        // Phase 2: the whole upsert entrypoint (refresh + retry loop + core upsert +
        // post-commit refresh), exactly what the Python binding runs.
        let stats = handle
            .upsert(vec![b], schema.clone(), opts(), multipart)
            .await
            .expect("bench upsert");
        t_refresh.push(stats.open_ms as f64);
        t_plan.push(stats.plan_ms as f64);
        t_rewrite.push(stats.rewrite_ms as f64);
        t_commit.push(stats.commit_ms as f64);
        t_maint.push(stats.maintenance_ms as f64);
        t_relax.push(stats.relax_ms as f64);
        probed += stats.files_probed;
        track(&mut io[1], c);

        if args.reuse_handle {
            kept_handle = Some(handle);
        }
        t_total.push(ms(total_started));
    }

    println!(
        "\ncommit_overhead: versions={} iters={} rows={} partitions={} non_nullable_pk={} reuse_handle={} (filesystem; understates S3)",
        args.versions, args.iters, args.rows, args.partitions, args.non_nullable_pk, args.reuse_handle
    );
    println!(
        "files_probed avg {:.1}\n",
        probed as f64 / args.iters as f64
    );
    stat("open_handle_ms", &t_open);
    stat("open_ms", &t_refresh);
    stat("relax_ms", &t_relax);
    stat("plan_ms", &t_plan);
    stat("rewrite_ms", &t_rewrite);
    stat("commit_ms", &t_commit);
    stat("maintenance_ms", &t_maint);
    stat("total_ms", &t_total);
    let named: f64 = [
        &t_open, &t_refresh, &t_relax, &t_plan, &t_rewrite, &t_commit, &t_maint,
    ]
    .iter()
    .map(|v| v.iter().sum::<f64>() / v.len() as f64)
    .sum();
    let total_avg = t_total.iter().sum::<f64>() / t_total.len() as f64;
    println!(
        "residual_ms      avg {:8.1}   (total minus named phases)",
        total_avg - named
    );

    println!("\nI/O ops per iteration (deterministic; what S3 latency multiplies):");
    let n = args.iters as f64;
    for (label, (g, l, w)) in ["open_handle", "handle_upsert"].iter().zip(io.iter()) {
        println!(
            "{label:<16} gets {:7.1}   lists {:6.1}   writes {:6.1}",
            *g as f64 / n,
            *l as f64 / n,
            *w as f64 / n
        );
    }
    let (tg, tl, tw) = io
        .iter()
        .fold((0, 0, 0), |a, b| (a.0 + b.0, a.1 + b.1, a.2 + b.2));
    println!(
        "{:<16} gets {:7.1}   lists {:6.1}   writes {:6.1}",
        "TOTAL",
        tg as f64 / n,
        tl as f64 / n,
        tw as f64 / n
    );
}
