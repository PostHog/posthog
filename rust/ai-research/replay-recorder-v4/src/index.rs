//! The v4 index files: Parquet in `rrweb-v4/index/`. Column names are the ones in `replay-data.md`.
//!
//! Integer columns are signed, the types parquetjs writes, so a parquetjs writer can produce the same files.

use std::sync::Arc;

use arrow_array::{ArrayRef, Int64Array, RecordBatch, StringArray};
use arrow_schema::{ArrowError, DataType, Field, Schema};
use parquet::arrow::ArrowWriter;
use parquet::basic::Compression;
use parquet::errors::ParquetError;
use parquet::file::properties::WriterProperties;

#[derive(Debug, thiserror::Error)]
pub enum IndexError {
    #[error(transparent)]
    Arrow(#[from] ArrowError),
    #[error(transparent)]
    Parquet(#[from] ParquetError),
}

/// Writes one Parquet file, snappy-compressed as the v3 catalog is.
pub fn write_parquet(batch: &RecordBatch) -> Result<Vec<u8>, IndexError> {
    let properties = WriterProperties::builder()
        .set_compression(Compression::SNAPPY)
        .build();
    let mut out = Vec::new();
    let mut writer = ArrowWriter::try_new(&mut out, batch.schema(), Some(properties))?;
    writer.write(batch)?;
    writer.close()?;
    Ok(out)
}

/// A count or size as its signed column. Real values fit, and a larger one saturates.
fn int64(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

/// Where one inline image sits in a pack in `images-v4`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageIndexRow {
    pub team_id: i64,
    pub key_month: String,
    pub image_ref: String,
    pub pack_s3_key: String,
    /// Inclusive byte range of the sealed image in the pack.
    pub byte_start: u64,
    pub byte_end: u64,
    pub mime: String,
    pub byte_size: u64,
}

pub fn image_index(rows: &[ImageIndexRow]) -> Result<RecordBatch, IndexError> {
    let schema = Schema::new(vec![
        Field::new("team_id", DataType::Int64, false),
        Field::new("key_month", DataType::Utf8, false),
        Field::new("image_ref", DataType::Utf8, false),
        Field::new("pack_s3_key", DataType::Utf8, false),
        Field::new("byte_start", DataType::Int64, false),
        Field::new("byte_end", DataType::Int64, false),
        Field::new("mime", DataType::Utf8, false),
        Field::new("byte_size", DataType::Int64, false),
    ]);
    let columns: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from_iter_values(rows.iter().map(|r| r.team_id))),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.key_month),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.image_ref),
        )),
        Arc::new(StringArray::from_iter_values(
            rows.iter().map(|r| &r.pack_s3_key),
        )),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_start)),
        )),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_end)),
        )),
        Arc::new(StringArray::from_iter_values(rows.iter().map(|r| &r.mime))),
        Arc::new(Int64Array::from_iter_values(
            rows.iter().map(|r| int64(r.byte_size)),
        )),
    ];
    Ok(RecordBatch::try_new(Arc::new(schema), columns)?)
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

    use super::*;

    #[test]
    fn image_index_reads_back_with_the_documented_columns() {
        let rows = vec![ImageIndexRow {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            image_ref: "image:v4:7:2026-10:abc".to_owned(),
            pack_s3_key: "images/packs/dt=2026-10-15/7/1-0".to_owned(),
            byte_start: 0,
            byte_end: 99,
            mime: "image/png".to_owned(),
            byte_size: u64::MAX,
        }];
        let file = write_parquet(&image_index(&rows).unwrap()).unwrap();
        let mut reader = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(file))
            .unwrap()
            .build()
            .unwrap();
        let batch = reader.next().unwrap().unwrap();
        let columns: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|f| (f.name().clone(), f.data_type().clone(), f.is_nullable()))
            .collect();
        let column = |name: &str, data_type| (name.to_owned(), data_type, false);
        assert_eq!(
            columns,
            [
                column("team_id", DataType::Int64),
                column("key_month", DataType::Utf8),
                column("image_ref", DataType::Utf8),
                column("pack_s3_key", DataType::Utf8),
                column("byte_start", DataType::Int64),
                column("byte_end", DataType::Int64),
                column("mime", DataType::Utf8),
                column("byte_size", DataType::Int64),
            ]
        );
        let sizes = batch
            .column(7)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        assert_eq!(sizes.value(0), i64::MAX);
        let refs = batch
            .column(2)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(refs.value(0), "image:v4:7:2026-10:abc");
    }
}
