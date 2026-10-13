//! Add-action statistics for files written by [`crate::writer`].
//!
//! Vendored from delta-rs `crates/core/src/writer/stats.rs` at deltalake 0.32.4
//! (Apache-2.0, Copyright (2020) QP Hou and a number of other contributors), because the
//! function that turns a written file's Parquet footer into an `Add` action
//! (`create_add`) is `pub(crate)` there. The logic is unchanged apart from error plumbing
//! and dropping the `itertools` dependency. The `Add` stats it produces must stay
//! byte-for-byte what delta-rs's `RecordBatchWriter` produces: deltalite's pruning and
//! every Delta reader trust them. `crate::writer`'s tests compare the two directly, so
//! a deltalake bump that changes delta-rs's stats fails there instead of drifting.

use std::collections::HashMap;
use std::collections::HashSet;
use std::ops::{AddAssign, Not};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use delta_kernel::expressions::Scalar;
use delta_kernel::table_properties::DataSkippingNumIndexedCols;
use deltalake::kernel::scalars::ScalarExt;
use deltalake::kernel::Add;
use deltalake::protocol::{ColumnCountStat, ColumnValueStat, Stats};
use indexmap::IndexMap;
use parquet::basic::{LogicalType, TimeUnit, Type};
use parquet::file::metadata::{ParquetMetaData, RowGroupMetaData};
use parquet::file::statistics::Statistics;
use parquet::schema::types::{ColumnDescriptor, SchemaDescriptor};
use tracing::warn;

/// The subset of delta-rs's `DeltaWriterError` the stats code raises.
#[derive(Debug)]
enum DeltaWriterError {
    StatsParsingFailed {
        debug_value: String,
        logical_type: Option<LogicalType>,
    },
    Generic(String),
}

impl From<DeltaWriterError> for crate::errors::Error {
    fn from(e: DeltaWriterError) -> Self {
        match e {
            DeltaWriterError::StatsParsingFailed {
                debug_value,
                logical_type,
            } => crate::errors::Error::Generic(format!(
                "failed to parse file stats value {debug_value} as {logical_type:?}"
            )),
            DeltaWriterError::Generic(msg) => crate::errors::Error::Generic(msg),
        }
    }
}

pub(crate) fn create_add(
    partition_values: &IndexMap<String, Scalar>,
    path: String,
    size: i64,
    file_metadata: &ParquetMetaData,
    num_indexed_cols: DataSkippingNumIndexedCols,
    stats_columns: &Option<Vec<impl AsRef<str>>>,
) -> crate::errors::Result<Add> {
    let stats = stats_from_file_metadata(
        partition_values,
        file_metadata,
        num_indexed_cols,
        stats_columns,
    )?;
    let stats_string = serde_json::to_string(&stats)
        .map_err(|e| crate::errors::Error::Generic(format!("serializing file stats: {e}")))?;

    // Determine the modification timestamp to include in the add action - milliseconds since epoch
    // Err should be impossible in this case since `SystemTime::now()` is always greater than `UNIX_EPOCH`
    let modification_time = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let modification_time = modification_time.as_millis() as i64;

    Ok(Add {
        path,
        size,
        partition_values: partition_values
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    if v.is_null() {
                        None
                    } else {
                        Some(v.serialize())
                    },
                )
            })
            .collect(),
        modification_time,
        data_change: true,
        stats: Some(stats_string),
        tags: None,
        deletion_vector: None,
        base_row_id: None,
        default_row_commit_version: None,
        clustering_provider: None,
    })
}

fn stats_from_file_metadata(
    partition_values: &IndexMap<String, Scalar>,
    file_metadata: &ParquetMetaData,
    num_indexed_cols: DataSkippingNumIndexedCols,
    stats_columns: &Option<Vec<impl AsRef<str>>>,
) -> Result<Stats, DeltaWriterError> {
    let schema_descriptor = file_metadata.file_metadata().schema_descr();

    let row_group_metadata: Vec<RowGroupMetaData> = file_metadata.row_groups().to_vec();

    stats_from_metadata(
        partition_values,
        Arc::new(schema_descriptor.clone()),
        row_group_metadata,
        file_metadata.file_metadata().num_rows(),
        num_indexed_cols,
        stats_columns,
    )
}

fn stats_from_metadata(
    partition_values: &IndexMap<String, Scalar>,
    schema_descriptor: Arc<SchemaDescriptor>,
    row_group_metadata: Vec<RowGroupMetaData>,
    num_rows: i64,
    num_indexed_cols: DataSkippingNumIndexedCols,
    stats_columns: &Option<Vec<impl AsRef<str>>>,
) -> Result<Stats, DeltaWriterError> {
    let mut min_values: HashMap<String, ColumnValueStat> = HashMap::new();
    let mut max_values: HashMap<String, ColumnValueStat> = HashMap::new();
    let mut null_count: HashMap<String, ColumnCountStat> = HashMap::new();
    let dialect = sqlparser::dialect::GenericDialect {};

    let idx_to_iterate = if let Some(stats_cols) = stats_columns {
        let stats_cols = stats_cols
            .iter()
            .map(|v| {
                match sqlparser::parser::Parser::new(&dialect)
                    .try_with_sql(v.as_ref())
                    .map_err(|e| DeltaWriterError::Generic(e.to_string()))?
                    .parse_multipart_identifier()
                {
                    Ok(parts) => Ok(parts
                        .into_iter()
                        .map(|v| v.value)
                        .collect::<Vec<_>>()
                        .join(".")),
                    Err(e) => Err(DeltaWriterError::Generic(e.to_string())),
                }
            })
            .collect::<Result<Vec<String>, DeltaWriterError>>()?;

        schema_descriptor
            .columns()
            .iter()
            .enumerate()
            .filter_map(|(index, col)| {
                if stats_cols.contains(&col.name().to_string()) {
                    Some(index)
                } else {
                    None
                }
            })
            .collect()
    } else if num_indexed_cols == DataSkippingNumIndexedCols::AllColumns {
        (0..schema_descriptor.num_columns()).collect::<Vec<_>>()
    } else if let DataSkippingNumIndexedCols::NumColumns(n_cols) = num_indexed_cols {
        // The `delta.dataSkippingNumIndexedCols` budget is consumed by distinct
        // top-level fields, not by parquet leaf columns. A single top-level
        // column with many nested fields therefore takes one slot, not N.
        // Partition columns do not consume a slot.
        let limit = n_cols as usize;
        let mut admitted: HashSet<String> = HashSet::new();
        let mut admitted_count: usize = 0;
        let mut idxs: Vec<usize> = Vec::new();
        for (idx, col) in schema_descriptor.columns().iter().enumerate() {
            let top = match col.path().parts().first() {
                Some(t) => t.clone(),
                None => continue,
            };
            if partition_values.contains_key(&top) {
                continue;
            }
            if !admitted.contains(&top) {
                if admitted_count >= limit {
                    break;
                }
                admitted.insert(top);
                admitted_count += 1;
            }
            idxs.push(idx);
        }
        idxs
    } else {
        return Err(DeltaWriterError::Generic(
            "delta.dataSkippingNumIndexedCols valid values are >=-1".to_string(),
        ));
    };

    for idx in idx_to_iterate {
        let column_descr = schema_descriptor.column(idx);

        let column_path = column_descr.path();
        let column_path_parts = column_path.parts();

        // Do not include partition columns in statistics (still relevant for
        // the `AllColumns` and explicit `stats_columns` branches).
        if partition_values.contains_key(&column_path_parts[0]) {
            continue;
        }

        let maybe_stats: Option<AggregatedStats> = row_group_metadata
            .iter()
            .flat_map(|g| {
                g.column(idx).statistics().into_iter().filter_map(|s| {
                    let is_binary = matches!(&column_descr.physical_type(), Type::BYTE_ARRAY)
                        && matches!(column_descr.logical_type_ref(), Some(LogicalType::String))
                            .not();
                    if is_binary {
                        warn!(
                            "Skipping column {} because it's a binary field.",
                            &column_descr.name().to_string()
                        );
                        None
                    } else {
                        Some(AggregatedStats::from((s, column_descr.logical_type_ref())))
                    }
                })
            })
            .reduce(|mut left, right| {
                left += right;
                left
            });

        if let Some(stats) = maybe_stats {
            apply_min_max_for_column(
                stats,
                column_descr.clone(),
                column_descr.path().parts(),
                &mut min_values,
                &mut max_values,
                &mut null_count,
            )?;
        }
    }

    Ok(Stats {
        min_values,
        max_values,
        num_records: num_rows,
        null_count,
    })
}

/// Logical scalars extracted from statistics. These are used to aggregate
/// minimums and maximums. We can't use the physical scalars because they
/// are not ordered correctly for some types. For example, decimals are stored
/// as fixed length binary, and can't be sorted leixcographically.
#[derive(Debug, Clone, PartialEq, PartialOrd)]
enum StatsScalar {
    Boolean(bool),
    Int32(i32),
    Int64(i64),
    Float32(f32),
    Float64(f64),
    Date(chrono::NaiveDate),
    Timestamp(chrono::NaiveDateTime),
    // We are serializing to f64 later and the ordering should be the same
    // Scale is stored to handle scale=0 serialization correctly
    Decimal { value: f64, scale: i32 },
    String(String),
    Bytes(Vec<u8>),
    Uuid(uuid::Uuid),
}

impl StatsScalar {
    fn try_from_stats(
        stats: &Statistics,
        logical_type: Option<&LogicalType>,
        use_min: bool,
    ) -> Result<Self, DeltaWriterError> {
        macro_rules! get_stat {
            ($val: expr) => {
                if use_min {
                    *$val.min_opt().unwrap()
                } else {
                    *$val.max_opt().unwrap()
                }
            };
        }

        match (stats, logical_type) {
            (Statistics::Boolean(v), _) => Ok(Self::Boolean(get_stat!(v))),
            // Int32 can be date, decimal, or just int32
            (Statistics::Int32(v), Some(LogicalType::Date)) => {
                let epoch_start = chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(); // creating from epoch should be infallible
                let date = epoch_start + chrono::Duration::days(get_stat!(v) as i64);
                Ok(Self::Date(date))
            }
            (Statistics::Int32(v), Some(LogicalType::Decimal { scale, .. })) => {
                let val = get_stat!(v) as f64 / 10.0_f64.powi(*scale);
                // Spark serializes these as numbers
                Ok(Self::Decimal {
                    value: val,
                    scale: *scale,
                })
            }
            (Statistics::Int32(v), _) => Ok(Self::Int32(get_stat!(v))),
            // Int64 can be timestamp, decimal, or integer
            (Statistics::Int64(v), Some(LogicalType::Timestamp { unit, .. })) => {
                // For now, we assume timestamps are adjusted to UTC. Non-UTC timestamps
                // are behind a feature gate in Delta:
                // https://github.com/delta-io/delta/blob/master/PROTOCOL.md#timestamp-without-timezone-timestampntz
                let v = get_stat!(v);
                let timestamp = match unit {
                    TimeUnit::MILLIS => chrono::DateTime::from_timestamp_millis(v),
                    TimeUnit::MICROS => chrono::DateTime::from_timestamp_micros(v),
                    TimeUnit::NANOS => {
                        let secs = v / 1_000_000_000;
                        let nanosecs = (v % 1_000_000_000) as u32;
                        chrono::DateTime::from_timestamp(secs, nanosecs)
                    }
                };
                let timestamp = timestamp.ok_or(DeltaWriterError::StatsParsingFailed {
                    debug_value: v.to_string(),
                    logical_type: logical_type.cloned(),
                })?;
                Ok(Self::Timestamp(timestamp.naive_utc()))
            }
            (Statistics::Int64(v), Some(LogicalType::Decimal { scale, .. })) => {
                let val = get_stat!(v) as f64 / 10.0_f64.powi(*scale);
                // Spark serializes these as numbers
                Ok(Self::Decimal {
                    value: val,
                    scale: *scale,
                })
            }
            (Statistics::Int64(v), _) => Ok(Self::Int64(get_stat!(v))),
            (Statistics::Float(v), _) => Ok(Self::Float32(get_stat!(v))),
            (Statistics::Double(v), _) => Ok(Self::Float64(get_stat!(v))),
            (Statistics::ByteArray(v), logical_type) => {
                let bytes = if use_min {
                    v.min_bytes_opt()
                } else {
                    v.max_bytes_opt()
                }
                .unwrap_or_default();
                match logical_type {
                    None => Ok(Self::Bytes(bytes.to_vec())),
                    Some(LogicalType::String) => {
                        Ok(Self::String(String::from_utf8(bytes.to_vec()).map_err(
                            |_| DeltaWriterError::StatsParsingFailed {
                                debug_value: format!("{bytes:?}"),
                                logical_type: Some(LogicalType::String),
                            },
                        )?))
                    }
                    _ => Err(DeltaWriterError::StatsParsingFailed {
                        debug_value: format!("{bytes:?}"),
                        logical_type: logical_type.cloned(),
                    }),
                }
            }
            (Statistics::FixedLenByteArray(v), Some(LogicalType::Decimal { scale, precision })) => {
                let val = if use_min {
                    v.min_bytes_opt()
                } else {
                    v.max_bytes_opt()
                }
                .unwrap_or_default();

                let val = if val.len() <= 16 {
                    i128::from_be_bytes(sign_extend_be(val)) as f64
                } else {
                    return Err(DeltaWriterError::StatsParsingFailed {
                        debug_value: format!("{val:?}"),
                        logical_type: Some(LogicalType::Decimal {
                            scale: *scale,
                            precision: *precision,
                        }),
                    });
                };

                let mut val = val / 10.0_f64.powi(*scale);

                if val.is_normal()
                    && (val.trunc() as i128).to_string().len() > (precision - scale) as usize
                {
                    // For normal values with integer parts that get rounded to a number beyond
                    // the precision - scale range take the next smaller (by magnitude) value
                    val = f64::from_bits(val.to_bits() - 1);
                }

                Ok(Self::Decimal {
                    value: val,
                    scale: *scale,
                })
            }
            (Statistics::FixedLenByteArray(v), Some(LogicalType::Uuid)) => {
                let val = if use_min {
                    v.min_bytes_opt()
                } else {
                    v.max_bytes_opt()
                }
                .unwrap_or_default();

                if val.len() != 16 {
                    return Err(DeltaWriterError::StatsParsingFailed {
                        debug_value: format!("{val:?}"),
                        logical_type: Some(LogicalType::Uuid),
                    });
                }

                let mut bytes = [0; 16];
                bytes.copy_from_slice(val);

                let val = uuid::Uuid::from_bytes(bytes);
                Ok(Self::Uuid(val))
            }
            (stats, _) => Err(DeltaWriterError::StatsParsingFailed {
                debug_value: format!("{stats:?}"),
                logical_type: logical_type.cloned(),
            }),
        }
    }
}

/// Performs big endian sign extension
/// Copied from arrow-rs repo/parquet crate:
/// https://github.com/apache/arrow-rs/blob/b25c441745602c9967b1e3cc4a28bc469cfb1311/parquet/src/arrow/buffer/bit_util.rs#L54
pub fn sign_extend_be<const N: usize>(b: &[u8]) -> [u8; N] {
    assert!(b.len() <= N, "Array too large, expected less than {N}");
    let is_negative = (b[0] & 128u8) == 128u8;
    let mut result = if is_negative { [255u8; N] } else { [0u8; N] };
    for (d, s) in result.iter_mut().skip(N - b.len()).zip(b) {
        *d = *s;
    }
    result
}

impl From<StatsScalar> for serde_json::Value {
    fn from(scalar: StatsScalar) -> Self {
        match scalar {
            StatsScalar::Boolean(v) => serde_json::Value::Bool(v),
            StatsScalar::Int32(v) => serde_json::Value::from(v),
            StatsScalar::Int64(v) => serde_json::Value::from(v),
            StatsScalar::Float32(v) => serde_json::Value::from(v),
            StatsScalar::Float64(v) => serde_json::Value::from(v),
            StatsScalar::Date(v) => serde_json::Value::from(v.format("%Y-%m-%d").to_string()),
            StatsScalar::Timestamp(v) => {
                serde_json::Value::from(v.format("%Y-%m-%dT%H:%M:%S%.fZ").to_string())
            }
            StatsScalar::Decimal { value, scale } => {
                // For scale=0, serialize as integer since serde_json would otherwise
                // serialize f64 as "1234.0" instead of "1234"
                if scale == 0 {
                    serde_json::Value::from(value.round() as i64)
                } else {
                    serde_json::Value::from(value)
                }
            }
            StatsScalar::String(v) => serde_json::Value::from(v),
            StatsScalar::Bytes(v) => {
                let escaped_bytes = v
                    .into_iter()
                    .flat_map(std::ascii::escape_default)
                    .collect::<Vec<u8>>();
                let escaped_string = String::from_utf8(escaped_bytes).unwrap();
                serde_json::Value::from(escaped_string)
            }
            StatsScalar::Uuid(v) => serde_json::Value::from(v.hyphenated().to_string()),
        }
    }
}

/// Aggregated stats
struct AggregatedStats {
    pub min: Option<StatsScalar>,
    pub max: Option<StatsScalar>,
    pub null_count: u64,
}

impl From<(&Statistics, Option<&LogicalType>)> for AggregatedStats {
    fn from(value: (&Statistics, Option<&LogicalType>)) -> Self {
        let (stats, logical_type) = value;
        let null_count = stats.null_count_opt().unwrap_or_default();
        if stats.min_bytes_opt().is_some() && stats.max_bytes_opt().is_some() {
            let min = StatsScalar::try_from_stats(stats, logical_type, true).ok();
            let max = StatsScalar::try_from_stats(stats, logical_type, false).ok();
            Self {
                min,
                max,
                null_count,
            }
        } else {
            Self {
                min: None,
                max: None,
                null_count,
            }
        }
    }
}

impl AddAssign for AggregatedStats {
    fn add_assign(&mut self, rhs: Self) {
        self.min = match (self.min.take(), rhs.min) {
            (Some(lhs), Some(rhs)) => {
                if lhs < rhs {
                    Some(lhs)
                } else {
                    Some(rhs)
                }
            }
            (lhs, rhs) => lhs.or(rhs),
        };
        self.max = match (self.max.take(), rhs.max) {
            (Some(lhs), Some(rhs)) => {
                if lhs > rhs {
                    Some(lhs)
                } else {
                    Some(rhs)
                }
            }
            (lhs, rhs) => lhs.or(rhs),
        };

        self.null_count += rhs.null_count;
    }
}

/// For a list field, we don't want the inner field names. We need to chuck out
/// the list and items fields from the path, but also need to handle the
/// peculiar case where the user named the list field "list" or "item".
///
/// NOTE: As of delta_kernel 0.3.1 the name switched from `item` to `element` to line up with the
/// parquet spec, see
/// [here](https://github.com/apache/parquet-format/blob/master/LogicalTypes.md#lists)
///
/// For example:
///
/// * ["some_nested_list", "list", "item", "list", "item"] -> "some_nested_list"
/// * ["some_list", "list", "item"] -> "some_list"
/// * ["list", "list", "item"] -> "list"
/// * ["item", "list", "item"] -> "item"
fn get_list_field_name(column_descr: &Arc<ColumnDescriptor>) -> Option<String> {
    let max_rep_levels = column_descr.max_rep_level();
    let column_path_parts = column_descr.path().parts();

    // If there are more nested names, we can't handle them yet.
    if column_path_parts.len() > (2 * max_rep_levels + 1) as usize {
        return None;
    }

    let mut column_path_parts = column_path_parts.to_vec();
    let mut items_seen = 0;
    let mut lists_seen = 0;
    while let Some(part) = column_path_parts.pop() {
        match (part.as_str(), lists_seen, items_seen) {
            ("list", seen, _) if seen == max_rep_levels => return Some("list".to_string()),
            ("element", _, seen) if seen == max_rep_levels => return Some("element".to_string()),
            ("list", _, _) => lists_seen += 1,
            ("element", _, _) => items_seen += 1,
            (other, _, _) => return Some(other.to_string()),
        }
    }
    None
}

fn apply_min_max_for_column(
    statistics: AggregatedStats,
    column_descr: Arc<ColumnDescriptor>,
    column_path_parts: &[String],
    min_values: &mut HashMap<String, ColumnValueStat>,
    max_values: &mut HashMap<String, ColumnValueStat>,
    null_counts: &mut HashMap<String, ColumnCountStat>,
) -> Result<(), DeltaWriterError> {
    // Special handling for list column
    if column_descr.max_rep_level() > 0 {
        let key = get_list_field_name(&column_descr);

        if let Some(key) = key {
            null_counts.insert(key, ColumnCountStat::Value(statistics.null_count as i64));
        }

        return Ok(());
    }

    match (column_path_parts.len(), column_path_parts.first()) {
        // Base case - we are at the leaf struct level in the path
        (1, _) => {
            let key = column_descr.name().to_string();

            if let Some(min) = statistics.min {
                let min = ColumnValueStat::Value(min.into());
                min_values.insert(key.clone(), min);
            }

            if let Some(max) = statistics.max {
                let max = ColumnValueStat::Value(max.into());
                max_values.insert(key.clone(), max);
            }

            null_counts.insert(key, ColumnCountStat::Value(statistics.null_count as i64));

            Ok(())
        }
        // Recurse to load value at the appropriate level of HashMap
        (_, Some(key)) => {
            let child_min_values = min_values
                .entry(key.to_owned())
                .or_insert_with(|| ColumnValueStat::Column(HashMap::new()));
            let child_max_values = max_values
                .entry(key.to_owned())
                .or_insert_with(|| ColumnValueStat::Column(HashMap::new()));
            let child_null_counts = null_counts
                .entry(key.to_owned())
                .or_insert_with(|| ColumnCountStat::Column(HashMap::new()));

            match (child_min_values, child_max_values, child_null_counts) {
                (
                    ColumnValueStat::Column(mins),
                    ColumnValueStat::Column(maxes),
                    ColumnCountStat::Column(null_counts),
                ) => {
                    let remaining_parts: Vec<String> = column_path_parts
                        .iter()
                        .skip(1)
                        .map(|s| s.to_string())
                        .collect();

                    apply_min_max_for_column(
                        statistics,
                        column_descr,
                        remaining_parts.as_slice(),
                        mins,
                        maxes,
                        null_counts,
                    )?;

                    Ok(())
                }
                _ => {
                    unreachable!();
                }
            }
        }
        // column path parts will always have at least one element.
        (_, None) => {
            unreachable!();
        }
    }
}
