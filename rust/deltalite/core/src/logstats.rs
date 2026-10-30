//! Whole-table column statistics folded from the live files' Add actions, one file at a
//! time, so memory stays per column however many files the table has. The result agrees
//! field for field with delta-rs's flattened projection (`get_add_actions(flatten=True)`),
//! so a caller can swap one for the other.

use std::cmp::Ordering;
use std::sync::Arc;

use arrow_array::{
    new_null_array, Array, ArrayRef, BinaryArray, BooleanArray, Date32Array, Decimal128Array,
    Float32Array, Float64Array, Int16Array, Int32Array, Int64Array, Int8Array, RecordBatch,
    StringArray, TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema};
use delta_kernel::engine::arrow_conversion::TryFromKernel as _;
use delta_kernel::expressions::Scalar;
use delta_kernel::schema::{DataType as KernelType, StructField};
use deltalake::table::state::DeltaTableState;
use indexmap::IndexMap;

use crate::errors::{Error, Result};

/// Number of live files folded. Always present and never null.
pub const NUM_FILES: &str = "num_files";
/// Sum of the per-file `numRecords`. Null when no live file carries one.
pub const NUM_RECORDS: &str = "num_records";

const NULL_COUNT_PREFIX: &str = "null_count.";
const MIN_PREFIX: &str = "min.";
const MAX_PREFIX: &str = "max.";

struct ColumnFold {
    kind: KernelType,
    null_count: Option<i64>,
    has_null_count: bool,
    min: Option<Scalar>,
    has_min: bool,
    max: Option<Scalar>,
    has_max: bool,
}

impl ColumnFold {
    fn new(kind: KernelType) -> Self {
        Self {
            kind,
            null_count: None,
            has_null_count: false,
            min: None,
            has_min: false,
            max: None,
            has_max: false,
        }
    }
}

/// Fold the live files' Add-action statistics into a one-row batch.
///
/// `columns` restricts the fold to those table columns; `None` folds every column the log
/// has a statistic for. The row holds [`NUM_FILES`] and [`NUM_RECORDS`] (Int64) and, per
/// column, `null_count.<col>` (Int64) plus `min.<col>` and `max.<col>` in the column's own
/// Arrow type, the names and types of the flattened Add-action projection. A statistic no
/// live file carries for a column is absent; one that every carrying file has null is null.
/// A nested (struct) column is skipped: the projection flattens its children instead.
pub fn add_action_stats(
    state: &DeltaTableState,
    columns: Option<&[String]>,
) -> Result<RecordBatch> {
    let mut folds: IndexMap<String, ColumnFold> = IndexMap::new();
    let mut num_files: i64 = 0;
    let mut num_records: Option<i64> = None;

    for view in state.log_data().iter() {
        num_files += 1;
        if let Some(n) = view.num_records() {
            num_records = Some(num_records.unwrap_or(0).saturating_add(n as i64));
        }
        if let Some(Scalar::Struct(counts)) = view.null_counts() {
            for (field, value) in counts.fields().iter().zip(counts.values()) {
                let Some(fold) = fold_for(&mut folds, field, columns) else {
                    continue;
                };
                fold.has_null_count = true;
                if let Scalar::Long(n) = value {
                    fold.null_count = Some(fold.null_count.unwrap_or(0).saturating_add(*n));
                }
            }
        }
        if let Some(Scalar::Struct(mins)) = view.min_values() {
            for (field, value) in mins.fields().iter().zip(mins.values()) {
                let Some(fold) = fold_for(&mut folds, field, columns) else {
                    continue;
                };
                fold.has_min = true;
                fold.min = better(fold.min.take(), value, Ordering::Less);
            }
        }
        if let Some(Scalar::Struct(maxs)) = view.max_values() {
            for (field, value) in maxs.fields().iter().zip(maxs.values()) {
                let Some(fold) = fold_for(&mut folds, field, columns) else {
                    continue;
                };
                fold.has_max = true;
                fold.max = better(
                    fold.max.take(),
                    &as_written(value.clone()),
                    Ordering::Greater,
                );
            }
        }
    }

    let mut fields = vec![
        Field::new(NUM_FILES, DataType::Int64, false),
        Field::new(NUM_RECORDS, DataType::Int64, true),
    ];
    let mut arrays: Vec<ArrayRef> = vec![
        Arc::new(Int64Array::from(vec![num_files])),
        Arc::new(Int64Array::from(vec![num_records])),
    ];
    for (name, fold) in &folds {
        let arrow_type = DataType::try_from_kernel(&fold.kind)?;
        if fold.has_null_count {
            fields.push(Field::new(
                format!("{NULL_COUNT_PREFIX}{name}"),
                DataType::Int64,
                true,
            ));
            arrays.push(Arc::new(Int64Array::from(vec![fold.null_count])));
        }
        if fold.has_min {
            fields.push(Field::new(
                format!("{MIN_PREFIX}{name}"),
                arrow_type.clone(),
                true,
            ));
            arrays.push(one_row(fold.min.as_ref(), &arrow_type)?);
        }
        if fold.has_max {
            fields.push(Field::new(
                format!("{MAX_PREFIX}{name}"),
                arrow_type.clone(),
                true,
            ));
            arrays.push(one_row(fold.max.as_ref(), &arrow_type)?);
        }
    }
    Ok(RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)?)
}

/// The fold for a statistics field, or None for a nested column or one outside the request.
fn fold_for<'a>(
    folds: &'a mut IndexMap<String, ColumnFold>,
    field: &StructField,
    columns: Option<&[String]>,
) -> Option<&'a mut ColumnFold> {
    if !matches!(field.data_type, KernelType::Primitive(_)) {
        return None;
    }
    if let Some(columns) = columns {
        if !columns.iter().any(|c| c == &field.name) {
            return None;
        }
        if folds.is_empty() {
            // Reserve the requested order up front; a column no file reports stays out of the
            // output because it never sets a `has_*` flag.
            for name in columns {
                folds
                    .entry(name.clone())
                    .or_insert_with(|| ColumnFold::new(field.data_type.clone()));
            }
        }
    }
    Some(
        folds
            .entry(field.name.clone())
            .and_modify(|fold| fold.kind = field.data_type.clone())
            .or_insert_with(|| ColumnFold::new(field.data_type.clone())),
    )
}

fn better(current: Option<Scalar>, candidate: &Scalar, wanted: Ordering) -> Option<Scalar> {
    if candidate.is_null() {
        return current;
    }
    match current {
        None => Some(candidate.clone()),
        Some(current) => match candidate.logical_partial_cmp(&current) {
            Some(order) if order == wanted => Some(candidate.clone()),
            _ => Some(current),
        },
    }
}

/// `LogicalFileView::max_values` moves a millisecond-aligned timestamp up by one millisecond,
/// on the assumption that a checkpoint truncated it. The flattened projection reports the
/// value as written, and so does this fold. Only an aligned input leaves that step aligned,
/// so taking the millisecond back is exact.
fn as_written(value: Scalar) -> Scalar {
    match value {
        Scalar::Timestamp(v) if v % 1_000 == 0 => Scalar::Timestamp(v - 1_000),
        Scalar::TimestampNtz(v) if v % 1_000 == 0 => Scalar::TimestampNtz(v - 1_000),
        other => other,
    }
}

fn one_row(value: Option<&Scalar>, arrow_type: &DataType) -> Result<ArrayRef> {
    let Some(value) = value else {
        return Ok(new_null_array(arrow_type, 1));
    };
    let array: ArrayRef = match value {
        Scalar::Integer(v) => Arc::new(Int32Array::from(vec![*v])),
        Scalar::Long(v) => Arc::new(Int64Array::from(vec![*v])),
        Scalar::Short(v) => Arc::new(Int16Array::from(vec![*v])),
        Scalar::Byte(v) => Arc::new(Int8Array::from(vec![*v])),
        Scalar::Float(v) => Arc::new(Float32Array::from(vec![*v])),
        Scalar::Double(v) => Arc::new(Float64Array::from(vec![*v])),
        Scalar::String(v) => Arc::new(StringArray::from(vec![v.as_str()])),
        Scalar::Boolean(v) => Arc::new(BooleanArray::from(vec![*v])),
        Scalar::Timestamp(v) => {
            Arc::new(TimestampMicrosecondArray::from(vec![*v]).with_timezone("UTC"))
        }
        Scalar::TimestampNtz(v) => Arc::new(TimestampMicrosecondArray::from(vec![*v])),
        Scalar::Date(v) => Arc::new(Date32Array::from(vec![*v])),
        Scalar::Binary(v) => Arc::new(BinaryArray::from(vec![v.as_slice()])),
        Scalar::Decimal(d) => Arc::new(
            Decimal128Array::from(vec![d.bits()])
                .with_precision_and_scale(d.precision(), d.scale() as i8)?,
        ),
        // Null, nested and any variant behind a kernel feature: nothing to report.
        _ => new_null_array(arrow_type, 1),
    };
    if array.data_type() != arrow_type {
        return Err(Error::Generic(format!(
            "add-action statistic has type {} but the column is {arrow_type}",
            array.data_type()
        )));
    }
    Ok(array)
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_schema::TimeUnit;
    use delta_kernel::schema::PrimitiveType;

    #[test]
    fn better_keeps_the_wanted_side_and_ignores_nulls_and_other_types() {
        let min = better(None, &Scalar::Long(5), Ordering::Less);
        let min = better(min, &Scalar::Long(9), Ordering::Less);
        let min = better(min, &Scalar::Null(KernelType::LONG), Ordering::Less);
        let min = better(min, &Scalar::String("a".into()), Ordering::Less);
        let min = better(min, &Scalar::Long(-2), Ordering::Less);
        assert!(matches!(min, Some(Scalar::Long(-2))));

        let max = better(None, &Scalar::String("pear".into()), Ordering::Greater);
        let max = better(max, &Scalar::String("apple".into()), Ordering::Greater);
        assert!(matches!(max, Some(Scalar::String(s)) if s == "pear"));
    }

    #[test]
    fn as_written_undoes_the_file_views_millisecond_step_only_when_aligned() {
        assert!(matches!(
            as_written(Scalar::Timestamp(2_000)),
            Scalar::Timestamp(1_000)
        ));
        assert!(matches!(
            as_written(Scalar::TimestampNtz(0)),
            Scalar::TimestampNtz(-1_000)
        ));
        assert!(matches!(
            as_written(Scalar::Timestamp(1_500)),
            Scalar::Timestamp(1_500)
        ));
        assert!(matches!(
            as_written(Scalar::Long(2_000)),
            Scalar::Long(2_000)
        ));
    }

    #[test]
    fn one_row_matches_the_columns_arrow_type() {
        let utc = DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into()));
        let ts = one_row(Some(&Scalar::Timestamp(7)), &utc).unwrap();
        assert_eq!(ts.data_type(), &utc);
        assert_eq!(
            ts.as_any()
                .downcast_ref::<TimestampMicrosecondArray>()
                .unwrap()
                .value(0),
            7
        );

        let decimal = DataType::Decimal128(10, 2);
        let d = one_row(Some(&Scalar::decimal(1234, 10, 2).unwrap()), &decimal).unwrap();
        assert_eq!(d.data_type(), &decimal);

        let none = one_row(None, &DataType::Utf8).unwrap();
        assert_eq!(none.len(), 1);
        assert!(none.is_null(0));

        assert!(one_row(Some(&Scalar::Long(1)), &DataType::Utf8).is_err());
    }

    #[test]
    fn fold_for_skips_nested_columns_and_keeps_the_requested_order() {
        let mut folds = IndexMap::new();
        let nested = StructField::new(
            "addr",
            KernelType::Struct(Box::new(
                delta_kernel::schema::StructType::try_new(Vec::<StructField>::new()).unwrap(),
            )),
            true,
        );
        assert!(fold_for(&mut folds, &nested, None).is_none());

        let a = StructField::new("a", KernelType::Primitive(PrimitiveType::Long), true);
        let b = StructField::new("b", KernelType::Primitive(PrimitiveType::String), true);
        let asked = vec!["b".to_string(), "a".to_string(), "zzz".to_string()];
        assert!(fold_for(&mut folds, &a, Some(&asked)).is_some());
        assert!(fold_for(&mut folds, &b, Some(&asked)).is_some());
        assert_eq!(folds.keys().cloned().collect::<Vec<_>>(), asked);
        assert!(matches!(
            folds["b"].kind,
            KernelType::Primitive(PrimitiveType::String)
        ));

        let c = StructField::new("c", KernelType::Primitive(PrimitiveType::Long), true);
        assert!(fold_for(&mut folds, &c, Some(&asked)).is_none());
    }
}
