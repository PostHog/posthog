//! Output layout of `upsert`: which rows share an output file, and therefore what the
//! next upsert has to copy again. Both layouts must hold the same rows.

use std::collections::HashMap;
use std::sync::Arc;

use arrow_array::{Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use bytes::Bytes;
use deltalake::kernel::{DataType as KernelType, StructField};
use deltalake::operations::create::CreateBuilder;
use deltalake::writer::{DeltaWriter, RecordBatchWriter};
use deltalake::Path;
use deltalite_core::handle::TableHandle;
use deltalite_core::limits::ProcessLimits;
use deltalite_core::table::MultipartConfig;
use deltalite_core::upsert::{UpsertOptions, UpsertStats};
use object_store::ObjectStoreExt;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

const TABLE_ROWS: usize = 1000;

fn schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("pk", DataType::Utf8, false),
        Field::new("v", DataType::Int64, true),
        Field::new("payload", DataType::Utf8, true),
        Field::new("p", DataType::Utf8, true),
    ]))
}

fn rows(keys: &[String], v: i64) -> RecordBatch {
    let n = keys.len();
    let payload: Vec<String> = keys.iter().map(|k| format!("{k}-").repeat(20)).collect();
    RecordBatch::try_new(
        schema(),
        vec![
            Arc::new(StringArray::from(keys.to_vec())),
            Arc::new(Int64Array::from(vec![v; n])),
            Arc::new(StringArray::from(payload)),
            Arc::new(StringArray::from(vec!["a"; n])),
        ],
    )
    .unwrap()
}

fn keys(prefix: &str, ids: std::ops::Range<usize>) -> Vec<String> {
    ids.map(|i| format!("{prefix}{i:06}")).collect()
}

/// A one-partition table whose rows `old000000..` sit in one file.
async fn table(dir: &std::path::Path) -> TableHandle {
    let mut table = CreateBuilder::new()
        .with_location(dir.to_str().unwrap())
        .with_columns(vec![
            StructField::new("pk", KernelType::STRING, false),
            StructField::new("v", KernelType::LONG, true),
            StructField::new("payload", KernelType::STRING, true),
            StructField::new("p", KernelType::STRING, true),
        ])
        .with_partition_columns(vec!["p".to_string()])
        .await
        .unwrap();
    let mut w = RecordBatchWriter::for_table(&table).unwrap();
    w.write(rows(&keys("old", 0..TABLE_ROWS), 0)).await.unwrap();
    w.flush_and_commit(&mut table).await.unwrap();
    TableHandle::open(dir.to_str().unwrap().into(), HashMap::new())
        .await
        .unwrap()
}

fn opts() -> UpsertOptions {
    UpsertOptions {
        primary_keys: vec!["pk".to_string()],
        partition_key: Some("p".to_string()),
        limits: Arc::new(ProcessLimits::with_fetch(8, 16, 256 << 20, 256 << 20)),
        ..Default::default()
    }
}

async fn upsert_with(
    handle: &mut TableHandle,
    keys: &[String],
    v: i64,
    opts: UpsertOptions,
) -> UpsertStats {
    handle
        .upsert(
            vec![rows(keys, v)],
            schema(),
            opts,
            MultipartConfig::default(),
        )
        .await
        .unwrap()
}

async fn upsert(handle: &mut TableHandle, keys: &[String], v: i64, isolate: bool) -> UpsertStats {
    let opts = UpsertOptions {
        isolate_source_rows: isolate,
        ..opts()
    };
    upsert_with(handle, keys, v, opts).await
}

async fn file_bytes(handle: &TableHandle, path: &str) -> Bytes {
    handle
        .table()
        .object_store()
        .get(&Path::parse(path).unwrap())
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap()
}

/// Every live row as (pk, v, payload), sorted.
async fn read_rows(handle: &TableHandle) -> Vec<(String, i64, String)> {
    let mut out = Vec::new();
    for f in handle.files().unwrap() {
        let bytes = file_bytes(handle, &f.path).await;
        for batch in ParquetRecordBatchReaderBuilder::try_new(bytes)
            .unwrap()
            .build()
            .unwrap()
        {
            let batch = batch.unwrap();
            let col = |name: &str| batch.column(batch.schema().index_of(name).unwrap()).clone();
            let (pk, v, payload) = (col("pk"), col("v"), col("payload"));
            let pk = pk.as_any().downcast_ref::<StringArray>().unwrap();
            let v = v.as_any().downcast_ref::<Int64Array>().unwrap();
            let payload = payload.as_any().downcast_ref::<StringArray>().unwrap();
            for i in 0..batch.num_rows() {
                out.push((
                    pk.value(i).to_string(),
                    v.value(i),
                    payload.value(i).to_string(),
                ));
            }
        }
    }
    out.sort();
    out
}

/// The first upsert updates 10 old rows and inserts 10 new ones; the second touches the
/// case's keys. With the option off, the first upsert writes its 20 rows into the file of
/// the 990 copied survivors, so any later batch that touches them copies all of those
/// survivors again. With it on, the 20 rows get their own file.
#[tokio::test]
async fn isolate_source_rows_copies_no_more_and_keeps_the_same_rows() {
    // (case, second upsert keys, rows copied per upsert with the option off, then on)
    type Case = (&'static str, Vec<String>, (usize, usize), (usize, usize));
    let cases: [Case; 3] = [
        (
            "touches the rows the last upsert wrote",
            [keys("old", 0..10), keys("new", 0..10)].concat(),
            (990, 990),
            (990, 0),
        ),
        (
            "touches only old rows",
            keys("old", 500..510),
            (990, 1000),
            (990, 980),
        ),
        (
            "touches old rows and rows the last upsert wrote",
            [keys("old", 500..505), keys("new", 0..5)].concat(),
            (990, 1000),
            (990, 1000),
        ),
    ];
    let first = [keys("old", 0..10), keys("new", 0..10)].concat();
    for (case, second, copied_off, copied_on) in cases {
        let (dir_off, dir_on) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
        let (mut off, mut on) = (table(dir_off.path()).await, table(dir_on.path()).await);

        let first_off = upsert(&mut off, &first, 1, false).await;
        let first_on = upsert(&mut on, &first, 1, true).await;
        assert_eq!(first_off.files_added, 1, "{case}: {first_off:?}");
        assert_eq!(first_on.files_added, 2, "{case}: {first_on:?}");

        let second_off = upsert(&mut off, &second, 2, false).await;
        let second_on = upsert(&mut on, &second, 2, true).await;
        assert_eq!(
            (first_off.rows_copied, second_off.rows_copied),
            copied_off,
            "{case}, option off: {first_off:?} {second_off:?}"
        );
        assert_eq!(
            (first_on.rows_copied, second_on.rows_copied),
            copied_on,
            "{case}, option on: {first_on:?} {second_on:?}"
        );
        assert_eq!(second_off.rows_updated, second_on.rows_updated, "{case}");

        let (rows_off, rows_on) = (read_rows(&off).await, read_rows(&on).await);
        assert_eq!(rows_off.len(), TABLE_ROWS + 10, "{case}");
        assert_eq!(rows_off, rows_on, "{case}");
    }
}

/// An upsert that only inserts already writes the new rows apart from every survivor,
/// so the option must add no file there.
#[tokio::test]
async fn isolate_source_rows_adds_no_file_to_an_insert_only_upsert() {
    let dir = tempfile::tempdir().unwrap();
    let mut handle = table(dir.path()).await;
    let stats = upsert(&mut handle, &keys("new", 0..10), 1, true).await;
    assert_eq!(
        (stats.files_added, stats.files_removed, stats.rows_copied),
        (1, 0, 0),
        "{stats:?}"
    );
}

/// Rows per row group of each file the upsert added, with `read_batch_size = 100` so the
/// writer sees survivor batches of at most 100 rows. A cap of one byte closes a row group
/// after every survivor batch (an update), and after every source row because the source
/// path also slices its writes by the cap (an update and an insert).
#[tokio::test]
async fn max_row_group_bytes_closes_row_groups_between_batches() {
    // (case, keys, row groups per added file without a cap, then with a one-byte cap)
    type Case = (&'static str, Vec<String>, Vec<usize>, Vec<usize>);
    let cases: [Case; 2] = [
        (
            "update: survivors of 10 batches, the first missing 10 rows, then 10 source rows",
            keys("old", 0..10),
            vec![1000],
            [vec![90], vec![100; 9], vec![1; 10]].concat(),
        ),
        (
            "insert: 250 source rows",
            keys("new", 0..250),
            vec![250],
            vec![1; 250],
        ),
    ];
    for (case, batch, uncapped, capped) in cases {
        let mut got = Vec::new();
        for cap in [None, Some(1)] {
            let dir = tempfile::tempdir().unwrap();
            let mut handle = table(dir.path()).await;
            let before: Vec<String> = handle
                .files()
                .unwrap()
                .into_iter()
                .map(|f| f.path)
                .collect();
            let o = UpsertOptions {
                read_batch_size: 100,
                max_row_group_bytes: cap,
                ..opts()
            };
            upsert_with(&mut handle, &batch, 1, o).await;
            let mut groups = Vec::new();
            for f in handle.files().unwrap() {
                if before.contains(&f.path) {
                    continue;
                }
                let meta =
                    ParquetRecordBatchReaderBuilder::try_new(file_bytes(&handle, &f.path).await)
                        .unwrap()
                        .metadata()
                        .clone();
                groups.extend(meta.row_groups().iter().map(|rg| rg.num_rows() as usize));
            }
            got.push((groups, read_rows(&handle).await));
        }
        assert_eq!(got[0].0, uncapped, "{case}, no cap");
        assert_eq!(got[1].0, capped, "{case}, one-byte cap");
        assert_eq!(got[0].1, got[1].1, "{case}: the cap changed the rows");
    }
}
