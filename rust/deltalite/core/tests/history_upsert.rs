//! `history_upsert` against real tables: the SCD2 rules, what it rewrites, and what it
//! refuses. The Python suite (`python/tests/test_history.py`) runs the same rules against
//! a reference model over random inputs.

use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering as AtomicOrdering};
use std::sync::{Arc, LazyLock, Mutex};

use arrow_array::types::Int32Type;
use arrow_array::{
    Array, DictionaryArray, Int32Array, Int64Array, RecordBatch, StringArray,
    TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema, SchemaRef, TimeUnit};
use bytes::Bytes;
use chrono::DateTime;
use deltalake::kernel::{DataType as KernelType, PrimitiveType, StructField};
use deltalake::logstore::{
    default_logstore, logstore_factories, object_store_factories, LogStore, LogStoreFactory,
    ObjectStoreFactory, StorageConfig,
};
use deltalake::operations::create::CreateBuilder;
use deltalake::DeltaResult;
use deltalake::Path;
use deltalite_core::errors::Error;
use deltalite_core::handle::TableHandle;
use deltalite_core::history::{
    format_months, history_upsert, HistoryUpsertOptions, HistoryUpsertStats,
};
use deltalite_core::limits::ProcessLimits;
use deltalite_core::table::MultipartConfig;
use futures::stream::BoxStream;
use object_store::local::LocalFileSystem;
use object_store::{
    CopyOptions, GetOptions, GetResult, ListResult, MultipartUpload, ObjectMeta, ObjectStore,
    ObjectStoreExt, PutMode, PutMultipartOptions, PutOptions, PutPayload, PutResult, RenameOptions,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

/// One source row: (id, order value, valid_from, payload, tie-break).
type Src<'a> = (Option<&'a str>, i64, &'a str, &'a str, i64);

/// One live table row: (partition, id, order value, valid_from, valid_to, payload).
type Live = (String, Option<String>, i64, i64, Option<i64>, String);

fn ts(s: &str) -> i64 {
    DateTime::parse_from_rfc3339(s).unwrap().timestamp_micros()
}

fn utc() -> DataType {
    DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into()))
}

fn source_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("id", DataType::Utf8, true),
        Field::new("v", DataType::Int64, true),
        Field::new("valid_from", utc(), true),
        Field::new("payload", DataType::Utf8, true),
        Field::new("seq", DataType::Int64, true),
    ]))
}

fn source(rows: &[Src]) -> RecordBatch {
    RecordBatch::try_new(
        source_schema(),
        vec![
            Arc::new(StringArray::from(
                rows.iter().map(|r| r.0).collect::<Vec<_>>(),
            )),
            Arc::new(Int64Array::from(
                rows.iter().map(|r| r.1).collect::<Vec<_>>(),
            )),
            Arc::new(
                TimestampMicrosecondArray::from(rows.iter().map(|r| ts(r.2)).collect::<Vec<_>>())
                    .with_timezone("UTC"),
            ),
            Arc::new(StringArray::from(
                rows.iter().map(|r| r.3).collect::<Vec<_>>(),
            )),
            Arc::new(Int64Array::from(
                rows.iter().map(|r| r.4).collect::<Vec<_>>(),
            )),
        ],
    )
    .unwrap()
}

async fn create(dir: &std::path::Path, partition_by: &[&str]) -> TableHandle {
    CreateBuilder::new()
        .with_location(dir.to_str().unwrap())
        .with_columns(vec![
            StructField::new("id", KernelType::STRING, true),
            StructField::new("v", KernelType::LONG, true),
            StructField::new(
                "valid_from",
                KernelType::Primitive(PrimitiveType::Timestamp),
                true,
            ),
            StructField::new(
                "valid_to",
                KernelType::Primitive(PrimitiveType::Timestamp),
                true,
            ),
            StructField::new("payload", KernelType::STRING, true),
            StructField::new("p", KernelType::STRING, false),
            StructField::new("q", KernelType::STRING, true),
        ])
        .with_partition_columns(partition_by.iter().map(|c| c.to_string()))
        .await
        .unwrap();
    TableHandle::open(dir.to_str().unwrap().into(), HashMap::new())
        .await
        .unwrap()
}

fn opts() -> HistoryUpsertOptions {
    HistoryUpsertOptions {
        key_columns: vec!["id".into()],
        order_column: "v".into(),
        valid_from_column: "valid_from".into(),
        valid_to_column: "valid_to".into(),
        partition_column: "p".into(),
        current_partition: "current".into(),
        tie_break_column: "seq".into(),
        limits: Arc::new(ProcessLimits::with_fetch(8, 16, 256 << 20, 256 << 20)),
        ..Default::default()
    }
}

async fn apply_with(
    handle: &mut TableHandle,
    rows: &[Src<'_>],
    opts: HistoryUpsertOptions,
) -> deltalite_core::Result<HistoryUpsertStats> {
    handle
        .history_upsert(
            vec![source(rows)],
            source_schema(),
            opts,
            MultipartConfig::default(),
        )
        .await
}

async fn apply(handle: &mut TableHandle, rows: &[Src<'_>]) -> HistoryUpsertStats {
    apply_with(handle, rows, opts()).await.unwrap()
}

/// Every live row, sorted.
async fn read(handle: &TableHandle) -> Vec<Live> {
    let mut out = Vec::new();
    for f in handle.files().unwrap() {
        let bytes = handle
            .table()
            .object_store()
            .get(&Path::parse(&f.path).unwrap())
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap();
        let partition = f.partition_values["p"].clone().unwrap();
        for batch in ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .build()
            .unwrap()
        {
            let batch = batch.unwrap();
            let col = |name: &str| batch.column_by_name(name).unwrap().clone();
            let (id, v, from, to, payload) = (
                col("id"),
                col("v"),
                col("valid_from"),
                col("valid_to"),
                col("payload"),
            );
            let id = id.as_any().downcast_ref::<StringArray>().unwrap();
            let v = v.as_any().downcast_ref::<Int64Array>().unwrap();
            let from = from
                .as_any()
                .downcast_ref::<TimestampMicrosecondArray>()
                .unwrap();
            let to = to
                .as_any()
                .downcast_ref::<TimestampMicrosecondArray>()
                .unwrap();
            let payload = payload.as_any().downcast_ref::<StringArray>().unwrap();
            for i in 0..batch.num_rows() {
                out.push((
                    partition.clone(),
                    id.is_valid(i).then(|| id.value(i).to_string()),
                    v.value(i),
                    from.value(i),
                    to.is_valid(i).then(|| to.value(i)),
                    payload.value(i).to_string(),
                ));
            }
        }
    }
    out.sort();
    out
}

fn open(id: Option<&str>, v: i64, from: &str, payload: &str) -> Live {
    (
        "current".into(),
        id.map(str::to_string),
        v,
        ts(from),
        None,
        payload.into(),
    )
}

fn closed(month: &str, id: Option<&str>, v: i64, from: &str, to: &str, payload: &str) -> Live {
    (
        month.into(),
        id.map(str::to_string),
        v,
        ts(from),
        Some(ts(to)),
        payload.into(),
    )
}

fn sorted(mut rows: Vec<Live>) -> Vec<Live> {
    rows.sort();
    rows
}

#[tokio::test]
async fn applies_each_rule_against_the_open_row() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    let first = apply(
        &mut h,
        &[
            (Some("changed"), 10, "2026-01-10T00:00:00Z", "c1", 1),
            (Some("reread"), 10, "2026-01-10T00:00:00Z", "r1", 2),
            (Some("backwards"), 10, "2026-01-10T00:00:00Z", "b1", 3),
            (Some("mixed"), 10, "2026-01-10T00:00:00Z", "m1", 4),
        ],
    )
    .await;
    assert_eq!(
        (
            first.versions_opened,
            first.versions_closed,
            first.files_removed
        ),
        (4, 0, 0),
        "{first:?}"
    );

    let second = apply(
        &mut h,
        &[
            (Some("changed"), 20, "2026-02-03T00:00:00Z", "c2", 10),
            (Some("reread"), 10, "2026-01-10T00:00:00Z", "r1-again", 11),
            (Some("backwards"), 5, "2026-01-05T00:00:00Z", "b0", 12),
            (Some("mixed"), 7, "2026-01-07T00:00:00Z", "m0", 13),
            (Some("mixed"), 30, "2026-03-01T00:00:00Z", "m3", 14),
            (Some("new"), 1, "2026-03-02T00:00:00Z", "n1", 15),
        ],
    )
    .await;
    assert_eq!(
        (
            second.rows_in,
            second.rows_reread,
            second.rows_backwards,
            second.versions_opened,
            second.versions_closed,
            second.chain_rows_closed,
            second.rows_copied,
        ),
        (6, 1, 2, 3, 2, 0, 2),
        "{second:?}"
    );
    assert_eq!(
        read(&h).await,
        sorted(vec![
            closed(
                "2026-02",
                Some("changed"),
                10,
                "2026-01-10T00:00:00Z",
                "2026-02-03T00:00:00Z",
                "c1"
            ),
            open(Some("changed"), 20, "2026-02-03T00:00:00Z", "c2"),
            open(Some("reread"), 10, "2026-01-10T00:00:00Z", "r1"),
            open(Some("backwards"), 10, "2026-01-10T00:00:00Z", "b1"),
            closed(
                "2026-03",
                Some("mixed"),
                10,
                "2026-01-10T00:00:00Z",
                "2026-03-01T00:00:00Z",
                "m1"
            ),
            open(Some("mixed"), 30, "2026-03-01T00:00:00Z", "m3"),
            open(Some("new"), 1, "2026-03-02T00:00:00Z", "n1"),
        ])
    );
}

#[tokio::test]
async fn chains_versions_in_one_call_and_a_tie_takes_the_highest_tie_break() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    let stats = apply(
        &mut h,
        &[
            (Some("a"), 3, "2026-03-01T00:00:00Z", "third", 1),
            (Some("a"), 2, "2026-02-01T00:00:00Z", "second-wins", 9),
            (Some("a"), 1, "2026-01-01T00:00:00Z", "first", 1),
            (Some("a"), 2, "2026-02-01T00:00:00Z", "second-loses", 5),
        ],
    )
    .await;
    assert_eq!(
        (
            stats.rows_deduped,
            stats.versions_opened,
            stats.chain_rows_closed
        ),
        (1, 1, 2),
        "{stats:?}"
    );
    assert_eq!(
        read(&h).await,
        sorted(vec![
            closed(
                "2026-02",
                Some("a"),
                1,
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "first"
            ),
            closed(
                "2026-03",
                Some("a"),
                2,
                "2026-02-01T00:00:00Z",
                "2026-03-01T00:00:00Z",
                "second-wins"
            ),
            open(Some("a"), 3, "2026-03-01T00:00:00Z", "third"),
        ])
    );
}

#[tokio::test]
async fn a_null_key_matches_its_open_row() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    apply(&mut h, &[(None, 1, "2026-01-01T00:00:00Z", "n1", 1)]).await;
    let stats = apply(&mut h, &[(None, 2, "2026-02-01T00:00:00Z", "n2", 2)]).await;
    assert_eq!(stats.versions_closed, 1, "{stats:?}");
    assert_eq!(
        read(&h).await,
        sorted(vec![
            closed(
                "2026-02",
                None,
                1,
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "n1"
            ),
            open(None, 2, "2026-02-01T00:00:00Z", "n2"),
        ])
    );
}

#[tokio::test]
async fn a_rerun_of_the_same_input_makes_no_commit() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    let input = [
        (Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1),
        (Some("a"), 2, "2026-02-01T00:00:00Z", "a2", 2),
        (Some("b"), 1, "2026-01-01T00:00:00Z", "b1", 3),
    ];
    let first = apply(&mut h, &input).await;
    let rows = read(&h).await;
    let files = h.files().unwrap();

    let rerun = apply(&mut h, &input).await;
    assert!(first.committed && !rerun.committed, "{rerun:?}");
    assert_eq!(rerun.version, first.version);
    assert_eq!(
        (
            rerun.rows_reread,
            rerun.rows_backwards,
            rerun.files_added,
            rerun.files_removed,
            rerun.files_carried_over
        ),
        (2, 1, 0, 0, 1),
        "{rerun:?}"
    );
    assert_eq!(h.version(), first.version);
    assert_eq!(h.files().unwrap(), files);
    assert_eq!(read(&h).await, rows);
}

#[tokio::test]
async fn closed_rows_land_in_the_utc_month_of_valid_to() {
    let vectors: Vec<serde_json::Value> =
        serde_json::from_str(include_str!("fixtures/month_vectors.json")).unwrap();
    let instants: Vec<i64> = vectors
        .iter()
        .map(|v| ts(v["valid_to"].as_str().unwrap()))
        .collect();
    let months =
        format_months(&TimestampMicrosecondArray::from(instants.clone()).with_timezone("UTC"))
            .unwrap();
    for (v, m) in vectors.iter().zip(months.iter()) {
        assert_eq!(m, v["month"].as_str(), "{v}");
    }

    // Each key opens before 1969 and closes at one vector instant.
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    let ids: Vec<String> = (0..vectors.len()).map(|i| format!("k{i}")).collect();
    let opens: Vec<Src> = ids
        .iter()
        .map(|id| (Some(id.as_str()), 1, "1960-01-01T00:00:00Z", "old", 1))
        .collect();
    apply(&mut h, &opens).await;
    let closes: Vec<Src> = ids
        .iter()
        .zip(&vectors)
        .map(|(id, v)| {
            (
                Some(id.as_str()),
                2,
                v["valid_to"].as_str().unwrap(),
                "new",
                2,
            )
        })
        .collect();
    apply(&mut h, &closes).await;
    let closed_months: HashMap<String, String> = read(&h)
        .await
        .into_iter()
        .filter(|row| row.4.is_some())
        .map(|row| (row.1.unwrap(), row.0))
        .collect();
    for (id, v) in ids.iter().zip(&vectors) {
        assert_eq!(closed_months[id], v["month"].as_str().unwrap(), "{v}");
    }
}

#[tokio::test]
async fn earlier_closed_versions_in_the_same_month_stay() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    apply(&mut h, &[(Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1)]).await;
    apply(&mut h, &[(Some("a"), 2, "2026-02-01T00:00:00Z", "a2", 2)]).await;
    apply(&mut h, &[(Some("a"), 3, "2026-02-15T00:00:00Z", "a3", 3)]).await;
    assert_eq!(
        read(&h).await,
        sorted(vec![
            closed(
                "2026-02",
                Some("a"),
                1,
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "a1"
            ),
            closed(
                "2026-02",
                Some("a"),
                2,
                "2026-02-01T00:00:00Z",
                "2026-02-15T00:00:00Z",
                "a2"
            ),
            open(Some("a"), 3, "2026-02-15T00:00:00Z", "a3"),
        ])
    );
}

#[tokio::test]
async fn a_file_holding_only_reread_keys_is_not_rewritten() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    apply(&mut h, &[(Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1)]).await;
    apply(&mut h, &[(Some("b"), 1, "2026-01-01T00:00:00Z", "b1", 2)]).await;
    let stats = apply(
        &mut h,
        &[
            (Some("a"), 1, "2026-01-01T00:00:00Z", "a1-again", 3),
            (Some("b"), 2, "2026-02-01T00:00:00Z", "b2", 4),
        ],
    )
    .await;
    assert_eq!(
        (
            stats.files_probed,
            stats.files_removed,
            stats.files_carried_over,
            stats.rows_reread
        ),
        (2, 1, 1, 1),
        "{stats:?}"
    );
}

#[tokio::test]
async fn refuses_input_it_cannot_apply() {
    let dir = tempfile::tempdir().unwrap();
    let mut history = create(dir.path(), &["p"]).await;
    apply(
        &mut history,
        &[(Some("a"), 1, "2026-01-01T00:00:00Z", "a", 1)],
    )
    .await;
    // A null order value, and a null hidden in the dictionary of a dictionary-encoded
    // `valid_from`, which a plain null count does not see.
    let valid = source(&[(Some("a"), 2, "2026-02-01T00:00:00Z", "a", 2)]);
    let null_dictionary_value: Arc<dyn Array> = Arc::new(
        DictionaryArray::<Int32Type>::try_new(
            Int32Array::from(vec![0]),
            Arc::new(TimestampMicrosecondArray::from(vec![None::<i64>]).with_timezone("UTC")),
        )
        .unwrap(),
    );
    let null_order: Arc<dyn Array> = Arc::new(Int64Array::from(vec![None::<i64>]));
    for (case, column, value) in [
        ("null order", 1, null_order),
        ("null dictionary valid_from", 2, null_dictionary_value),
    ] {
        let mut fields: Vec<Field> = source_schema()
            .fields()
            .iter()
            .map(|f| f.as_ref().clone())
            .collect();
        fields[column] = Field::new(fields[column].name(), value.data_type().clone(), true);
        let schema: SchemaRef = Arc::new(Schema::new(fields));
        let mut cols = valid.columns().to_vec();
        cols[column] = value;
        let batch = RecordBatch::try_new(schema.clone(), cols).unwrap();
        let err = history
            .history_upsert(vec![batch], schema, opts(), MultipartConfig::default())
            .await
            .unwrap_err();
        assert!(
            matches!(err, Error::Generic(ref m) if m.contains("null")),
            "{case}: {err}"
        );
    }

    for (case, partition_by) in [("unpartitioned", vec![]), ("other column", vec!["q"])] {
        let dir = tempfile::tempdir().unwrap();
        let mut h = create(dir.path(), &partition_by).await;
        let err = apply_with(
            &mut h,
            &[(Some("a"), 1, "2026-01-01T00:00:00Z", "a", 1)],
            opts(),
        )
        .await
        .unwrap_err();
        assert!(matches!(err, Error::Unsupported(_)), "{case}: {err}");
    }

    let month_named = HistoryUpsertOptions {
        current_partition: "2026-01".into(),
        ..opts()
    };
    let err = apply_with(
        &mut history,
        &[(Some("a"), 3, "2026-03-01T00:00:00Z", "a", 3)],
        month_named,
    )
    .await
    .unwrap_err();
    assert!(
        matches!(err, Error::Generic(ref m) if m.contains("month")),
        "{err}"
    );
}

#[tokio::test]
async fn a_concurrent_commit_on_the_same_file_is_retried_against_the_new_state() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    apply(
        &mut h,
        &[
            (Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1),
            (Some("b"), 1, "2026-01-01T00:00:00Z", "b1", 2),
        ],
    )
    .await;

    // A stale snapshot plans to remove the file another commit already removed.
    let stale = h.table().clone();
    apply(&mut h, &[(Some("a"), 2, "2026-02-01T00:00:00Z", "a2", 3)]).await;
    let err = history_upsert(
        &stale,
        vec![source(&[(Some("b"), 2, "2026-02-01T00:00:00Z", "b2", 4)])],
        source_schema(),
        opts(),
    )
    .await
    .unwrap_err();
    assert!(matches!(err, Error::Conflict(_)), "{err}");

    // A concurrent commit that only adds files must not let a stale plan open a key twice.
    let stale = h.table().clone();
    apply(&mut h, &[(Some("c"), 1, "2026-02-01T00:00:00Z", "c1", 5)]).await;
    let err = history_upsert(
        &stale,
        vec![source(&[(Some("c"), 2, "2026-02-02T00:00:00Z", "c2", 6)])],
        source_schema(),
        opts(),
    )
    .await
    .unwrap_err();
    assert!(matches!(err, Error::Conflict(_)), "{err}");

    h.refresh().await.unwrap();
    assert_eq!(
        read(&h).await,
        sorted(vec![
            closed(
                "2026-02",
                Some("a"),
                1,
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "a1"
            ),
            open(Some("a"), 2, "2026-02-01T00:00:00Z", "a2"),
            open(Some("b"), 1, "2026-01-01T00:00:00Z", "b1"),
            open(Some("c"), 1, "2026-02-01T00:00:00Z", "c1"),
        ])
    );
}

#[tokio::test]
async fn a_handle_plans_again_when_another_commit_lands_before_its_own() {
    register_race_scheme();
    let dir = tempfile::tempdir().unwrap();
    let mut plain = create(dir.path(), &["p"]).await;
    apply(
        &mut plain,
        &[
            (Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1),
            (Some("b"), 1, "2026-01-01T00:00:00Z", "b1", 2),
        ],
    )
    .await;

    // The competing commit lands after the racing call planned, just before its commit
    // file is written, so the racing commit finds its version taken.
    let path = dir.path().to_str().unwrap().to_string();
    let raced = Arc::new(AtomicBool::new(false));
    let (other_path, other_raced) = (path.clone(), raced.clone());
    arm_race(
        dir.path(),
        Box::new(move || {
            Box::pin(async move {
                let mut other = TableHandle::open(other_path, HashMap::new()).await.unwrap();
                apply(
                    &mut other,
                    &[(Some("b"), 2, "2026-02-01T00:00:00Z", "b2", 3)],
                )
                .await;
                other_raced.store(true, AtomicOrdering::SeqCst);
            })
        }),
    );
    let mut racing = TableHandle::open(format!("dlrace://{path}"), HashMap::new())
        .await
        .unwrap();
    let stats = apply(
        &mut racing,
        &[(Some("a"), 2, "2026-03-01T00:00:00Z", "a2", 4)],
    )
    .await;

    assert!(raced.load(AtomicOrdering::SeqCst));
    assert_eq!((stats.version, stats.versions_closed), (3, 1), "{stats:?}");
    plain.refresh().await.unwrap();
    assert_eq!(
        read(&plain).await,
        sorted(vec![
            closed(
                "2026-03",
                Some("a"),
                1,
                "2026-01-01T00:00:00Z",
                "2026-03-01T00:00:00Z",
                "a1"
            ),
            open(Some("a"), 2, "2026-03-01T00:00:00Z", "a2"),
            closed(
                "2026-02",
                Some("b"),
                1,
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "b1"
            ),
            open(Some("b"), 2, "2026-02-01T00:00:00Z", "b2"),
        ])
    );
}

#[tokio::test]
async fn a_call_that_keeps_no_row_makes_no_relax_commit() {
    let dir = tempfile::tempdir().unwrap();
    CreateBuilder::new()
        .with_location(dir.path().to_str().unwrap())
        .with_columns(vec![
            StructField::new("id", KernelType::STRING, true),
            StructField::new("v", KernelType::LONG, true),
            StructField::new(
                "valid_from",
                KernelType::Primitive(PrimitiveType::Timestamp),
                true,
            ),
            StructField::new(
                "valid_to",
                KernelType::Primitive(PrimitiveType::Timestamp),
                true,
            ),
            StructField::new("payload", KernelType::STRING, false),
            StructField::new("p", KernelType::STRING, false),
        ])
        .with_partition_columns(vec!["p".to_string()])
        .await
        .unwrap();
    let mut h = TableHandle::open(dir.path().to_str().unwrap().into(), HashMap::new())
        .await
        .unwrap();
    apply(&mut h, &[(Some("a"), 1, "2026-01-01T00:00:00Z", "a1", 1)]).await;
    let with_null_payload = |v: i64, at: &str| {
        let batch = source(&[(Some("a"), v, at, "", 2)]);
        let mut cols = batch.columns().to_vec();
        cols[3] = Arc::new(StringArray::from(vec![None::<&str>]));
        RecordBatch::try_new(source_schema(), cols).unwrap()
    };
    let version = h.version();

    // A re-read with a null in the non-nullable column: nothing is kept, nothing commits.
    let reread = h
        .history_upsert(
            vec![with_null_payload(1, "2026-01-01T00:00:00Z")],
            source_schema(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        (reread.committed, reread.columns_relaxed),
        (false, 0),
        "{reread:?}"
    );
    assert_eq!(h.version(), version);
    assert!(h
        .schema_json()
        .unwrap()
        .contains(r#""name":"payload","type":"string","nullable":false"#));

    // A kept row with the same null relaxes the column and lands.
    let kept = h
        .history_upsert(
            vec![with_null_payload(2, "2026-02-01T00:00:00Z")],
            source_schema(),
            opts(),
            MultipartConfig::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        (kept.committed, kept.columns_relaxed),
        (true, 1),
        "{kept:?}"
    );
    assert_eq!(kept.version, version + 2);
}

#[tokio::test]
async fn closes_many_rows_under_tiny_budgets_and_returns_every_permit() {
    let dir = tempfile::tempdir().unwrap();
    let mut h = create(dir.path(), &["p"]).await;
    let ids: Vec<String> = (0..400).map(|i| format!("k{i:04}")).collect();
    for chunk in ids.chunks(100) {
        let rows: Vec<Src> = chunk
            .iter()
            .map(|id| (Some(id.as_str()), 1, "2026-01-01T00:00:00Z", "old", 1))
            .collect();
        apply(&mut h, &rows).await;
    }

    let limits = Arc::new(ProcessLimits::with_fetch(1, 1, 1024, 1024));
    let tiny = HistoryUpsertOptions {
        max_parallel_files: 4,
        probe_concurrency: 4,
        max_buffered_bytes: 1024,
        max_fetch_bytes: 1024,
        read_batch_size: 16,
        target_file_size: Some(4 * 1024),
        limits: limits.clone(),
        ..opts()
    };
    // The closes land in 50 months, more than the closed-row writer keeps open at once.
    let instants: Vec<String> = (0..ids.len())
        .map(|i| format!("{}-{:02}-15T00:00:00Z", 2026 + i % 50 / 12, i % 50 % 12 + 1))
        .collect();
    let rows: Vec<Src> = ids
        .iter()
        .zip(&instants)
        .map(|(id, at)| (Some(id.as_str()), 2, at.as_str(), "new", 2))
        .collect();
    let stats = apply_with(&mut h, &rows, tiny).await.unwrap();
    assert_eq!(
        (
            stats.files_removed,
            stats.versions_closed,
            stats.versions_opened
        ),
        (4, 400, 400),
        "{stats:?}"
    );
    let snapshot = limits.snapshot();
    for budget in [
        snapshot.partitions,
        snapshot.files,
        snapshot.buffer_kb,
        snapshot.fetch_kb,
    ] {
        assert_eq!(budget.available, budget.total, "{snapshot:?}");
    }
    let live = read(&h).await;
    assert_eq!(live.len(), 800);
    let mut per_month: HashMap<String, usize> = HashMap::new();
    for row in live.iter().filter(|r| r.0 != "current") {
        *per_month.entry(row.0.clone()).or_default() += 1;
    }
    assert_eq!(per_month.len(), 50);
    assert!(per_month.values().all(|n| *n == 8), "{per_month:?}");
}

#[tokio::test]
async fn key_bucket_ids_are_fixed_and_follow_the_table_key_types() {
    let dir = tempfile::tempdir().unwrap();
    let h = create(dir.path(), &["p"]).await;
    let keys = ["id".to_string(), "v".to_string()];
    let batch = |v: Arc<dyn Array>| {
        let ids = StringArray::from(vec![
            Some("a"),
            Some("b"),
            None,
            Some("a"),
            Some("customer-42"),
        ]);
        RecordBatch::try_new(
            Arc::new(Schema::new(vec![
                Field::new("id", DataType::Utf8, true),
                Field::new("v", v.data_type().clone(), true),
            ])),
            vec![Arc::new(ids), v],
        )
        .unwrap()
    };
    let typed = batch(Arc::new(Int64Array::from(vec![
        Some(1),
        Some(1),
        Some(1),
        None,
        Some(7),
    ])));
    let buckets = h
        .key_buckets(std::slice::from_ref(&typed), &keys, 16)
        .unwrap();
    assert_eq!(buckets.values().to_vec(), vec![4, 12, 0, 6, 6]);

    // The same key gets the same bucket in a later call with other rows around it.
    let again = h
        .key_buckets(&[typed.slice(3, 2), typed.slice(0, 3)], &keys, 16)
        .unwrap();
    assert_eq!(
        again.values().to_vec(),
        [&buckets.values()[3..], &buckets.values()[..3]].concat()
    );

    // Strings that cast to the same table key share its bucket, as they share the key.
    let strings = batch(Arc::new(StringArray::from(vec![
        Some("01"),
        Some("1"),
        Some("001"),
        None,
        Some("07"),
    ])));
    assert_eq!(
        h.key_buckets(&[strings], &keys, 16)
            .unwrap()
            .values()
            .to_vec(),
        buckets.values().to_vec()
    );
}

// ---- a store that lands a competing commit just before a commit file is written ------

type Race = Box<dyn FnOnce() -> Pin<Box<dyn Future<Output = ()> + Send>> + Send>;

/// Armed races by table path prefix; each fires once, on the first commit file written
/// under its prefix.
static RACES: LazyLock<Mutex<Vec<(String, Race)>>> = LazyLock::new(Default::default);

fn arm_race(dir: &std::path::Path, race: Race) {
    let prefix = Path::from(dir.to_string_lossy().as_ref()).to_string();
    RACES.lock().unwrap().push((prefix, race));
}

fn take_race(location: &Path) -> Option<Race> {
    let mut races = RACES.lock().unwrap();
    let i = races
        .iter()
        .position(|(prefix, _)| location.as_ref().starts_with(prefix.as_str()))?;
    Some(races.swap_remove(i).1)
}

#[derive(Debug)]
struct RaceStore {
    inner: Arc<dyn ObjectStore>,
}

impl std::fmt::Display for RaceStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "RaceStore({})", self.inner)
    }
}

#[async_trait::async_trait]
impl ObjectStore for RaceStore {
    async fn put_opts(
        &self,
        location: &Path,
        payload: PutPayload,
        opts: PutOptions,
    ) -> object_store::Result<PutResult> {
        let is_commit = matches!(opts.mode, PutMode::Create)
            && location.as_ref().contains("_delta_log/")
            && location.as_ref().ends_with(".json");
        if is_commit {
            if let Some(race) = take_race(location) {
                race().await;
            }
        }
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
        self.inner.get_ranges(location, ranges).await
    }

    fn delete_stream(
        &self,
        locations: BoxStream<'static, object_store::Result<Path>>,
    ) -> BoxStream<'static, object_store::Result<Path>> {
        self.inner.delete_stream(locations)
    }

    // Sorted: cloud stores list lexicographically and delta-kernel relies on it.
    fn list(&self, prefix: Option<&Path>) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        sorted_listing(self.inner.list(prefix))
    }

    fn list_with_offset(
        &self,
        prefix: Option<&Path>,
        offset: &Path,
    ) -> BoxStream<'static, object_store::Result<ObjectMeta>> {
        sorted_listing(self.inner.list_with_offset(prefix, offset))
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

fn sorted_listing(
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
struct RaceFactory;

impl ObjectStoreFactory for RaceFactory {
    fn parse_url_opts(
        &self,
        url: &url::Url,
        _config: &StorageConfig,
    ) -> DeltaResult<(Arc<dyn ObjectStore>, Path)> {
        let store = RaceStore {
            inner: Arc::new(LocalFileSystem::new()),
        };
        Ok((Arc::new(store), Path::from_url_path(url.path())?))
    }
}

impl LogStoreFactory for RaceFactory {
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

fn register_race_scheme() {
    let scheme = url::Url::parse("dlrace://").expect("static url");
    object_store_factories().insert(scheme.clone(), Arc::new(RaceFactory));
    logstore_factories().insert(scheme, Arc::new(RaceFactory));
}
