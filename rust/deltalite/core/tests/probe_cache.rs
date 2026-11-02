//! The probe cache must not change what an upsert does. Each case runs the same upserts
//! against two copies of one table, one with a cache and one without, and requires the
//! same rows and the same file decisions after every upsert.

use std::collections::HashMap;
use std::sync::Arc;

use arrow_array::{Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::operations::create::CreateBuilder;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalake::Path;
use deltalite_core::compact::CompactOptions;
use deltalite_core::handle::TableHandle;
use deltalite_core::limits::ProcessLimits;
use deltalite_core::table::MultipartConfig;
use deltalite_core::upsert::{UpsertOptions, UpsertStats};
use deltalite_core::ProbeCache;
use object_store::ObjectStoreExt;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

const PARTITIONS: u64 = 5;
const SEED_KEYS: u64 = 2000;
const SEED_FLUSHES: u64 = 8;
const ROUNDS: u64 = 12;

#[derive(Clone, Copy, Debug)]
enum Keys {
    Int,
    Str,
    Composite,
    /// A PK that includes the partition column, which is not stored in the data files.
    WithPartition,
}

impl Keys {
    fn primary_keys(self) -> Vec<String> {
        let names: &[&str] = match self {
            Keys::Int => &["id_i"],
            Keys::Str => &["id_s"],
            Keys::Composite => &["id_s", "id_i"],
            Keys::WithPartition => &["id_i", "p"],
        };
        names.iter().map(|s| s.to_string()).collect()
    }
}

fn schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("id_i", DataType::Int64, true),
        Field::new("id_s", DataType::Utf8, true),
        Field::new("v", DataType::Int64, true),
        Field::new("p", DataType::Utf8, true),
    ]))
}

/// Rows for keys `ks` (key `k` lives in partition `k % PARTITIONS`), plus `null_rows`
/// rows whose PK columns are NULL, which never match and always insert.
fn rows(ks: &[u64], v: i64, null_rows: usize) -> RecordBatch {
    let mut id_i: Vec<Option<i64>> = ks.iter().map(|k| Some(*k as i64)).collect();
    let mut id_s: Vec<Option<String>> = ks.iter().map(|k| Some(format!("k{k:06}"))).collect();
    let mut p: Vec<String> = ks.iter().map(|k| (k % PARTITIONS).to_string()).collect();
    for i in 0..null_rows {
        id_i.push(None);
        id_s.push(None);
        p.push((i as u64 % PARTITIONS).to_string());
    }
    let n = id_i.len();
    RecordBatch::try_new(
        schema(),
        vec![
            Arc::new(Int64Array::from(id_i)),
            Arc::new(StringArray::from(id_s)),
            Arc::new(Int64Array::from(vec![v; n])),
            Arc::new(StringArray::from(p)),
        ],
    )
    .unwrap()
}

/// A partitioned table holding `SEED_KEYS` keys (offset by `offset`) in
/// `SEED_FLUSHES` files per partition.
async fn seed(dir: &std::path::Path, offset: u64) -> TableHandle {
    let mut table = CreateBuilder::new()
        .with_location(dir.to_str().unwrap())
        .with_columns(vec![
            StructField::new("id_i", KernelType::LONG, true),
            StructField::new("id_s", KernelType::STRING, true),
            StructField::new("v", KernelType::LONG, true),
            StructField::new("p", KernelType::STRING, true),
        ])
        .with_partition_columns(vec!["p".to_string()])
        .await
        .unwrap();
    let per_flush = SEED_KEYS / SEED_FLUSHES;
    for f in 0..SEED_FLUSHES {
        let ks: Vec<u64> = (offset + f * per_flush..offset + (f + 1) * per_flush).collect();
        let mut w = RecordBatchWriter::for_table(&table).unwrap();
        w.write(rows(&ks, 0, 0)).await.unwrap();
        w.flush_and_commit(&mut table).await.unwrap();
    }
    TableHandle::open(dir.to_str().unwrap().into(), HashMap::new())
        .await
        .unwrap()
}

/// Every live row as (id_i, id_s, v, p), sorted.
async fn read_rows(handle: &TableHandle) -> Vec<(Option<i64>, Option<String>, i64, String)> {
    let store = handle.table().object_store();
    let mut out = Vec::new();
    for f in handle.files().unwrap() {
        let p = f.partition_values["p"].clone().unwrap();
        let bytes = store
            .get(&Path::parse(&f.path).unwrap())
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap();
        for batch in ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .build()
            .unwrap()
        {
            let batch = batch.unwrap();
            let col = |name: &str| batch.column(batch.schema().index_of(name).unwrap()).clone();
            let (id_i, id_s, v) = (col("id_i"), col("id_s"), col("v"));
            let id_i = id_i.as_any().downcast_ref::<Int64Array>().unwrap();
            let id_s = id_s.as_any().downcast_ref::<StringArray>().unwrap();
            let v = v.as_any().downcast_ref::<Int64Array>().unwrap();
            for i in 0..batch.num_rows() {
                out.push((
                    (!id_i.is_null(i)).then(|| id_i.value(i)),
                    (!id_s.is_null(i)).then(|| id_s.value(i).to_string()),
                    v.value(i),
                    p.clone(),
                ));
            }
        }
    }
    out.sort();
    out
}

/// Deterministic pseudo-random sequence, so both copies get the same batches.
struct Lcg(u64);

impl Lcg {
    fn next(&mut self, below: u64) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (self.0 >> 33) % below
    }
}

/// One table under test: a copy with the cache and a copy without it.
struct Twin {
    cached: TableHandle,
    plain: TableHandle,
    offset: u64,
    /// Keys the last upsert wrote, so the next one hits files that the cache got from
    /// the writer rather than from a probe.
    last_keys: Vec<u64>,
    next_new_key: u64,
    _dirs: (tempfile::TempDir, tempfile::TempDir),
}

impl Twin {
    async fn new(offset: u64) -> Self {
        let (a, b) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
        Self {
            cached: seed(a.path(), offset).await,
            plain: seed(b.path(), offset).await,
            offset,
            last_keys: Vec::new(),
            next_new_key: offset + SEED_KEYS,
            _dirs: (a, b),
        }
    }

    fn batch_keys(&mut self, rng: &mut Lcg) -> Vec<u64> {
        let mut ks: Vec<u64> = Vec::new();
        ks.extend(self.last_keys.iter().take(20));
        ks.extend((0..40).map(|_| self.offset + rng.next(SEED_KEYS)));
        ks.extend(self.next_new_key..self.next_new_key + 15);
        self.next_new_key += 15;
        ks.sort_unstable();
        ks.dedup();
        self.last_keys = ks.clone();
        ks
    }
}

fn opts(keys: Keys, round: u64, cache: Option<Arc<ProbeCache>>) -> UpsertOptions {
    UpsertOptions {
        primary_keys: keys.primary_keys(),
        partition_key: Some("p".to_string()),
        limits: Arc::new(ProcessLimits::with_fetch(8, 16, 256 << 20, 256 << 20)),
        // Small files, so one upsert writes several files per partition.
        target_file_size: Some(2 * 1024),
        isolate_source_rows: round % 3 == 1,
        max_row_group_bytes: (round % 4 == 2).then_some(512),
        // One reader per partition makes the output layout deterministic, so the two
        // copies can be compared file decision by file decision.
        max_parallel_files: 1,
        probe_cache: cache,
        ..Default::default()
    }
}

/// The file decisions of an upsert, which the cache must not change.
fn decisions(s: &UpsertStats) -> [usize; 7] {
    [
        s.files_removed,
        s.files_added,
        s.files_carried_over,
        s.rows_updated,
        s.rows_inserted,
        s.rows_copied,
        s.null_pk_rows,
    ]
}

#[derive(Default)]
struct Totals {
    probed_cached: usize,
    probed_plain: usize,
    decided_from_cache: usize,
}

async fn upsert_round(
    twin: &mut Twin,
    keys: Keys,
    round: u64,
    rng: &mut Lcg,
    cache: &Arc<ProbeCache>,
    totals: &mut Totals,
) {
    let ks = twin.batch_keys(rng);
    let batch = rows(&ks, round as i64 + 1, 2);
    let with = twin
        .cached
        .upsert(
            vec![batch.clone()],
            schema(),
            opts(keys, round, Some(cache.clone())),
            MultipartConfig::default(),
        )
        .await
        .unwrap();
    let without = twin
        .plain
        .upsert(
            vec![batch],
            schema(),
            opts(keys, round, None),
            MultipartConfig::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        decisions(&with),
        decisions(&without),
        "{keys:?} round {round}: {with:?} vs {without:?}"
    );
    assert_eq!(
        read_rows(&twin.cached).await,
        read_rows(&twin.plain).await,
        "{keys:?} round {round}"
    );
    assert_eq!(without.files_probe_cached, 0);
    totals.probed_cached += with.files_probed;
    totals.probed_plain += without.files_probed;
    totals.decided_from_cache += with.files_probe_cached;
}

async fn compact_both(twin: &mut Twin) {
    let copts = || CompactOptions {
        target_file_size: Some(64 * 1024),
        limits: Arc::new(ProcessLimits::with_fetch(8, 16, 256 << 20, 256 << 20)),
        ..Default::default()
    };
    let a = twin
        .cached
        .compact(copts(), MultipartConfig::default())
        .await
        .unwrap();
    let b = twin
        .plain
        .compact(copts(), MultipartConfig::default())
        .await
        .unwrap();
    assert!(a.files_removed > 0);
    assert_eq!(a.files_removed, b.files_removed);
    assert_eq!(read_rows(&twin.cached).await, read_rows(&twin.plain).await);
}

/// Upserts into `tables` tables in turn, all sharing one cache of `cache_bytes`, with
/// one compaction halfway when `compact` is set.
async fn run(
    keys: Keys,
    tables: u64,
    cache_bytes: usize,
    compact: bool,
) -> (Totals, Arc<ProbeCache>) {
    let cache = Arc::new(ProbeCache::new(cache_bytes));
    let mut twins = Vec::new();
    for t in 0..tables {
        twins.push(Twin::new(t * 1_000_000).await);
    }
    let mut rng = Lcg(42);
    let mut totals = Totals::default();
    for round in 0..ROUNDS {
        for twin in twins.iter_mut() {
            upsert_round(twin, keys, round, &mut rng, &cache, &mut totals).await;
            if compact && round == ROUNDS / 2 {
                compact_both(twin).await;
            }
        }
    }
    (totals, cache)
}

#[tokio::test]
async fn cached_upserts_match_uncached_upserts_for_every_key_type() {
    for keys in [Keys::Int, Keys::Str, Keys::Composite, Keys::WithPartition] {
        let (totals, cache) = run(keys, 1, 64 << 20, true).await;
        // The cache must actually take part: most later probes come from it.
        assert!(totals.decided_from_cache > 0, "{keys:?}");
        assert!(
            totals.probed_cached * 2 < totals.probed_plain,
            "{keys:?}: probed {} with the cache, {} without",
            totals.probed_cached,
            totals.probed_plain
        );
        assert_eq!(cache.stats().evictions, 0, "{keys:?}");
    }
}

#[tokio::test]
async fn two_tables_can_share_one_cache() {
    let (totals, cache) = run(Keys::Composite, 2, 64 << 20, true).await;
    assert!(totals.decided_from_cache > 0);
    assert!(cache.stats().entries > 0);
}

#[tokio::test]
async fn a_cache_smaller_than_the_tables_evicts_and_stays_correct() {
    // Without compaction every file is small enough for an entry, but the files of the
    // three tables together are not.
    let (totals, cache) = run(Keys::Str, 3, 32 * 1024, false).await;
    let stats = cache.stats();
    assert!(stats.evictions > 0);
    assert!(stats.bytes <= 32 * 1024);
    assert!(totals.decided_from_cache > 0);
}

#[tokio::test]
async fn a_disabled_cache_probes_every_candidate() {
    let (totals, cache) = run(Keys::Int, 1, 0, true).await;
    assert_eq!(totals.decided_from_cache, 0);
    assert_eq!(totals.probed_cached, totals.probed_plain);
    assert_eq!(cache.stats().entries, 0);
}
