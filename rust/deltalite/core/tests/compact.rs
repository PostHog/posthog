//! Integration tests for `deltalite_core::compact`: the OPTIMIZE commit it writes, the
//! no-I/O plan, the output layout knobs, and its behaviour when another writer commits
//! between its plan and its commit. Every test checks the log replays cleanly (no file
//! removed twice or removed while not live) and that no uncommitted output file is left
//! in the table directory.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use arrow_array::{Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use bytes::Bytes;
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::operations::create::CreateBuilder;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalake::{DeltaTable, Path};
use deltalite_core::compact::{compact, CompactOptions, CompactStats};
use deltalite_core::handle::TableHandle;
use deltalite_core::limits::ProcessLimits;
use deltalite_core::table::{open_table, MultipartConfig};
use deltalite_core::upsert::UpsertOptions;
use deltalite_core::Error;
use object_store::ObjectStoreExt;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use parquet::file::properties::WriterProperties;
use serde_json::Value;

// ---- fixtures ----------------------------------------------------------------------

fn schema(partitioned: bool) -> SchemaRef {
    let mut fields = vec![
        Field::new("pk", DataType::Utf8, false),
        Field::new("v", DataType::Int64, true),
        Field::new("payload", DataType::Utf8, true),
    ];
    if partitioned {
        fields.push(Field::new("p", DataType::Utf8, true));
    }
    Arc::new(Schema::new(fields))
}

/// Rows `pk = <prefix><i>` for `i` in `ids`, each with value `v` and a `payload_len`
/// payload (every third payload NULL).
fn rows(
    s: &SchemaRef,
    prefix: &str,
    ids: std::ops::Range<usize>,
    v: i64,
    payload_len: usize,
    p: Option<&str>,
) -> RecordBatch {
    let n = ids.len();
    let pks: Vec<String> = ids.clone().map(|i| format!("{prefix}{i:06}")).collect();
    let payload: Vec<Option<String>> = ids
        .map(|i| (i % 3 != 0).then(|| format!("{i}-").repeat(payload_len / 4 + 1)))
        .collect();
    let mut cols: Vec<Arc<dyn Array>> = vec![
        Arc::new(StringArray::from(pks)),
        Arc::new(Int64Array::from(vec![v; n])),
        Arc::new(StringArray::from(payload)),
    ];
    if s.fields().len() == 4 {
        cols.push(Arc::new(StringArray::from(vec![p; n])));
    }
    RecordBatch::try_new(s.clone(), cols).unwrap()
}

async fn create(dir: &std::path::Path, partitioned: bool) -> DeltaTable {
    let mut builder = CreateBuilder::new()
        .with_location(dir.to_str().unwrap())
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("v", KernelType::LONG, true),
            StructField::new("payload", KernelType::STRING, true),
        ]);
    if partitioned {
        builder = builder
            .with_columns(vec![StructField::new("p", KernelType::STRING, true)])
            .with_partition_columns(vec!["p".to_string()]);
    }
    builder.await.unwrap()
}

/// Append `batch` as one commit through delta-rs (one new file per partition).
async fn append(table: &mut DeltaTable, batch: RecordBatch, props: Option<WriterProperties>) {
    let mut w = RecordBatchWriter::for_table(table).unwrap();
    if let Some(props) = props {
        w = w.with_writer_properties(props);
    }
    w.write(batch).await.unwrap();
    w.flush_and_commit(table).await.unwrap();
}

/// `files` small appends per partition value, keys disjoint across files.
async fn fragmented(
    dir: &std::path::Path,
    partitions: &[Option<&str>],
    files: usize,
    rows_per_file: usize,
) -> DeltaTable {
    let partitioned = !partitions.is_empty();
    let mut table = create(dir, partitioned).await;
    let s = schema(partitioned);
    let parts: Vec<Option<&str>> = if partitioned {
        partitions.to_vec()
    } else {
        vec![None]
    };
    for f in 0..files {
        for (i, p) in parts.iter().enumerate() {
            let start = f * rows_per_file;
            let b = rows(
                &s,
                &format!("k{i}-"),
                start..start + rows_per_file,
                f as i64,
                40,
                *p,
            );
            append(&mut table, b, None).await;
        }
    }
    table
}

type Row = (Option<String>, String, Option<i64>, Option<String>);

/// Every live row as (partition, pk, v, payload), sorted, read through the table's store.
async fn read_rows(table: &DeltaTable) -> Vec<Row> {
    let store = table.object_store();
    let mut out = Vec::new();
    for view in table.snapshot().unwrap().log_data().iter() {
        let remove = view.remove_action(false);
        let p = remove
            .partition_values
            .as_ref()
            .and_then(|pv| pv.get("p").cloned().flatten());
        let path = Path::parse(view.path().as_ref()).unwrap();
        let bytes: Bytes = store.get(&path).await.unwrap().bytes().await.unwrap();
        for batch in ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .build()
            .unwrap()
        {
            let batch = batch.unwrap();
            let col = |name: &str| batch.column(batch.schema().index_of(name).unwrap()).clone();
            let pk = col("pk");
            let pk = pk.as_any().downcast_ref::<StringArray>().unwrap();
            let v = col("v");
            let v = v.as_any().downcast_ref::<Int64Array>().unwrap();
            let payload = col("payload");
            let payload = payload.as_any().downcast_ref::<StringArray>().unwrap();
            for i in 0..batch.num_rows() {
                out.push((
                    p.clone(),
                    pk.value(i).to_string(),
                    (!v.is_null(i)).then(|| v.value(i)),
                    (!payload.is_null(i)).then(|| payload.value(i).to_string()),
                ));
            }
        }
    }
    out.sort();
    out
}

async fn reopen(dir: &std::path::Path) -> DeltaTable {
    open_table(dir.to_str().unwrap(), HashMap::new())
        .await
        .unwrap()
}

/// Actions of every commit, by version.
fn commits(dir: &std::path::Path) -> BTreeMap<u64, Vec<Value>> {
    let mut out = BTreeMap::new();
    for entry in std::fs::read_dir(dir.join("_delta_log")).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let Some(stem) = name.strip_suffix(".json") else {
            continue;
        };
        let Ok(version) = stem.parse::<u64>() else {
            continue;
        };
        let actions = std::fs::read_to_string(&path)
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect();
        out.insert(version, actions);
    }
    out
}

fn name(path: &str) -> String {
    path.rsplit('/').next().unwrap().to_string()
}

/// Replays the log: no remove of a file that is not live, every OPTIMIZE action has
/// `dataChange=false`. Returns the live file names and the OPTIMIZE commits.
fn assert_log_valid(dir: &std::path::Path) -> (HashSet<String>, Vec<Vec<Value>>) {
    let mut live: HashSet<String> = HashSet::new();
    let mut optimizes = Vec::new();
    let log = commits(dir);
    let versions: Vec<u64> = log.keys().copied().collect();
    assert_eq!(
        versions,
        (0..versions.len() as u64).collect::<Vec<_>>(),
        "contiguous log"
    );
    for (version, actions) in log {
        let op = actions
            .iter()
            .find_map(|a| a.get("commitInfo"))
            .and_then(|c| c.get("operation"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        for a in &actions {
            if let Some(r) = a.get("remove") {
                let n = name(r["path"].as_str().unwrap());
                assert!(
                    live.remove(&n),
                    "v{version} ({op}) removes {n}, which is not live"
                );
                if op == "OPTIMIZE" {
                    assert_eq!(r["dataChange"], false, "v{version} remove");
                }
            }
            if let Some(add) = a.get("add") {
                let n = name(add["path"].as_str().unwrap());
                assert!(live.insert(n.clone()), "v{version} adds {n} twice");
                if op == "OPTIMIZE" {
                    assert_eq!(add["dataChange"], false, "v{version} add");
                }
            }
        }
        if op == "OPTIMIZE" {
            optimizes.push(actions);
        }
    }
    (live, optimizes)
}

/// Every compaction output (ZSTD; the fixtures and upserts write SNAPPY) in the table
/// directory was added by some commit. Upserts that lose a race leave their own
/// outputs behind, which is not what these tests check.
fn assert_no_orphans(dir: &std::path::Path) {
    let mut added: HashSet<String> = HashSet::new();
    for actions in commits(dir).values() {
        for a in actions {
            if let Some(add) = a.get("add") {
                added.insert(name(add["path"].as_str().unwrap()));
            }
        }
    }
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                if !path.ends_with("_delta_log") {
                    stack.push(path);
                }
            } else if path.to_string_lossy().ends_with(".zstd.parquet") {
                let n = path.file_name().unwrap().to_string_lossy().to_string();
                assert!(added.contains(&n), "orphan output file {path:?}");
            }
        }
    }
}

fn files_per_partition(table: &DeltaTable) -> BTreeMap<Option<String>, usize> {
    let mut out = BTreeMap::new();
    for view in table.snapshot().unwrap().log_data().iter() {
        let p = view
            .remove_action(false)
            .partition_values
            .and_then(|pv| pv.get("p").cloned().flatten());
        *out.entry(p).or_default() += 1;
    }
    out
}

fn limits() -> Arc<ProcessLimits> {
    Arc::new(ProcessLimits::with_fetch(8, 16, 256 << 20, 256 << 20))
}

fn opts() -> CompactOptions {
    CompactOptions {
        target_file_size: Some(64 << 20),
        limits: limits(),
        ..Default::default()
    }
}

async fn run(table: &DeltaTable, o: CompactOptions) -> (CompactStats, DeltaTable) {
    let (stats, state) = tokio::time::timeout(Duration::from_secs(120), compact(table, o))
        .await
        .expect("compaction hung")
        .expect("compaction failed");
    let mut after = table.clone();
    if let Some(state) = state {
        after.state = Some(state);
    }
    (stats, after)
}

fn upsert_opts() -> UpsertOptions {
    UpsertOptions {
        primary_keys: vec!["pk".to_string()],
        partition_key: Some("p".to_string()),
        ..Default::default()
    }
}

// ---- tests -------------------------------------------------------------------------

/// Every partition with small files, including a NULL partition and values that need
/// path encoding, lands as one file in one OPTIMIZE commit with the same rows.
#[tokio::test]
async fn compacts_every_partition_in_one_optimize_commit() {
    let dir = tempfile::tempdir().unwrap();
    let parts = [Some("x"), Some("a b/c=d%e"), None, Some("ü")];
    let table = fragmented(dir.path(), &parts, 5, 50).await;
    let before = read_rows(&table).await;
    let version_before = table.version().unwrap();

    let (stats, after) = run(&table, opts()).await;

    assert_eq!(stats.files_considered, 20);
    assert_eq!(stats.partitions_compacted, 4);
    assert_eq!(stats.bins, 4);
    assert_eq!(stats.files_removed, 20);
    assert_eq!(stats.files_added, 4);
    assert_eq!(stats.rows_rewritten, 1000);
    assert_eq!(stats.commits, 1);
    assert_eq!(stats.version as u64, version_before + 1);
    assert_eq!(
        files_per_partition(&after)
            .values()
            .copied()
            .collect::<Vec<_>>(),
        vec![1; 4]
    );
    let fresh = reopen(dir.path()).await;
    assert_eq!(read_rows(&fresh).await, before);
    assert_eq!(files_per_partition(&fresh), files_per_partition(&after));

    let (_, optimizes) = assert_log_valid(dir.path());
    assert_eq!(optimizes.len(), 1);
    let info = optimizes[0]
        .iter()
        .find_map(|a| a.get("commitInfo"))
        .unwrap();
    assert_eq!(info["isBlindAppend"], false);
    assert_eq!(info["readVersion"], version_before);
    assert_eq!(info["operationParameters"]["targetSize"], "67108864");
    let metrics = &info["operationMetrics"];
    assert_eq!(metrics["numFilesRemoved"], 20);
    assert_eq!(metrics["numFilesAdded"], 4);
    assert_eq!(metrics["partitionsOptimized"], 4);
    let removed: Value = serde_json::from_str(metrics["filesRemoved"].as_str().unwrap()).unwrap();
    assert_eq!(removed["totalFiles"], 20);
    // ZSTD, as delta-rs's optimize writes.
    for a in &optimizes[0] {
        if let Some(add) = a.get("add") {
            assert!(add["path"].as_str().unwrap().ends_with(".zstd.parquet"));
        }
    }
    assert_no_orphans(dir.path());
}

#[tokio::test]
async fn unpartitioned_table_with_oversized_and_lone_files() {
    let dir = tempfile::tempdir().unwrap();
    let mut table = fragmented(dir.path(), &[], 4, 100).await;
    let s = schema(false);
    // One big file splits the run: the four small files before it form a bin, the two
    // after it form another.
    append(&mut table, rows(&s, "big", 0..4000, 9, 2000, None), None).await;
    for f in 0..2 {
        append(
            &mut table,
            rows(&s, &format!("t{f}-"), 0..10, 1, 40, None),
            None,
        )
        .await;
    }
    let before = read_rows(&table).await;
    let big = table
        .snapshot()
        .unwrap()
        .log_data()
        .iter()
        .map(|v| v.size() as usize)
        .max()
        .unwrap();
    let (stats, after) = run(
        &table,
        CompactOptions {
            target_file_size: Some(big - 1),
            ..opts()
        },
    )
    .await;
    assert_eq!(stats.bins, 2);
    assert_eq!(stats.files_removed, 6);
    assert_eq!(stats.files_skipped, 1);
    assert_eq!(after.snapshot().unwrap().log_data().num_files(), 3);
    assert_eq!(read_rows(&reopen(dir.path()).await).await, before);
    assert_log_valid(dir.path());
}

/// Planning reads only the log: with every data file deleted from disk, a dry run still
/// reports the full plan and commits nothing.
#[tokio::test]
async fn dry_run_plans_from_the_log_alone() {
    let dir = tempfile::tempdir().unwrap();
    let table = fragmented(dir.path(), &[Some("x"), Some("y")], 3, 20).await;
    for entry in walk(dir.path()) {
        if entry.extension().is_some_and(|e| e == "parquet") {
            std::fs::remove_file(entry).unwrap();
        }
    }
    let (stats, state) = compact(
        &table,
        CompactOptions {
            dry_run: true,
            ..opts()
        },
    )
    .await
    .unwrap();
    assert!(state.is_none());
    assert!(stats.dry_run);
    assert_eq!(stats.bins, 2);
    assert_eq!(stats.files_removed, 6);
    assert_eq!(stats.partitions_compacted, 2);
    assert_eq!(stats.files_added, 0);
    assert_eq!(reopen(dir.path()).await.version(), table.version());
}

fn walk(dir: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for entry in std::fs::read_dir(&d).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                stack.push(path);
            } else {
                out.push(path);
            }
        }
    }
    out
}

/// `min_partition_removable_files` leaves partitions that would gain little alone, and
/// `partitions` restricts the plan to the named values.
#[tokio::test]
async fn partition_selection() {
    let dir = tempfile::tempdir().unwrap();
    let mut table = fragmented(dir.path(), &[Some("many")], 6, 10).await;
    let s = schema(true);
    for f in 0..2 {
        append(
            &mut table,
            rows(&s, &format!("few{f}-"), 0..10, 1, 40, Some("few")),
            None,
        )
        .await;
    }
    let dry = |o: CompactOptions| {
        let table = table.clone();
        async move {
            compact(&table, CompactOptions { dry_run: true, ..o })
                .await
                .unwrap()
                .0
        }
    };
    // Every partition with a mergeable bin, as delta-rs.
    assert_eq!(dry(opts()).await.partitions_compacted, 2);
    // "few" would remove 2 files and write 1: below a threshold of 2.
    let s2 = dry(CompactOptions {
        min_partition_removable_files: 2,
        ..opts()
    })
    .await;
    assert_eq!(s2.partitions_compacted, 1);
    assert_eq!(s2.files_removed, 6);
    assert_eq!(s2.files_skipped, 2);
    let named = dry(CompactOptions {
        partitions: Some(vec!["few".into()]),
        ..opts()
    })
    .await;
    assert_eq!((named.files_considered, named.files_removed), (2, 2));
    let flat = tempfile::tempdir().unwrap();
    assert!(matches!(
        compact(
            &fragmented(flat.path(), &[], 2, 5).await,
            CompactOptions {
                partitions: Some(vec!["x".into()]),
                ..opts()
            }
        )
        .await,
        Err(Error::SchemaMismatch(_))
    ));
}

/// Multi-row-group inputs; the decoded caps split row groups and output files.
#[tokio::test]
async fn decoded_caps_split_row_groups_and_files() {
    let dir = tempfile::tempdir().unwrap();
    let mut table = create(dir.path(), true).await;
    let s = schema(true);
    let small_groups = WriterProperties::builder()
        .set_max_row_group_row_count(Some(100))
        .build();
    for f in 0..4 {
        append(
            &mut table,
            rows(&s, &format!("f{f}-"), 0..1000, f, 400, Some("x")),
            Some(small_groups.clone()),
        )
        .await;
    }
    let before = read_rows(&table).await;

    let (stats, after) = run(
        &table,
        CompactOptions {
            max_row_group_decoded_bytes: 64 * 1024,
            max_decoded_file_bytes: 1024 * 1024,
            decode_batch_bytes: 32 * 1024,
            ..opts()
        },
    )
    .await;
    assert_eq!(stats.bins, 1);
    assert!(stats.files_added >= 2, "{stats:?}");
    assert_eq!(read_rows(&reopen(dir.path()).await).await, before);
    let store = after.object_store();
    let mut row_groups = 0;
    for view in after.snapshot().unwrap().log_data().iter() {
        let path = Path::parse(view.path().as_ref()).unwrap();
        let bytes = store.get(&path).await.unwrap().bytes().await.unwrap();
        let meta = ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .metadata()
            .clone();
        // A row group or file closes on the batch that crosses its cap, so each may
        // overshoot by one input batch (one 100-row input row group here).
        for rg in meta.row_groups() {
            assert!(
                rg.total_byte_size() < 128 * 1024,
                "{}",
                rg.total_byte_size()
            );
        }
        row_groups += meta.num_row_groups();
        let decoded: i64 = meta.row_groups().iter().map(|r| r.total_byte_size()).sum();
        assert!(decoded < 1024 * 1024 + 64 * 1024, "{decoded}");
    }
    assert!(row_groups > stats.files_added, "{row_groups}");
    assert_log_valid(dir.path());
}

/// `max_bins_per_commit` commits as bins finish instead of once.
#[tokio::test]
async fn chunked_commits() {
    let dir = tempfile::tempdir().unwrap();
    let table = fragmented(dir.path(), &[Some("x"), Some("y"), Some("z")], 3, 10).await;
    let before = read_rows(&table).await;
    let (stats, _) = run(
        &table,
        CompactOptions {
            max_bins_per_commit: Some(1),
            max_parallel_bins: 1,
            ..opts()
        },
    )
    .await;
    assert_eq!((stats.commits, stats.bins), (3, 3));
    assert_eq!(read_rows(&reopen(dir.path()).await).await, before);
    let (_, optimizes) = assert_log_valid(dir.path());
    assert_eq!(optimizes.len(), 3);
}

/// A merge that rewrote a file of one planned bin commits between the compaction's plan
/// and its commit. That bin is dropped (its output deleted), the untouched partition
/// still lands, and the touched partition is planned again from the merge's result.
#[tokio::test]
async fn concurrent_merge_drops_only_the_touched_bin_and_replans_it() {
    for replan in [1usize, 0] {
        let dir = tempfile::tempdir().unwrap();
        let stale = fragmented(dir.path(), &[Some("x"), Some("y")], 3, 10).await;

        let mut handle = TableHandle::open(dir.path().to_str().unwrap().into(), HashMap::new())
            .await
            .unwrap();
        let s = schema(true);
        handle
            .upsert(
                vec![rows(&s, "k0-", 3..4, 777, 8, Some("x"))],
                s.clone(),
                upsert_opts(),
                MultipartConfig::default(),
            )
            .await
            .unwrap();
        let expected = read_rows(&reopen(dir.path()).await).await;
        let updated: Row = (Some("x".into()), "k0-000003".into(), Some(777), None);
        assert!(expected.contains(&updated));

        let (stats, _) = run(
            &stale,
            CompactOptions {
                max_replan_rounds: replan,
                ..opts()
            },
        )
        .await;
        assert_eq!(stats.commit_retries, 1, "{stats:?}");
        assert_eq!(stats.bins_dropped, 1, "{stats:?}");
        let fresh = reopen(dir.path()).await;
        assert_eq!(read_rows(&fresh).await, expected, "no row resurrected");
        let layout = files_per_partition(&fresh);
        assert_eq!(layout[&Some("y".to_string())], 1);
        if replan == 1 {
            assert_eq!((stats.commits, stats.replan_rounds, stats.bins), (2, 1, 2));
            assert_eq!(layout[&Some("x".to_string())], 1);
        } else {
            assert_eq!((stats.commits, stats.replan_rounds, stats.bins), (1, 0, 1));
            assert_eq!(layout[&Some("x".to_string())], 3);
        }
        assert_log_valid(dir.path());
        assert_no_orphans(dir.path());
    }
}

/// A concurrent schema change aborts the compaction as a retryable conflict and leaves
/// no output behind.
#[tokio::test]
async fn concurrent_schema_change_is_a_conflict() {
    let dir = tempfile::tempdir().unwrap();
    let stale = fragmented(dir.path(), &[Some("x")], 3, 10).await;
    let mut evolved = reopen(dir.path()).await;
    // Append once so the compaction's first attempt certainly loses the race, then add
    // a column.
    let s = schema(true);
    append(&mut evolved, rows(&s, "late", 0..5, 1, 8, Some("x")), None).await;
    reopen(dir.path())
        .await
        .add_columns()
        .with_fields(vec![StructField::new("extra", KernelType::STRING, true)])
        .await
        .unwrap();

    let err = compact(&stale, opts()).await.unwrap_err();
    assert!(matches!(err, Error::Conflict(_)), "{err:?}");
    assert_log_valid(dir.path());
    assert_no_orphans(dir.path());
}

/// Upserts running on other handles while compactions run: every upsert's rows survive,
/// nothing is removed twice, and no uncommitted output is left behind.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn compactions_racing_upserts_keep_every_row() {
    let dir = tempfile::tempdir().unwrap();
    let parts = [Some("a"), Some("b"), Some("c")];
    fragmented(dir.path(), &parts, 4, 20).await;
    let uri = dir.path().to_str().unwrap().to_string();

    let writer = {
        let uri = uri.clone();
        tokio::spawn(async move {
            let s = schema(true);
            let mut handle = TableHandle::open(uri, HashMap::new()).await.unwrap();
            for round in 0..12i64 {
                let p = ["a", "b", "c"][round as usize % 3];
                // Update a key from the first file of each partition and insert a new one.
                let mut b = vec![rows(&s, "k0-", 0..2, 1000 + round, 8, Some(p))];
                b.push(rows(&s, &format!("new{round}-"), 0..3, round, 8, Some(p)));
                handle
                    .upsert(b, s.clone(), upsert_opts(), MultipartConfig::default())
                    .await
                    .unwrap();
            }
        })
    };
    let compactor = {
        let uri = uri.clone();
        tokio::spawn(async move {
            let mut totals = CompactStats::default();
            for _ in 0..6 {
                let table = open_table(&uri, HashMap::new()).await.unwrap();
                match compact(
                    &table,
                    CompactOptions {
                        target_file_size: Some(64 << 20),
                        commit_max_retries: 50,
                        max_replan_rounds: 2,
                        limits: limits(),
                        ..Default::default()
                    },
                )
                .await
                {
                    Ok((s, _)) => {
                        totals.commits += s.commits;
                        totals.bins_dropped += s.bins_dropped;
                        totals.commit_retries += s.commit_retries;
                    }
                    Err(Error::Conflict(_)) => {}
                    Err(e) => panic!("compaction failed: {e:?}"),
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            totals
        })
    };
    writer.await.unwrap();
    let totals = compactor.await.unwrap();
    assert!(totals.commits > 0, "{totals:?}");

    // The same upserts applied to a table nobody compacts.
    let reference = tempfile::tempdir().unwrap();
    fragmented(reference.path(), &parts, 4, 20).await;
    let s = schema(true);
    let mut handle = TableHandle::open(reference.path().to_str().unwrap().into(), HashMap::new())
        .await
        .unwrap();
    for round in 0..12i64 {
        let p = ["a", "b", "c"][round as usize % 3];
        let mut b = vec![rows(&s, "k0-", 0..2, 1000 + round, 8, Some(p))];
        b.push(rows(&s, &format!("new{round}-"), 0..3, round, 8, Some(p)));
        handle
            .upsert(b, s.clone(), upsert_opts(), MultipartConfig::default())
            .await
            .unwrap();
    }
    assert_eq!(
        read_rows(&reopen(dir.path()).await).await,
        read_rows(&reopen(reference.path()).await).await
    );
    assert_log_valid(dir.path());
    assert_no_orphans(dir.path());
}

/// A bin whose input cannot be read fails the compaction, commits nothing, and deletes
/// every output already written, including other bins'.
#[tokio::test]
async fn a_failing_bin_commits_nothing_and_leaves_no_outputs() {
    let dir = tempfile::tempdir().unwrap();
    let table = fragmented(dir.path(), &[Some("ok"), Some("broken")], 3, 10).await;
    let version = table.version();
    let victim = table
        .snapshot()
        .unwrap()
        .log_data()
        .iter()
        .find(|v| v.path().contains("broken"))
        .unwrap()
        .path()
        .into_owned();
    let victim = walk(dir.path())
        .into_iter()
        .find(|p| p.to_string_lossy().ends_with(&name(&victim)))
        .unwrap();
    std::fs::write(&victim, b"not parquet").unwrap();

    let err = compact(
        &table,
        CompactOptions {
            max_parallel_bins: 2,
            ..opts()
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(err, Error::Generic(_)), "{err:?}");
    assert_eq!(reopen(dir.path()).await.version(), version);
    assert_no_orphans(dir.path());
}

/// Budgets far smaller than one batch, shared by several compactions and an upsert in
/// one process, still finish: every holder of a fetch or decode permit can complete
/// without waiting on another permit.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn tiny_shared_budgets_never_deadlock() {
    let tiny = Arc::new(ProcessLimits::with_fetch(1, 1, 16 * 1024, 16 * 1024));
    let dirs: Vec<_> = (0..3).map(|_| tempfile::tempdir().unwrap()).collect();
    for d in &dirs {
        fragmented(d.path(), &[Some("a"), Some("b"), Some("c")], 4, 200).await;
    }
    let mut tasks = Vec::new();
    for d in &dirs {
        let uri = d.path().to_str().unwrap().to_string();
        let limits = tiny.clone();
        tasks.push(tokio::spawn(async move {
            let table = open_table(&uri, HashMap::new()).await.unwrap();
            compact(
                &table,
                CompactOptions {
                    target_file_size: Some(64 << 20),
                    max_parallel_bins: 3,
                    max_buffered_bytes: 8 * 1024,
                    max_fetch_bytes: 8 * 1024,
                    decode_batch_bytes: 4 * 1024,
                    limits,
                    ..Default::default()
                },
            )
            .await
            .unwrap()
            .0
        }));
    }
    let upsert_dir = dirs[0].path().to_str().unwrap().to_string();
    let limits = tiny.clone();
    let upsert = tokio::spawn(async move {
        let s = schema(true);
        let mut handle = TableHandle::open(upsert_dir, HashMap::new()).await.unwrap();
        handle
            .upsert(
                vec![rows(&s, "z", 0..50, 1, 8, Some("a"))],
                s.clone(),
                UpsertOptions {
                    max_buffered_bytes: 8 * 1024,
                    max_fetch_bytes: 8 * 1024,
                    limits,
                    ..upsert_opts()
                },
                MultipartConfig::default(),
            )
            .await
            .unwrap();
    });
    let all = async {
        for t in tasks {
            let stats = t.await.unwrap();
            // The upsert only inserts, so it removes nothing a compaction planned.
            assert_eq!(stats.files_removed, 12, "{stats:?}");
        }
        upsert.await.unwrap();
    };
    tokio::time::timeout(Duration::from_secs(120), all)
        .await
        .expect("budgets deadlocked");
    for d in &dirs {
        assert_log_valid(d.path());
        assert_no_orphans(d.path());
    }
}
