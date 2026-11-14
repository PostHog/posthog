//! The columns of the two v4 index files, in file order. This table drives the row validator and the Parquet writer.
//! The recorder's `index.rs` writes the JSON rows that these columns read, and its tests list the same columns.

use std::sync::LazyLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Index {
    Blocks,
    Images,
}

impl Index {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "blocks" => Some(Self::Blocks),
            "images" => Some(Self::Images),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Blocks => "blocks",
            Self::Images => "images",
        }
    }

    pub fn columns(self) -> &'static [Column] {
        match self {
            Self::Blocks => &BLOCK_COLUMNS,
            Self::Images => &IMAGE_COLUMNS,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeafType {
    Utf8,
    Boolean,
    Int32,
    Int64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeafColumn {
    pub name: &'static str,
    pub leaf: LeafType,
    pub optional: bool,
    /// Sealed bytes with no useful order. Min and max statistics would copy each long value into the file metadata.
    pub opaque: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Column {
    Leaf(LeafColumn),
    Repeated {
        name: &'static str,
        fields: &'static [LeafColumn],
    },
    /// A repeated leaf. Parquet readers see it as a non-null list of non-null values.
    List {
        name: &'static str,
        leaf: LeafType,
    },
    NullableList {
        name: &'static str,
        leaf: LeafType,
    },
}

impl Column {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Leaf(leaf) => leaf.name,
            Self::Repeated { name, .. }
            | Self::List { name, .. }
            | Self::NullableList { name, .. } => name,
        }
    }
}

const fn leaf(name: &'static str, leaf: LeafType, optional: bool) -> LeafColumn {
    LeafColumn {
        name,
        leaf,
        optional,
        opaque: false,
    }
}

fn required(leaf_type: LeafType, names: &[&'static str]) -> Vec<Column> {
    names
        .iter()
        .map(|name| Column::Leaf(leaf(name, leaf_type, false)))
        .collect()
}

fn optional(leaf_type: LeafType, names: &[&'static str]) -> Vec<Column> {
    names
        .iter()
        .map(|name| Column::Leaf(leaf(name, leaf_type, true)))
        .collect()
}

use LeafType::{Boolean, Int32, Int64, Utf8};

pub static MOMENT_COLUMNS: [LeafColumn; 4] = [
    leaf("kind", Utf8, false),
    leaf("window_id", Utf8, false),
    leaf("ts_ms", Int64, false),
    leaf("event_index", Int32, false),
];

pub static IMAGE_COLUMNS: LazyLock<Vec<Column>> = LazyLock::new(|| {
    [
        required(Int64, &["team_id"]),
        required(Utf8, &["key_month", "image_ref", "pack_s3_key"]),
        required(Int64, &["byte_start", "byte_end"]),
        required(Utf8, &["mime"]),
        required(Int64, &["byte_size"]),
    ]
    .concat()
});

pub static BLOCK_COLUMNS: LazyLock<Vec<Column>> = LazyLock::new(|| {
    [
        required(Int64, &["team_id"]),
        required(Utf8, &["session_id", "key_month", "block_s3_key", "topic"]),
        required(Int32, &["partition"]),
        required(Int64, &["start_offset", "end_offset", "flush_end_offset"]),
        required(Int32, &["flush_row_count", "flush_row_index"]),
        required(Utf8, &["flush_id"]),
        required(
            Int64,
            &["flushed_at_ms", "block_byte_start", "block_byte_end"],
        ),
        optional(Int64, &["first_ts_ms", "last_ts_ms"]),
        required(Int64, &["event_count", "byte_size"]),
        optional(Utf8, &["snapshot_source", "snapshot_library", "host"]),
        required(
            Int32,
            &[
                "full_snapshots",
                "events_before_first_full_snapshot",
                "orphan_mutations",
                "decode_failures",
                "dom_nodes",
                "remote_stylesheets",
                "inline_stylesheets",
                "iframes",
                "canvases",
                "videos",
                "shadow_roots",
            ],
        ),
        required(Int64, &["max_gap_ms", "active_ms", "dom_text_chars"]),
        required(
            Boolean,
            &[
                "cold_start",
                "node_cap_reached",
                "moments_truncated",
                "touch_input",
            ],
        ),
        required(
            Int32,
            &[
                "clicks",
                "mouse_interactions",
                "rage_clicks",
                "dead_clicks",
                "keypresses",
                "scrolls",
                "mouse_moves",
                "touches",
                "touch_moves",
                "selections",
                "media_events",
                "viewport_resizes",
                "navigations",
                "console_errors",
                "console_warnings",
                "network_requests",
                "network_failures",
                "images_extracted",
                "images_inline",
                "image_urls",
            ],
        ),
        required(
            Int64,
            &[
                "image_bytes",
                "written_jsonl_bytes",
                "max_written_event_bytes",
            ],
        ),
        optional(Int32, &["viewport_width", "viewport_height"]),
        optional(Int64, &["viewport_ts_ms"]),
        vec![
            Column::Repeated {
                name: "moments",
                fields: &MOMENT_COLUMNS,
            },
            Column::List {
                name: "url_fingerprints",
                leaf: Utf8,
            },
            Column::List {
                name: "window_ids",
                leaf: Utf8,
            },
            Column::Leaf(LeafColumn {
                name: "urls",
                leaf: Utf8,
                optional: true,
                opaque: true,
            }),
        ],
        required(Boolean, &["urls_truncated"]),
        // A recorder from before the surfacing columns sends rows without them, so they are nullable.
        optional(
            Int32,
            &[
                "surfacing_event_count",
                "surfacing_click_count",
                "surfacing_keypress_count",
                "surfacing_mouse_activity_count",
                "surfacing_rage_click_count",
                "surfacing_dead_click_count",
                "surfacing_quick_back_count",
                "surfacing_page_visit_count",
                "surfacing_text_selection_count",
                "surfacing_scroll_event_count",
                "surfacing_console_error_count",
                "surfacing_console_error_after_click_count",
                "surfacing_console_warn_count",
                "surfacing_network_request_count",
                "surfacing_network_failed_request_count",
                "surfacing_network_4xx_count",
                "surfacing_network_5xx_count",
                "surfacing_network_request_duration_count",
                "surfacing_mouse_position_count",
                "surfacing_mouse_direction_change_count",
                "surfacing_mouse_velocity_count",
                "surfacing_scroll_direction_reversal_count",
                "surfacing_rapid_scroll_reversal_count",
                "surfacing_scroll_to_top_count",
                "surfacing_inter_action_gap_count",
                "surfacing_long_idle_gap_count",
                "surfacing_backspace_count",
                "surfacing_mutation_count",
                "surfacing_viewport_resize_count",
                "surfacing_touch_event_count",
                "surfacing_selection_copy_count",
                "surfacing_login_path_visit_count",
                "surfacing_signup_path_visit_count",
                "surfacing_checkout_path_visit_count",
                "surfacing_cart_path_visit_count",
                "surfacing_billing_path_visit_count",
                "surfacing_settings_path_visit_count",
                "surfacing_account_path_visit_count",
                "surfacing_error_path_visit_count",
                "surfacing_not_found_path_visit_count",
                "surfacing_admin_path_visit_count",
                "surfacing_dashboard_path_visit_count",
                "surfacing_onboarding_path_visit_count",
                "surfacing_cancel_path_visit_count",
                "surfacing_refund_path_visit_count",
            ],
        ),
        optional(
            Int64,
            &[
                "surfacing_mouse_sum_x_millipx",
                "surfacing_mouse_sum_x_squared_px2",
                "surfacing_mouse_sum_y_millipx",
                "surfacing_mouse_sum_y_squared_px2",
                "surfacing_mouse_distance_traveled_millipx",
                "surfacing_mouse_velocity_sum_px_per_s",
                "surfacing_mouse_velocity_sum_of_squares_px2_per_s2",
                "surfacing_total_scroll_magnitude_millipx",
                "surfacing_inter_action_gap_sum_ms",
                "surfacing_inter_action_gap_sum_of_squares_ms2",
                "surfacing_network_request_duration_sum_us",
                "surfacing_network_request_duration_sum_of_squares_ms2",
                "surfacing_max_scroll_y_millipx",
                "surfacing_max_idle_gap_ms",
            ],
        ),
        vec![
            Column::NullableList {
                name: "surfacing_visited_url_fingerprints",
                leaf: Utf8,
            },
            Column::NullableList {
                name: "surfacing_click_target_ids",
                leaf: Int64,
            },
            Column::NullableList {
                name: "surfacing_form_field_ids",
                leaf: Int64,
            },
        ],
        optional(Utf8, &["unread_reason"]),
    ]
    .concat()
});
