//! Decimal buffer realignment and schema casting.
//!
//! The pyarrow-facing half of ingest (the C Data Interface import) lives in the
//! `deltalite-python` binding crate; everything here is pure arrow-rs so it can be
//! unit-tested without a Python runtime.

use std::sync::Arc;

use arrow_array::{make_array, new_null_array, Array, RecordBatch};
use arrow_buffer::Buffer;
use arrow_cast::{cast_with_options, CastOptions};
use arrow_data::ArrayData;
use arrow_schema::{DataType, Schema, SchemaRef};

use crate::errors::{Error, Result};

/// Copy any decimal value buffer that is not aligned to its native type's alignment into
/// a freshly allocated (and therefore correctly aligned) buffer. Recurses into children
/// so nested decimals are covered too.
///
/// This is the fix for delta-io/delta-rs#3884: arrow-rs asserts 16-byte alignment while
/// constructing the *typed* decimal array, and buffers arriving over the C Data
/// Interface from pyarrow are only guaranteed 8-byte aligned (an Arrow IPC round-trip
/// reliably produces one). The assert fires *inside* a `RecordBatch`-level import,
/// before any batch exists to repair -- so ingest must go column by column as
/// `ArrayData` (which carries untyped buffers) and pass through here before
/// `make_array` builds the typed array.
pub fn realign_array_data(data: ArrayData) -> Result<ArrayData> {
    // arrow-rs represents Decimal256 as `i256`, a `#[repr(C)]` pair of 128-bit lanes, so
    // both decimal widths require 16-byte alignment.
    let align = match data.data_type() {
        DataType::Decimal128(_, _) | DataType::Decimal256(_, _) => {
            Some(std::mem::align_of::<i128>())
        }
        _ => None,
    };

    let mut children = Vec::with_capacity(data.child_data().len());
    let mut child_changed = false;
    for c in data.child_data() {
        let before = c.buffers().first().map(|b| b.as_ptr());
        let fixed = realign_array_data(c.clone())?;
        if fixed.buffers().first().map(|b| b.as_ptr()) != before {
            child_changed = true;
        }
        children.push(fixed);
    }

    let needs_fix = align
        .map(|a| {
            data.buffers()
                .iter()
                .any(|b| !(b.as_ptr() as usize).is_multiple_of(a))
        })
        .unwrap_or(false);

    if !needs_fix && !child_changed {
        return Ok(data);
    }

    let buffers = if needs_fix {
        data.buffers()
            .iter()
            .map(|b| realign_buffer(b, align.unwrap_or(16)))
            .collect()
    } else {
        data.buffers().to_vec()
    };

    let builder = data.into_builder().buffers(buffers).child_data(children);
    // Only buffers were replaced, with byte-identical copies, so the layout the
    // original data was validated against still holds.
    builder
        .build()
        .map_err(|e| Error::Generic(format!("rebuilding realigned array: {e}")))
}

/// Byte-identical copy of `buf` into a `Vec<i128>` allocation, which the allocator
/// guarantees is 16-byte aligned.
fn realign_buffer(buf: &Buffer, align: usize) -> Buffer {
    if (buf.as_ptr() as usize).is_multiple_of(align) {
        return buf.clone();
    }
    let bytes = buf.as_slice();
    let n = bytes.len().div_ceil(16);
    let mut v: Vec<i128> = vec![0; n];
    // SAFETY: `v` holds `n * 16 >= bytes.len()` bytes and the ranges cannot overlap
    // (freshly allocated destination).
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), v.as_mut_ptr() as *mut u8, bytes.len());
    }
    Buffer::from_vec(v).slice_with_length(0, bytes.len())
}

/// Cast `batch` to `target`, padding columns absent from the batch with nulls.
///
/// This is the equivalent of delta-rs's `schema_mode="merge"` for the additive-evolution
/// case: old Parquet files predating an `add_columns` are read up to the current schema,
/// and incoming batches missing a recently added column get nulls for it.
pub fn cast_to_schema(batch: &RecordBatch, target: &SchemaRef) -> Result<RecordBatch> {
    let opts = CastOptions {
        safe: false,
        ..Default::default()
    };
    let mut cols = Vec::with_capacity(target.fields().len());

    for field in target.fields() {
        match batch.schema().index_of(field.name()) {
            Ok(idx) => {
                let col = batch.column(idx);
                if col.data_type() == field.data_type() {
                    cols.push(col.clone());
                } else {
                    cols.push(
                        cast_with_options(col, field.data_type(), &opts).map_err(|e| {
                            Error::SchemaMismatch(format!(
                                "cannot cast column '{}' from {:?} to {:?}: {e}",
                                field.name(),
                                col.data_type(),
                                field.data_type()
                            ))
                        })?,
                    );
                }
            }
            Err(_) => cols.push(new_null_array(field.data_type(), batch.num_rows())),
        }
    }

    Ok(RecordBatch::try_new(target.clone(), cols)?)
}

/// Columns present in `source` but absent from the table schema. Schema evolution is
/// expected to have run before `upsert`, so these are a genuine mismatch.
pub fn unknown_columns(source: &Schema, target: &Schema) -> Vec<String> {
    source
        .fields()
        .iter()
        .filter(|f| target.index_of(f.name()).is_err())
        .map(|f| f.name().clone())
        .collect()
}

/// Import helper shared with the binding crate: realign a freshly imported column and
/// build the typed array. Split out so the alignment-sensitive step is testable here.
pub fn import_column(data: ArrayData) -> Result<Arc<dyn Array>> {
    Ok(make_array(realign_array_data(data)?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::cast::AsArray;
    use arrow_array::types::Decimal128Type;
    use arrow_array::{Decimal128Array, Int64Array, StringArray};
    use arrow_schema::Field;

    /// Build a Decimal128 `ArrayData` whose value buffer is deliberately NOT 16-byte
    /// aligned, the exact shape a pyarrow IPC round-trip hands us over FFI.
    fn misaligned_decimal_data(values: &[i128]) -> ArrayData {
        let mut bytes: Vec<u8> = vec![0u8; 8]; // 8-byte prefix forces misalignment
        for v in values {
            bytes.extend_from_slice(&v.to_le_bytes());
        }
        let buf = Buffer::from_vec(bytes).slice(8);
        assert_ne!(
            (buf.as_ptr() as usize) % 16,
            0,
            "test setup failed to produce a misaligned buffer"
        );
        let builder = ArrayData::builder(DataType::Decimal128(38, 10))
            .len(values.len())
            .add_buffer(buf);
        // SAFETY: layout is valid by construction; skipping validation is the point --
        // validation would reject the misalignment we are testing the repair of.
        unsafe { builder.build_unchecked() }
    }

    #[test]
    fn realigns_misaligned_decimal_buffer() {
        let values = [1_i128, -2, 3_000_000_000];
        let data = misaligned_decimal_data(&values);
        let fixed = realign_array_data(data).unwrap();
        assert_eq!(
            (fixed.buffers()[0].as_ptr() as usize) % 16,
            0,
            "buffer must be 16-byte aligned after realignment"
        );
        // And the typed array constructs (this is where #3884 aborts) with equal values.
        let arr = make_array(fixed);
        let arr = arr.as_primitive::<Decimal128Type>();
        assert_eq!(arr.values(), &values[..]);
    }

    #[test]
    fn aligned_buffers_are_left_untouched() {
        let arr = Decimal128Array::from(vec![1_i128, 2, 3]);
        let data = arr.to_data();
        let before = data.buffers()[0].as_ptr();
        let fixed = realign_array_data(data).unwrap();
        assert_eq!(fixed.buffers()[0].as_ptr(), before, "no copy expected");
    }

    #[test]
    fn cast_pads_missing_columns_with_nulls_and_casts_types() {
        let target: SchemaRef = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Utf8, true),
            Field::new("n", DataType::Int64, true),
            Field::new("added_later", DataType::Utf8, true),
        ]));
        let batch = RecordBatch::try_new(
            Arc::new(Schema::new(vec![
                Field::new("id", DataType::Utf8, true),
                Field::new("n", DataType::Int32, true),
            ])),
            vec![
                Arc::new(StringArray::from(vec!["a", "b"])),
                Arc::new(arrow_array::Int32Array::from(vec![1, 2])),
            ],
        )
        .unwrap();

        let out = cast_to_schema(&batch, &target).unwrap();
        assert_eq!(out.schema(), target);
        let n = out.column_by_name("n").unwrap();
        assert_eq!(n.data_type(), &DataType::Int64);
        assert_eq!(
            n.as_any().downcast_ref::<Int64Array>().unwrap().values(),
            &[1, 2]
        );
        assert_eq!(out.column_by_name("added_later").unwrap().null_count(), 2);
    }

    #[test]
    fn uncastable_column_is_a_schema_mismatch() {
        let target: SchemaRef = Arc::new(Schema::new(vec![Field::new("n", DataType::Int64, true)]));
        let batch = RecordBatch::try_new(
            Arc::new(Schema::new(vec![Field::new("n", DataType::Utf8, true)])),
            vec![Arc::new(StringArray::from(vec!["not a number"]))],
        )
        .unwrap();
        let err = cast_to_schema(&batch, &target).unwrap_err();
        assert!(matches!(err, Error::SchemaMismatch(_)), "{err}");
    }

    #[test]
    fn unknown_columns_reports_only_extras() {
        let target = Schema::new(vec![Field::new("a", DataType::Utf8, true)]);
        let source = Schema::new(vec![
            Field::new("a", DataType::Utf8, true),
            Field::new("b", DataType::Utf8, true),
        ]);
        assert_eq!(unknown_columns(&source, &target), vec!["b".to_string()]);
        assert!(unknown_columns(&target, &source).is_empty());
    }
}
