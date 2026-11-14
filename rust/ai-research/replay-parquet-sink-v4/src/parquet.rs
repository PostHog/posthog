//! Encodes v4 index rows into a zstd-compressed Parquet file with plain v2 pages.

use std::cmp::Ordering;
use std::sync::{Arc, LazyLock};

use parquet::basic::{
    Compression, ConvertedType, Encoding, Repetition, Type as PhysicalType, ZstdLevel,
};
use parquet::data_type::{BoolType, ByteArray, ByteArrayType, Int32Type, Int64Type};
use parquet::errors::Result;
use parquet::file::properties::{EnabledStatistics, WriterProperties, WriterVersion};
use parquet::file::writer::SerializedFileWriter;
use parquet::schema::types::{ColumnPath, Type, TypePtr};

use crate::columns::{Column, Index, LeafColumn, LeafType};
use crate::row::{Cell, Row};

const ZSTD_LEVEL: i32 = 9;

fn physical(leaf: LeafType) -> PhysicalType {
    match leaf {
        LeafType::Utf8 => PhysicalType::BYTE_ARRAY,
        LeafType::Boolean => PhysicalType::BOOLEAN,
        LeafType::Int32 => PhysicalType::INT32,
        LeafType::Int64 => PhysicalType::INT64,
    }
}

fn primitive(name: &str, leaf: LeafType, repetition: Repetition) -> Result<TypePtr> {
    let converted = match leaf {
        LeafType::Utf8 => ConvertedType::UTF8,
        _ => ConvertedType::NONE,
    };
    Ok(Arc::new(
        Type::primitive_type_builder(name, physical(leaf))
            .with_repetition(repetition)
            .with_converted_type(converted)
            .build()?,
    ))
}

fn group(
    name: &str,
    repetition: Repetition,
    converted: ConvertedType,
    fields: Vec<TypePtr>,
) -> Result<TypePtr> {
    Ok(Arc::new(
        Type::group_type_builder(name)
            .with_repetition(repetition)
            .with_converted_type(converted)
            .with_fields(fields)
            .build()?,
    ))
}

/// A list of structs and a nullable list use the 3-level LIST layout, because Athena reads a bare repeated group of
/// several fields as null.
fn column_type(column: &Column) -> Result<TypePtr> {
    match column {
        Column::Leaf(LeafColumn {
            name,
            leaf,
            optional,
            ..
        }) => {
            let repetition = if *optional {
                Repetition::OPTIONAL
            } else {
                Repetition::REQUIRED
            };
            primitive(name, *leaf, repetition)
        }
        Column::Repeated { name, fields } => {
            let leaves = fields
                .iter()
                .map(|field| primitive(field.name, field.leaf, Repetition::REQUIRED))
                .collect::<Result<Vec<_>>>()?;
            let element = group("element", Repetition::REQUIRED, ConvertedType::NONE, leaves)?;
            let list = group(
                "list",
                Repetition::REPEATED,
                ConvertedType::NONE,
                vec![element],
            )?;
            group(name, Repetition::REQUIRED, ConvertedType::LIST, vec![list])
        }
        Column::List { name, leaf } => primitive(name, *leaf, Repetition::REPEATED),
        Column::NullableList { name, leaf } => {
            let element = primitive("element", *leaf, Repetition::REQUIRED)?;
            let list = group(
                "list",
                Repetition::REPEATED,
                ConvertedType::NONE,
                vec![element],
            )?;
            group(name, Repetition::OPTIONAL, ConvertedType::LIST, vec![list])
        }
    }
}

pub fn schema(index: Index) -> Result<TypePtr> {
    let fields = index
        .columns()
        .iter()
        .map(column_type)
        .collect::<Result<Vec<_>>>()?;
    Ok(Arc::new(
        Type::group_type_builder("root")
            .with_fields(fields)
            .build()?,
    ))
}

fn properties(index: Index) -> Result<Arc<WriterProperties>> {
    let mut builder = WriterProperties::builder()
        .set_writer_version(WriterVersion::PARQUET_2_0)
        .set_compression(Compression::ZSTD(ZstdLevel::try_new(ZSTD_LEVEL)?))
        .set_dictionary_enabled(false)
        .set_encoding(Encoding::PLAIN);
    for column in index.columns() {
        if let Column::Leaf(LeafColumn {
            name, opaque: true, ..
        }) = column
        {
            builder = builder
                .set_column_statistics_enabled(ColumnPath::from(*name), EnabledStatistics::None);
        }
    }
    Ok(Arc::new(builder.build()))
}

#[derive(Debug, Clone, Copy)]
enum Leaf {
    Plain {
        column: usize,
        leaf: LeafType,
        optional: bool,
    },
    StructField {
        column: usize,
        field: usize,
        leaf: LeafType,
    },
    List {
        column: usize,
        leaf: LeafType,
    },
    NullableList {
        column: usize,
        leaf: LeafType,
    },
}

fn leaves(index: Index) -> Vec<Leaf> {
    let mut leaves = Vec::new();
    for (column, definition) in index.columns().iter().enumerate() {
        match definition {
            Column::Leaf(LeafColumn { leaf, optional, .. }) => leaves.push(Leaf::Plain {
                column,
                leaf: *leaf,
                optional: *optional,
            }),
            Column::Repeated { fields, .. } => {
                leaves.extend(fields.iter().enumerate().map(|(field, definition)| {
                    Leaf::StructField {
                        column,
                        field,
                        leaf: definition.leaf,
                    }
                }));
            }
            Column::List { leaf, .. } => leaves.push(Leaf::List {
                column,
                leaf: *leaf,
            }),
            Column::NullableList { leaf, .. } => leaves.push(Leaf::NullableList {
                column,
                leaf: *leaf,
            }),
        }
    }
    leaves
}

enum Values {
    Bool(Vec<bool>),
    Int32(Vec<i32>),
    Int64(Vec<i64>),
    Bytes(Vec<ByteArray>),
}

impl Values {
    fn new(leaf: LeafType) -> Self {
        match leaf {
            LeafType::Boolean => Self::Bool(Vec::new()),
            LeafType::Int32 => Self::Int32(Vec::new()),
            LeafType::Int64 => Self::Int64(Vec::new()),
            LeafType::Utf8 => Self::Bytes(Vec::new()),
        }
    }

    fn push(&mut self, cell: &Cell) {
        match (self, cell) {
            (Self::Bool(values), Cell::Bool(value)) => values.push(*value),
            (Self::Int32(values), Cell::Int32(value)) => values.push(*value),
            (Self::Int64(values), Cell::Int64(value)) => values.push(*value),
            (Self::Bytes(values), Cell::Utf8(value)) => {
                values.push(ByteArray::from(value.to_utf8().into_owned()))
            }
            // The row validator built every cell from its column's type.
            (_, cell) => unreachable!("a cell of the wrong type: {cell:?}"),
        }
    }
}

struct LeafData {
    values: Values,
    definition: Vec<i16>,
    repetition: Vec<i16>,
}

impl LeafData {
    /// Levels for the values of one row's list: one empty entry at `empty_level` for an empty list.
    fn push_list<'c>(
        &mut self,
        items: impl ExactSizeIterator<Item = &'c Cell>,
        present: i16,
        empty_level: i16,
    ) {
        if items.len() == 0 {
            self.definition.push(empty_level);
            self.repetition.push(0);
            return;
        }
        for (position, item) in items.enumerate() {
            self.values.push(item);
            self.definition.push(present);
            self.repetition.push(i16::from(position > 0));
        }
    }
}

fn leaf_data(leaf: Leaf, rows: &[&Row]) -> (LeafData, bool, bool) {
    let leaf_type = match leaf {
        Leaf::Plain { leaf, .. }
        | Leaf::StructField { leaf, .. }
        | Leaf::List { leaf, .. }
        | Leaf::NullableList { leaf, .. } => leaf,
    };
    let mut data = LeafData {
        values: Values::new(leaf_type),
        definition: Vec::new(),
        repetition: Vec::new(),
    };
    for row in rows {
        match leaf {
            Leaf::Plain {
                column, optional, ..
            } => match &row[column] {
                Cell::Null => data.definition.push(0),
                cell => {
                    data.values.push(cell);
                    if optional {
                        data.definition.push(1);
                    }
                }
            },
            Leaf::StructField { column, field, .. } => {
                let Cell::Structs(items) = &row[column] else {
                    unreachable!("a repeated column holds structs");
                };
                data.push_list(items.iter().map(|item| &item[field]), 1, 0);
            }
            Leaf::List { column, .. } => {
                let Cell::List(items) = &row[column] else {
                    unreachable!("a list column holds a list");
                };
                data.push_list(items.iter(), 1, 0);
            }
            Leaf::NullableList { column, .. } => match &row[column] {
                Cell::Null => {
                    data.definition.push(0);
                    data.repetition.push(0);
                }
                Cell::List(items) => data.push_list(items.iter(), 2, 1),
                cell => unreachable!("a nullable list column holds {cell:?}"),
            },
        }
    }
    let (has_definition, has_repetition) = match leaf {
        Leaf::Plain { optional, .. } => (optional, false),
        _ => (true, true),
    };
    (data, has_definition, has_repetition)
}

static SORT_COLUMNS: LazyLock<(usize, usize, usize)> = LazyLock::new(|| {
    let position = |name: &str| {
        Index::Blocks
            .columns()
            .iter()
            .position(|column| column.name() == name)
            .expect("a block index column")
    };
    (
        position("team_id"),
        position("session_id"),
        position("first_ts_ms"),
    )
});

fn compare_blocks(a: &Row, b: &Row) -> Ordering {
    let (team_id, session_id, first_ts_ms) = *SORT_COLUMNS;
    let int64 = |row: &Row, column: usize| match row[column] {
        Cell::Int64(value) => Some(value),
        _ => None,
    };
    let team = int64(a, team_id).cmp(&int64(b, team_id));
    let session = match (&a[session_id], &b[session_id]) {
        (Cell::Utf8(a), Cell::Utf8(b)) => a.cmp_utf16(b),
        _ => Ordering::Equal,
    };
    let first_ts = match (int64(a, first_ts_ms), int64(b, first_ts_ms)) {
        (Some(a), Some(b)) => a.cmp(&b),
        (None, None) => Ordering::Equal,
        (None, Some(_)) => Ordering::Greater,
        (Some(_), None) => Ordering::Less,
    };
    team.then(session).then(first_ts)
}

/// Puts a session's blocks next to each other, so its repeated session and window ids compress to almost nothing. The
/// sort is stable, so rows with equal keys keep their arrival order.
fn in_file_order<'r>(index: Index, rows: impl IntoIterator<Item = &'r Row>) -> Vec<&'r Row> {
    let mut rows: Vec<&Row> = rows.into_iter().collect();
    if index == Index::Blocks {
        rows.sort_by(|a, b| compare_blocks(a, b));
    }
    rows
}

pub fn encode<'r>(
    index: Index,
    rows: impl IntoIterator<Item = &'r Row>,
    row_group_rows: usize,
) -> Result<Vec<u8>> {
    let rows = in_file_order(index, rows);
    let leaves = leaves(index);
    let mut writer = SerializedFileWriter::new(Vec::new(), schema(index)?, properties(index)?)?;
    for group_rows in rows.chunks(row_group_rows.max(1)) {
        let mut group = writer.next_row_group()?;
        for leaf in &leaves {
            let (data, has_definition, has_repetition) = leaf_data(*leaf, group_rows);
            let definition = has_definition.then_some(data.definition.as_slice());
            let repetition = has_repetition.then_some(data.repetition.as_slice());
            let mut column = group
                .next_column()?
                .expect("the schema has a leaf for each planned column");
            match &data.values {
                Values::Bool(values) => column
                    .typed::<BoolType>()
                    .write_batch(values, definition, repetition)?,
                Values::Int32(values) => column
                    .typed::<Int32Type>()
                    .write_batch(values, definition, repetition)?,
                Values::Int64(values) => column
                    .typed::<Int64Type>()
                    .write_batch(values, definition, repetition)?,
                Values::Bytes(values) => column
                    .typed::<ByteArrayType>()
                    .write_batch(values, definition, repetition)?,
            };
            column.close()?;
        }
        group.close()?;
    }
    writer.into_inner()
}

#[cfg(test)]
mod tests {
    use ::parquet::basic::{Compression as Codec, ConvertedType as Converted};
    use ::parquet::file::reader::{FileReader, SerializedFileReader};
    use ::parquet::record::Field;
    use ::parquet::schema::types::Type as SchemaType;
    use serde_json::{json, Value};

    use super::*;
    use crate::row::{parse_index_message, Headers, INDEX_HEADER, WRITE_DAY_HEADER};
    use crate::testing::{block_row, image_row, read_rows};

    /// The v4 index contract, shared with the recorder's JSON rows: name, order, nullability and type of each column.
    const IMAGE_SCHEMA: &[&str] = &[
        "REQUIRED INT64 team_id",
        "REQUIRED BYTE_ARRAY key_month UTF8",
        "REQUIRED BYTE_ARRAY image_ref UTF8",
        "REQUIRED BYTE_ARRAY pack_s3_key UTF8",
        "REQUIRED INT64 byte_start",
        "REQUIRED INT64 byte_end",
        "REQUIRED BYTE_ARRAY mime UTF8",
        "REQUIRED INT64 byte_size",
    ];

    const BLOCK_SCHEMA: &[&str] = &[
        "REQUIRED INT64 team_id",
        "REQUIRED BYTE_ARRAY session_id UTF8",
        "REQUIRED BYTE_ARRAY key_month UTF8",
        "REQUIRED BYTE_ARRAY block_s3_key UTF8",
        "REQUIRED BYTE_ARRAY topic UTF8",
        "REQUIRED INT32 partition",
        "REQUIRED INT64 start_offset",
        "REQUIRED INT64 end_offset",
        "REQUIRED INT64 flush_end_offset",
        "REQUIRED INT32 flush_row_count",
        "REQUIRED INT32 flush_row_index",
        "REQUIRED BYTE_ARRAY flush_id UTF8",
        "REQUIRED INT64 flushed_at_ms",
        "REQUIRED INT64 block_byte_start",
        "REQUIRED INT64 block_byte_end",
        "OPTIONAL INT64 first_ts_ms",
        "OPTIONAL INT64 last_ts_ms",
        "REQUIRED INT64 event_count",
        "REQUIRED INT64 byte_size",
        "OPTIONAL BYTE_ARRAY snapshot_source UTF8",
        "OPTIONAL BYTE_ARRAY snapshot_library UTF8",
        "OPTIONAL BYTE_ARRAY host UTF8",
        "REQUIRED INT32 full_snapshots",
        "REQUIRED INT32 events_before_first_full_snapshot",
        "REQUIRED INT32 orphan_mutations",
        "REQUIRED INT32 decode_failures",
        "REQUIRED INT32 dom_nodes",
        "REQUIRED INT32 remote_stylesheets",
        "REQUIRED INT32 inline_stylesheets",
        "REQUIRED INT32 iframes",
        "REQUIRED INT32 canvases",
        "REQUIRED INT32 videos",
        "REQUIRED INT32 shadow_roots",
        "REQUIRED INT64 max_gap_ms",
        "REQUIRED INT64 active_ms",
        "REQUIRED INT64 dom_text_chars",
        "REQUIRED BOOLEAN cold_start",
        "REQUIRED BOOLEAN node_cap_reached",
        "REQUIRED BOOLEAN moments_truncated",
        "REQUIRED BOOLEAN touch_input",
        "REQUIRED INT32 clicks",
        "REQUIRED INT32 mouse_interactions",
        "REQUIRED INT32 rage_clicks",
        "REQUIRED INT32 dead_clicks",
        "REQUIRED INT32 keypresses",
        "REQUIRED INT32 scrolls",
        "REQUIRED INT32 mouse_moves",
        "REQUIRED INT32 touches",
        "REQUIRED INT32 touch_moves",
        "REQUIRED INT32 selections",
        "REQUIRED INT32 media_events",
        "REQUIRED INT32 viewport_resizes",
        "REQUIRED INT32 navigations",
        "REQUIRED INT32 console_errors",
        "REQUIRED INT32 console_warnings",
        "REQUIRED INT32 network_requests",
        "REQUIRED INT32 network_failures",
        "REQUIRED INT32 images_extracted",
        "REQUIRED INT32 images_inline",
        "REQUIRED INT32 image_urls",
        "REQUIRED INT64 image_bytes",
        "REQUIRED INT64 written_jsonl_bytes",
        "REQUIRED INT64 max_written_event_bytes",
        "OPTIONAL INT32 viewport_width",
        "OPTIONAL INT32 viewport_height",
        "OPTIONAL INT64 viewport_ts_ms",
        "REQUIRED group moments LIST",
        "REPEATED group moments.list",
        "REQUIRED group moments.list.element",
        "REQUIRED BYTE_ARRAY moments.list.element.kind UTF8",
        "REQUIRED BYTE_ARRAY moments.list.element.window_id UTF8",
        "REQUIRED INT64 moments.list.element.ts_ms",
        "REQUIRED INT32 moments.list.element.event_index",
        "REPEATED BYTE_ARRAY url_fingerprints UTF8",
        "REPEATED BYTE_ARRAY window_ids UTF8",
        "OPTIONAL BYTE_ARRAY urls UTF8",
        "REQUIRED BOOLEAN urls_truncated",
        "OPTIONAL INT32 surfacing_event_count",
        "OPTIONAL INT32 surfacing_click_count",
        "OPTIONAL INT32 surfacing_keypress_count",
        "OPTIONAL INT32 surfacing_mouse_activity_count",
        "OPTIONAL INT32 surfacing_rage_click_count",
        "OPTIONAL INT32 surfacing_dead_click_count",
        "OPTIONAL INT32 surfacing_quick_back_count",
        "OPTIONAL INT32 surfacing_page_visit_count",
        "OPTIONAL INT32 surfacing_text_selection_count",
        "OPTIONAL INT32 surfacing_scroll_event_count",
        "OPTIONAL INT32 surfacing_console_error_count",
        "OPTIONAL INT32 surfacing_console_error_after_click_count",
        "OPTIONAL INT32 surfacing_console_warn_count",
        "OPTIONAL INT32 surfacing_network_request_count",
        "OPTIONAL INT32 surfacing_network_failed_request_count",
        "OPTIONAL INT32 surfacing_network_4xx_count",
        "OPTIONAL INT32 surfacing_network_5xx_count",
        "OPTIONAL INT32 surfacing_network_request_duration_count",
        "OPTIONAL INT32 surfacing_mouse_position_count",
        "OPTIONAL INT32 surfacing_mouse_direction_change_count",
        "OPTIONAL INT32 surfacing_mouse_velocity_count",
        "OPTIONAL INT32 surfacing_scroll_direction_reversal_count",
        "OPTIONAL INT32 surfacing_rapid_scroll_reversal_count",
        "OPTIONAL INT32 surfacing_scroll_to_top_count",
        "OPTIONAL INT32 surfacing_inter_action_gap_count",
        "OPTIONAL INT32 surfacing_long_idle_gap_count",
        "OPTIONAL INT32 surfacing_backspace_count",
        "OPTIONAL INT32 surfacing_mutation_count",
        "OPTIONAL INT32 surfacing_viewport_resize_count",
        "OPTIONAL INT32 surfacing_touch_event_count",
        "OPTIONAL INT32 surfacing_selection_copy_count",
        "OPTIONAL INT32 surfacing_login_path_visit_count",
        "OPTIONAL INT32 surfacing_signup_path_visit_count",
        "OPTIONAL INT32 surfacing_checkout_path_visit_count",
        "OPTIONAL INT32 surfacing_cart_path_visit_count",
        "OPTIONAL INT32 surfacing_billing_path_visit_count",
        "OPTIONAL INT32 surfacing_settings_path_visit_count",
        "OPTIONAL INT32 surfacing_account_path_visit_count",
        "OPTIONAL INT32 surfacing_error_path_visit_count",
        "OPTIONAL INT32 surfacing_not_found_path_visit_count",
        "OPTIONAL INT32 surfacing_admin_path_visit_count",
        "OPTIONAL INT32 surfacing_dashboard_path_visit_count",
        "OPTIONAL INT32 surfacing_onboarding_path_visit_count",
        "OPTIONAL INT32 surfacing_cancel_path_visit_count",
        "OPTIONAL INT32 surfacing_refund_path_visit_count",
        "OPTIONAL INT64 surfacing_mouse_sum_x_millipx",
        "OPTIONAL INT64 surfacing_mouse_sum_x_squared_px2",
        "OPTIONAL INT64 surfacing_mouse_sum_y_millipx",
        "OPTIONAL INT64 surfacing_mouse_sum_y_squared_px2",
        "OPTIONAL INT64 surfacing_mouse_distance_traveled_millipx",
        "OPTIONAL INT64 surfacing_mouse_velocity_sum_px_per_s",
        "OPTIONAL INT64 surfacing_mouse_velocity_sum_of_squares_px2_per_s2",
        "OPTIONAL INT64 surfacing_total_scroll_magnitude_millipx",
        "OPTIONAL INT64 surfacing_inter_action_gap_sum_ms",
        "OPTIONAL INT64 surfacing_inter_action_gap_sum_of_squares_ms2",
        "OPTIONAL INT64 surfacing_network_request_duration_sum_us",
        "OPTIONAL INT64 surfacing_network_request_duration_sum_of_squares_ms2",
        "OPTIONAL INT64 surfacing_max_scroll_y_millipx",
        "OPTIONAL INT64 surfacing_max_idle_gap_ms",
        "OPTIONAL group surfacing_visited_url_fingerprints LIST",
        "REPEATED group surfacing_visited_url_fingerprints.list",
        "REQUIRED BYTE_ARRAY surfacing_visited_url_fingerprints.list.element UTF8",
        "OPTIONAL group surfacing_click_target_ids LIST",
        "REPEATED group surfacing_click_target_ids.list",
        "REQUIRED INT64 surfacing_click_target_ids.list.element",
        "OPTIONAL group surfacing_form_field_ids LIST",
        "REPEATED group surfacing_form_field_ids.list",
        "REQUIRED INT64 surfacing_form_field_ids.list.element",
        "OPTIONAL BYTE_ARRAY unread_reason UTF8",
    ];

    fn describe(schema: &SchemaType, path: &mut Vec<String>, out: &mut Vec<String>) {
        for field in schema.get_fields() {
            path.push(field.name().to_owned());
            let info = field.get_basic_info();
            let kind = if field.is_primitive() {
                format!("{}", field.get_physical_type())
            } else {
                "group".to_owned()
            };
            let mut line = format!("{} {kind} {}", info.repetition(), path.join("."));
            if info.converted_type() != Converted::NONE {
                line.push_str(&format!(" {}", info.converted_type()));
            }
            out.push(line);
            if !field.is_primitive() {
                describe(field, path, out);
            }
            path.pop();
        }
    }

    fn rows(index: Index, values: &[Value]) -> Vec<Row> {
        values
            .iter()
            .map(|value| {
                let headers = Headers::from_pairs([
                    (INDEX_HEADER, Some(index.as_str().as_bytes())),
                    (WRITE_DAY_HEADER, Some(b"2026-10-15".as_slice())),
                ]);
                parse_index_message(&headers, Some(&serde_json::to_vec(value).unwrap()))
                    .unwrap()
                    .row
            })
            .collect()
    }

    fn file(index: Index, values: &[Value], row_group_rows: usize) -> Vec<u8> {
        encode(index, rows(index, values).iter(), row_group_rows).unwrap()
    }

    fn get<'r>(row: &'r [(String, Field)], name: &str) -> &'r Field {
        &row.iter().find(|(column, _)| column == name).unwrap().1
    }

    #[test]
    fn writes_the_columns_of_the_v4_index_contract() {
        for (index, expected) in [(Index::Images, IMAGE_SCHEMA), (Index::Blocks, BLOCK_SCHEMA)] {
            let body = file(index, &[], 1_000);
            let reader = SerializedFileReader::new(bytes::Bytes::from(body)).unwrap();
            let mut lines = Vec::new();
            describe(
                reader.metadata().file_metadata().schema(),
                &mut Vec::new(),
                &mut lines,
            );
            assert_eq!(lines, expected, "{index:?}");
        }
    }

    #[test]
    fn reads_back_the_values_it_writes_in_row_groups_of_the_given_size_with_zstd_on_every_column() {
        let image = image_row("image:v4:7:2026-10:abc");
        let body = file(Index::Images, &vec![image; 5], 2);
        let reader = SerializedFileReader::new(bytes::Bytes::from(body.clone())).unwrap();
        let groups = reader.metadata().row_groups();
        assert_eq!(
            groups
                .iter()
                .map(|group| group.num_rows())
                .collect::<Vec<_>>(),
            [2, 2, 1]
        );
        for group in groups {
            assert!(group
                .columns()
                .iter()
                .all(|column| matches!(column.compression(), Codec::ZSTD(_))));
        }
        let row = &read_rows(&body)[4];
        assert_eq!(get(row, "team_id"), &Field::Long(7));
        assert_eq!(
            get(row, "image_ref"),
            &Field::Str("image:v4:7:2026-10:abc".to_owned())
        );
        assert_eq!(get(row, "byte_end"), &Field::Long(99));
    }

    #[test]
    fn writes_a_large_sealed_urls_value_with_no_copy_of_it_in_the_statistics() {
        // Random-looking base64, which zstd shrinks by about a quarter.
        let mut state = 7_u64;
        let urls: String = (0..768 * 1024 * 4 / 3)
            .map(|_| {
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                char::from(
                    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
                        [(state >> 58) as usize],
                )
            })
            .collect();
        let mut row = block_row("s1");
        row["urls"] = json!(urls);
        let body = file(Index::Blocks, &[row], 1_000);
        assert_eq!(get(&read_rows(&body)[0], "urls"), &Field::Str(urls.clone()));
        assert!(
            body.len() < urls.len() * 11 / 10,
            "{} vs {}",
            body.len(),
            urls.len()
        );
        let reader = SerializedFileReader::new(bytes::Bytes::from(body)).unwrap();
        let group = reader.metadata().row_group(0);
        let urls_column = group
            .columns()
            .iter()
            .find(|column| column.column_path().string() == "urls")
            .unwrap();
        assert!(urls_column.statistics().is_none());
    }

    #[test]
    fn writes_blocks_in_team_session_and_first_timestamp_order_with_a_null_first_timestamp_last() {
        let at = |team_id: i64, session_id: &str, first_ts_ms: Option<i64>| {
            let mut row = block_row(session_id);
            row["team_id"] = json!(team_id);
            row["first_ts_ms"] = json!(first_ts_ms);
            row
        };
        let arrival = [
            at(10, "a", Some(1)),
            at(2, "b", None),
            at(2, "b", Some(30)),
            at(2, "a", Some(5)),
            at(2, "b", Some(4)),
        ];
        let read: Vec<(Field, Field, Field)> = read_rows(&file(Index::Blocks, &arrival, 1_000))
            .iter()
            .map(|row| {
                (
                    get(row, "team_id").clone(),
                    get(row, "session_id").clone(),
                    get(row, "first_ts_ms").clone(),
                )
            })
            .collect();
        let expected = [
            (2, "a", Some(5)),
            (2, "b", Some(4)),
            (2, "b", Some(30)),
            (2, "b", None),
            (10, "a", Some(1)),
        ]
        .map(|(team, session, ts)| {
            (
                Field::Long(team),
                Field::Str(session.to_owned()),
                ts.map_or(Field::Null, Field::Long),
            )
        });
        assert_eq!(read, expected);
    }

    fn list_of(field: &Field) -> Option<Vec<Field>> {
        match field {
            Field::Null => None,
            Field::ListInternal(list) => Some(list.elements().to_vec()),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn reads_the_surfacing_lists_back_as_lists_and_a_row_without_them_as_null() {
        let mut with = block_row("s1");
        with["surfacing_click_count"] = json!(3);
        with["surfacing_mouse_sum_x_millipx"] = json!(-(2_i64.pow(53) - 1));
        with["surfacing_visited_url_fingerprints"] =
            json!(["0f1e2d3c4b5a6978", "b08517cee3ff5ecc"]);
        with["surfacing_click_target_ids"] = json!([-1, 2_i64.pow(53) - 1]);
        with["surfacing_form_field_ids"] = json!([]);
        let mut without = block_row("s2");
        for name in [
            "surfacing_visited_url_fingerprints",
            "surfacing_click_target_ids",
            "surfacing_form_field_ids",
        ] {
            without[name] = Value::Null;
        }
        let read = read_rows(&file(Index::Blocks, &[with, without], 1_000));
        assert_eq!(get(&read[0], "surfacing_click_count"), &Field::Int(3));
        assert_eq!(
            get(&read[0], "surfacing_mouse_sum_x_millipx"),
            &Field::Long(-(2_i64.pow(53) - 1))
        );
        assert_eq!(
            list_of(get(&read[0], "surfacing_visited_url_fingerprints")),
            Some(vec![
                Field::Str("0f1e2d3c4b5a6978".to_owned()),
                Field::Str("b08517cee3ff5ecc".to_owned())
            ])
        );
        assert_eq!(
            list_of(get(&read[0], "surfacing_click_target_ids")),
            Some(vec![Field::Long(-1), Field::Long(2_i64.pow(53) - 1)])
        );
        assert_eq!(
            list_of(get(&read[0], "surfacing_form_field_ids")),
            Some(vec![])
        );
        for name in [
            "surfacing_click_count",
            "surfacing_visited_url_fingerprints",
            "surfacing_click_target_ids",
            "surfacing_form_field_ids",
        ] {
            assert_eq!(get(&read[1], name), &Field::Null, "{name}");
        }
    }

    #[test]
    fn reads_moments_back_as_a_list_of_structs_and_the_string_lists_as_lists() {
        let moments = json!([
            {"kind": "click", "window_id": "w1", "ts_ms": 1_000, "event_index": 2_i64.pow(31) - 1},
            {"kind": "full_snapshot_undecoded", "window_id": "w2", "ts_ms": 2_000, "event_index": 0},
        ]);
        let mut first = block_row("s1");
        first["moments"] = moments;
        first["url_fingerprints"] = json!(["w1", "w2"]);
        first["window_ids"] = json!(["w1", "w2"]);
        let mut empty = block_row("s2");
        for name in ["moments", "url_fingerprints", "window_ids"] {
            empty[name] = json!([]);
        }
        let read = read_rows(&file(Index::Blocks, &[first, empty], 1_000));
        let structs: Vec<Vec<(String, Field)>> = list_of(get(&read[0], "moments"))
            .unwrap()
            .into_iter()
            .map(|item| match item {
                Field::Group(group) => group
                    .get_column_iter()
                    .map(|(n, f)| (n.clone(), f.clone()))
                    .collect(),
                other => panic!("{other:?}"),
            })
            .collect();
        assert_eq!(
            structs[0],
            [
                ("kind".to_owned(), Field::Str("click".to_owned())),
                ("window_id".to_owned(), Field::Str("w1".to_owned())),
                ("ts_ms".to_owned(), Field::Long(1_000)),
                ("event_index".to_owned(), Field::Int(i32::MAX)),
            ]
        );
        assert_eq!(
            get(&structs[1], "kind"),
            &Field::Str("full_snapshot_undecoded".to_owned())
        );
        let strings = |field: &Field| list_of(field).unwrap();
        assert_eq!(
            strings(get(&read[0], "window_ids")),
            [Field::Str("w1".to_owned()), Field::Str("w2".to_owned())]
        );
        for name in ["moments", "url_fingerprints", "window_ids"] {
            assert_eq!(list_of(get(&read[1], name)), Some(vec![]), "{name}");
        }
    }
}
