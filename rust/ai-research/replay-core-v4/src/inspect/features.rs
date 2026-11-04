//! The values of ingestion's surfacing feature recorder (`session-feature-recorder.ts`), one block at a time.
//!
//! Ingestion records them per batch and the surfacing sweep merges a session's batch rows. The recorder starts fresh at
//! each block, as ingestion's does at each batch, so a block row holds what one batch row of `session_replay_features`
//! holds, and a session's values are the fold of its block rows: [`SurfacingFeatures::merge`].

use std::borrow::Cow;
use std::collections::{HashMap, HashSet};

use crate::bytescan::{self as scan, Span};
use crate::scan::message::Event;

use super::clicks::{ClickKind, ClickTracker};
use super::events::{href_from, number, text, DataFields, NetworkRequest};
use super::rrweb::*;

/// `MAX_UNIQUE_VALUES`: the values each set of a block keeps, and the input fields it remembers for backspaces.
pub const MAX_UNIQUE_VALUES: usize = 1000;

/// `PATH_TOKEN_ALLOWLIST` in its order, each with the name its count has in `session_replay_features`.
pub const PATH_TOKENS: [(&str, &str); 14] = [
    ("login", "login"),
    ("signup", "signup"),
    ("checkout", "checkout"),
    ("cart", "cart"),
    ("billing", "billing"),
    ("settings", "settings"),
    ("account", "account"),
    ("error", "error"),
    ("404", "not_found"),
    ("admin", "admin"),
    ("dashboard", "dashboard"),
    ("onboarding", "onboarding"),
    ("cancel", "cancel"),
    ("refund", "refund"),
];

const LONG_IDLE_GAP_MS: f64 = 30_000.0;
const SELECTION_COPY_WINDOW_MS: f64 = 2_000.0;
const QUICK_BACK_WINDOW_MS: f64 = 2_000.0;
const RAPID_SCROLL_REVERSAL_MS: f64 = 500.0;
const ERROR_AFTER_ACTION_MS: f64 = 5_000.0;

/// The largest node ID a set keeps. Past it a JavaScript number does not hold every integer, and the index refuses it.
const MAX_NODE_ID: f64 = 9_007_199_254_740_991.0;

/// One block's values as `SessionFeatureRecorder.end()` returns them for a batch. Float sums keep the exact values the
/// TypeScript computes, in the same order of operations.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct BlockFeatures {
    pub event_count: u64,
    pub mouse_position_count: u64,
    pub mouse_sum_x: f64,
    pub mouse_sum_x_squared: f64,
    pub mouse_sum_y: f64,
    pub mouse_sum_y_squared: f64,
    pub mouse_distance_traveled: f64,
    pub mouse_direction_change_count: u64,
    pub mouse_velocity_sum: f64,
    pub mouse_velocity_sum_of_squares: f64,
    pub mouse_velocity_count: u64,
    pub scroll_event_count: u64,
    pub total_scroll_magnitude: f64,
    pub scroll_direction_reversal_count: u64,
    pub rapid_scroll_reversal_count: u64,
    pub scroll_to_top_count: u64,
    pub click_count: u64,
    pub keypress_count: u64,
    pub mouse_activity_count: u64,
    pub rage_click_count: u64,
    pub dead_click_count: u64,
    pub backspace_count: u64,
    pub inter_action_gap_count: u64,
    pub inter_action_gap_sum_ms: f64,
    pub inter_action_gap_sum_of_squares_ms: f64,
    pub max_idle_gap_ms: f64,
    pub long_idle_gap_count: u64,
    pub quick_back_count: u64,
    pub page_visit_count: u64,
    /// The distinct page URLs in plaintext, sorted. The writer stores them as fingerprints under the session key, where
    /// ingestion stores their md5.
    pub visited_urls: Vec<String>,
    pub path_token_counts: [u64; PATH_TOKENS.len()],
    pub console_error_count: u64,
    pub console_error_after_click_count: u64,
    pub console_warn_count: u64,
    pub network_request_count: u64,
    pub network_failed_request_count: u64,
    pub network_4xx_count: u64,
    pub network_5xx_count: u64,
    pub network_request_duration_sum: f64,
    pub network_request_duration_sum_of_squares: f64,
    pub network_request_duration_count: u64,
    pub mutation_count: u64,
    pub viewport_resize_count: u64,
    pub touch_event_count: u64,
    pub max_scroll_y: f64,
    /// Sorted.
    pub click_target_ids: Vec<i64>,
    /// Sorted.
    pub form_field_ids: Vec<i64>,
    pub text_selection_count: u64,
    pub selection_copy_count: u64,
}

/// What the recorder knows about the block so far. It never outlives the block.
#[derive(Default)]
pub struct FeatureRecorder {
    values: BlockFeatures,
    visited_urls: HashSet<String>,
    click_target_ids: HashSet<i64>,
    form_field_ids: HashSet<i64>,
    /// The last text length of each input, by the bits of its ID, for the backspace count.
    input_text_lengths: HashMap<u64, usize>,
    last_mouse: Option<MousePosition>,
    last_mouse_delta: Option<(f64, f64)>,
    scroll: ScrollState,
    clicks: ClickTracker,
    /// The last click or keypress.
    last_action_ts: Option<f64>,
    last_navigation_ts: Option<f64>,
    /// Valid while `last_navigation_ts` is set. Reused, so that a navigation allocates only for a new page.
    last_navigation_url: String,
    /// The path tokens of `last_navigation_url`, one bit per token, so that the same page is parsed once.
    last_navigation_tokens: u16,
    last_selection_ts: Option<f64>,
}

#[derive(Clone, Copy)]
struct MousePosition {
    x: f64,
    y: f64,
    ts: f64,
}

#[derive(Default)]
struct ScrollState {
    last_up: Option<bool>,
    last_ts: Option<f64>,
    last_y: Option<f64>,
    /// `lastScrollId`: JavaScript `null` or a node ID.
    last_id: Option<f64>,
}

impl FeatureRecorder {
    /// Records one event of the block, apart from the requests of an `rrweb/network@1` event, which reach
    /// [`FeatureRecorder::track_network_request`]. Returns whether the event counts: ingestion's parse step drops an
    /// event without a positive timestamp before its recorder sees it, so such an event changes nothing here.
    pub fn observe(&mut self, inner: &[u8], event: &Event, data: &DataFields) -> bool {
        let Some(ts) = event.timestamp_ms.filter(|&ts| ts > 0.0) else {
            return false;
        };
        self.values.event_count += 1;
        let source = event
            .source
            .filter(|_| event.kind == Some(INCREMENTAL_SNAPSHOT));
        let interaction = number(inner, data.interaction);
        let is_click = source == Some(MOUSE_INTERACTION)
            && interaction.is_some_and(|t| {
                [CLICK, DOUBLE_CLICK, TOUCH_END, CONTEXT_MENU]
                    .map(f64::from)
                    .contains(&t)
            });
        let is_keypress = source == Some(INPUT);

        // The order of `aggregateFeatures`: a click reads the navigation state before a navigation on the same event
        // sets it.
        match source {
            Some(MOUSE_MOVE) => self.track_mouse_positions(inner, ts, event.positions_start),
            Some(SCROLL) => self.track_scroll(inner, ts, data),
            _ => {}
        }
        if is_click {
            self.track_click(inner, ts, data);
        }
        if is_keypress {
            self.track_keypress(inner, ts, data);
        }
        if is_click || is_keypress {
            self.track_inter_action_gap(ts);
        }
        if let Some(href) = href_from(inner, event.kind, data) {
            self.track_navigation(ts, &href);
        }
        if event.kind == Some(PLUGIN) {
            self.track_plugin(inner, ts, data);
        }
        let values = &mut self.values;
        match source {
            Some(SELECTION) => {
                values.text_selection_count += 1;
                self.last_selection_ts = Some(ts);
            }
            Some(MUTATION) => values.mutation_count += 1,
            Some(VIEWPORT_RESIZE) => values.viewport_resize_count += 1,
            _ => {}
        }
        let touch_interaction =
            interaction.is_some_and(|t| [TOUCH_START, TOUCH_END].map(f64::from).contains(&t));
        if source == Some(TOUCH_MOVE) || (source == Some(MOUSE_INTERACTION) && touch_interaction) {
            values.touch_event_count += 1;
        }
        if matches!(source, Some(MOUSE_INTERACTION | MOUSE_MOVE | TOUCH_MOVE)) {
            values.mouse_activity_count += 1;
        }
        true
    }

    fn track_mouse_positions(&mut self, inner: &[u8], ts: f64, positions: Option<u32>) {
        let Some(items) = positions.and_then(|start| {
            scan::array_object_fields(inner, start as usize, [b"x", b"y", b"timeOffset"]).ok()
        }) else {
            return;
        };
        for [x, y, offset] in items.map_while(Result::ok) {
            // The TypeScript skips a falsy item, and turns its sums into NaN on an item without coordinates.
            let (Some(x), Some(y)) = (number(inner, x), number(inner, y)) else {
                continue;
            };
            let ts = ts + number(inner, offset).unwrap_or(0.0);
            let values = &mut self.values;
            values.mouse_position_count += 1;
            values.mouse_sum_x += x;
            values.mouse_sum_x_squared += x * x;
            values.mouse_sum_y += y;
            values.mouse_sum_y_squared += y * y;
            if let Some(last) = self.last_mouse {
                let (dx, dy) = (x - last.x, y - last.y);
                let distance = (dx * dx + dy * dy).sqrt();
                values.mouse_distance_traveled += distance;
                if let Some((last_dx, last_dy)) = self.last_mouse_delta {
                    if dx * last_dx + dy * last_dy < 0.0 {
                        values.mouse_direction_change_count += 1;
                    }
                }
                self.last_mouse_delta = Some((dx, dy));
                let dt = ts - last.ts;
                if dt > 0.0 {
                    let velocity = distance / dt;
                    values.mouse_velocity_sum += velocity;
                    values.mouse_velocity_sum_of_squares += velocity * velocity;
                    values.mouse_velocity_count += 1;
                }
            }
            self.last_mouse = Some(MousePosition { x, y, ts });
        }
    }

    fn track_scroll(&mut self, inner: &[u8], ts: f64, data: &DataFields) {
        let values = &mut self.values;
        values.scroll_event_count += 1;
        let Some(y) = number(inner, data.y) else {
            return;
        };
        if y > values.max_scroll_y {
            values.max_scroll_y = y;
        }
        // `scrollId !== this.lastScrollId`: a missing ID never equals the last one, so it resets every time.
        let id = match data.id {
            None => None,
            Some(id) if scan::is_null(inner, id) => Some(None),
            Some(id) => number(inner, Some(id)).map(Some),
        };
        let scroll = &mut self.scroll;
        if id.is_none_or(|id| id != scroll.last_id) {
            scroll.last_y = None;
            scroll.last_up = None;
            scroll.last_id = id.flatten();
        }
        let Some(last_y) = scroll.last_y else {
            scroll.last_y = Some(y);
            scroll.last_ts = Some(ts);
            return;
        };
        let delta = y - last_y;
        values.total_scroll_magnitude += delta.abs();
        if last_y > 0.0 && y == 0.0 {
            values.scroll_to_top_count += 1;
        }
        if delta != 0.0 {
            let up = delta < 0.0;
            if scroll.last_up.is_some_and(|last_up| last_up != up) {
                values.scroll_direction_reversal_count += 1;
                if scroll
                    .last_ts
                    .is_some_and(|last_ts| ts - last_ts < RAPID_SCROLL_REVERSAL_MS)
                {
                    values.rapid_scroll_reversal_count += 1;
                }
            }
            scroll.last_up = Some(up);
        }
        scroll.last_y = Some(y);
        scroll.last_ts = Some(ts);
    }

    fn track_click(&mut self, inner: &[u8], ts: f64, data: &DataFields) {
        self.values.click_count += 1;
        if let Some(id) = node_id(inner, data.id) {
            if self.click_target_ids.len() < MAX_UNIQUE_VALUES {
                self.click_target_ids.insert(id);
            }
        }
        let position = number(inner, data.x).zip(number(inner, data.y));
        match self.clicks.click(ts, position) {
            ClickKind::Rage => self.values.rage_click_count += 1,
            ClickKind::AfterDead => self.values.dead_click_count += 1,
            ClickKind::Plain => {}
        }
    }

    fn track_keypress(&mut self, inner: &[u8], ts: f64, data: &DataFields) {
        self.values.keypress_count += 1;
        if let Some(id) = number(inner, data.id) {
            if let Some(id) = node_id(inner, data.id) {
                if self.form_field_ids.len() < MAX_UNIQUE_VALUES {
                    self.form_field_ids.insert(id);
                }
            }
            if let Some(length) = data.text.and_then(|text| utf16_length(inner, text)) {
                // A JavaScript `Map` holds 0 and -0 as one key.
                let key = (id + 0.0).to_bits();
                let previous = self.input_text_lengths.get(&key).copied();
                if let Some(previous) = previous.filter(|&previous| length < previous) {
                    self.values.backspace_count += (previous - length) as u64;
                }
                if previous.is_some() || self.input_text_lengths.len() < MAX_UNIQUE_VALUES {
                    self.input_text_lengths.insert(key, length);
                }
            }
        }
        if self
            .last_selection_ts
            .is_some_and(|selected| ts - selected <= SELECTION_COPY_WINDOW_MS)
        {
            self.values.selection_copy_count += 1;
            self.last_selection_ts = None;
        }
    }

    fn track_inter_action_gap(&mut self, ts: f64) {
        if let Some(last) = self.last_action_ts {
            let gap = ts - last;
            if gap > 0.0 {
                let values = &mut self.values;
                values.inter_action_gap_count += 1;
                values.inter_action_gap_sum_ms += gap;
                values.inter_action_gap_sum_of_squares_ms += gap * gap;
                if gap > values.max_idle_gap_ms {
                    values.max_idle_gap_ms = gap;
                }
                if gap > LONG_IDLE_GAP_MS {
                    values.long_idle_gap_count += 1;
                }
            }
        }
        self.last_action_ts = Some(ts);
    }

    fn track_navigation(&mut self, ts: f64, url: &str) {
        self.values.page_visit_count += 1;
        if self.visited_urls.len() < MAX_UNIQUE_VALUES && !self.visited_urls.contains(url) {
            self.visited_urls.insert(url.to_owned());
        }
        self.clicks.navigated();
        let same_page = self.last_navigation_ts.is_some() && self.last_navigation_url == url;
        let tokens = if same_page {
            self.last_navigation_tokens
        } else {
            path_tokens(url)
        };
        for (index, count) in self.values.path_token_counts.iter_mut().enumerate() {
            if tokens & (1 << index) != 0 {
                *count += 1;
            }
        }
        if self
            .last_navigation_ts
            .is_some_and(|last| ts - last < QUICK_BACK_WINDOW_MS)
            && !same_page
        {
            self.values.quick_back_count += 1;
        }
        if !same_page {
            self.last_navigation_url.clear();
            self.last_navigation_url.push_str(url);
            self.last_navigation_tokens = tokens;
        }
        self.last_navigation_ts = Some(ts);
    }

    fn track_plugin(&mut self, inner: &[u8], ts: f64, data: &DataFields) {
        let Some(plugin) = text(inner, data.plugin) else {
            return;
        };
        match &*plugin {
            "rrweb/console@1" => match text(inner, data.level).as_deref() {
                Some("error") => {
                    self.values.console_error_count += 1;
                    if self
                        .last_action_ts
                        .is_some_and(|last| (0.0..ERROR_AFTER_ACTION_MS).contains(&(ts - last)))
                    {
                        self.values.console_error_after_click_count += 1;
                    }
                }
                Some("warn") => self.values.console_warn_count += 1,
                _ => {}
            },
            // `if (!payload) return`, then `payload[39]` and `payload[21]`.
            "posthog/network@1" => {
                if data.payload.is_some_and(|p| js_truthy(inner, p)) {
                    self.track_network_request(NetworkRequest {
                        duration: number(inner, data.network_duration),
                        status: number(inner, data.network_status),
                    });
                }
            }
            _ => {}
        }
    }

    /// Records one request of an `rrweb/network@1` event. The inspector reads an event's requests in one pass for this
    /// and the event counter.
    pub fn track_network_request(&mut self, request: NetworkRequest) {
        let NetworkRequest { duration, status } = request;
        let values = &mut self.values;
        values.network_request_count += 1;
        if let Some(status) = status {
            if (400.0..500.0).contains(&status) {
                values.network_4xx_count += 1;
                values.network_failed_request_count += 1;
            } else if (500.0..600.0).contains(&status) {
                values.network_5xx_count += 1;
                values.network_failed_request_count += 1;
            } else if status >= 600.0 {
                values.network_failed_request_count += 1;
            }
        }
        if let Some(duration) = duration.filter(|&d| d > 0.0) {
            values.network_request_duration_sum += duration;
            values.network_request_duration_sum_of_squares += duration * duration;
            values.network_request_duration_count += 1;
        }
    }

    pub fn finish(self) -> BlockFeatures {
        fn sorted<T: Ord>(values: HashSet<T>) -> Vec<T> {
            let mut values: Vec<T> = values.into_iter().collect();
            values.sort_unstable();
            values
        }
        BlockFeatures {
            visited_urls: sorted(self.visited_urls),
            click_target_ids: sorted(self.click_target_ids),
            form_field_ids: sorted(self.form_field_ids),
            ..self.values
        }
    }
}

/// The surfacing values of a block as the index stores them, or of a session as [`SurfacingFeatures::merge`] folds
/// them. Each float sum of [`BlockFeatures`] is an integer in the unit its name gives, rounded once per block, so that
/// the fold is exact and does not depend on the order of the blocks.
#[derive(Debug, Clone, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct SurfacingFeatures {
    pub event_count: u64,
    pub click_count: u64,
    pub keypress_count: u64,
    pub mouse_activity_count: u64,
    pub rage_click_count: u64,
    pub dead_click_count: u64,
    pub quick_back_count: u64,
    pub page_visit_count: u64,
    pub text_selection_count: u64,
    pub scroll_event_count: u64,
    pub console_error_count: u64,
    pub console_error_after_click_count: u64,
    pub console_warn_count: u64,
    pub network_request_count: u64,
    pub network_failed_request_count: u64,
    pub network_4xx_count: u64,
    pub network_5xx_count: u64,
    pub network_request_duration_count: u64,
    pub mouse_position_count: u64,
    pub mouse_direction_change_count: u64,
    pub mouse_velocity_count: u64,
    pub scroll_direction_reversal_count: u64,
    pub rapid_scroll_reversal_count: u64,
    pub scroll_to_top_count: u64,
    pub inter_action_gap_count: u64,
    pub long_idle_gap_count: u64,
    pub backspace_count: u64,
    pub mutation_count: u64,
    pub viewport_resize_count: u64,
    pub touch_event_count: u64,
    pub selection_copy_count: u64,
    /// In [`PATH_TOKENS`] order.
    pub path_visit_counts: [u64; PATH_TOKENS.len()],

    pub mouse_sum_x_millipx: i64,
    pub mouse_sum_x_squared_px2: i64,
    pub mouse_sum_y_millipx: i64,
    pub mouse_sum_y_squared_px2: i64,
    pub mouse_distance_traveled_millipx: i64,
    pub mouse_velocity_sum_px_per_s: i64,
    pub mouse_velocity_sum_of_squares_px2_per_s2: i64,
    pub total_scroll_magnitude_millipx: i64,
    pub inter_action_gap_sum_ms: i64,
    pub inter_action_gap_sum_of_squares_ms2: i64,
    pub network_request_duration_sum_us: i64,
    pub network_request_duration_sum_of_squares_ms2: i64,

    pub max_scroll_y_millipx: i64,
    pub max_idle_gap_ms: i64,

    /// The distinct page URLs as [`crate::refs::url_fingerprint`]s under the session's fingerprint key, sorted. The
    /// inspector leaves this empty: the writer fills it, because only the writer holds the session key.
    pub visited_url_fingerprints: Vec<String>,
    /// Sorted.
    pub click_target_ids: Vec<i64>,
    /// Sorted.
    pub form_field_ids: Vec<i64>,
}

impl SurfacingFeatures {
    /// Folds another block of the session into this one: counts and sums add, maxima take the larger, and sets take
    /// the union with no cap. The result does not depend on the order or grouping of the blocks.
    pub fn merge(&mut self, other: &SurfacingFeatures) {
        macro_rules! add {
            ($($field:ident),*) => { $( self.$field = self.$field.saturating_add(other.$field); )* };
        }
        add!(
            event_count,
            click_count,
            keypress_count,
            mouse_activity_count,
            rage_click_count,
            dead_click_count,
            quick_back_count,
            page_visit_count,
            text_selection_count,
            scroll_event_count,
            console_error_count,
            console_error_after_click_count,
            console_warn_count,
            network_request_count,
            network_failed_request_count,
            network_4xx_count,
            network_5xx_count,
            network_request_duration_count,
            mouse_position_count,
            mouse_direction_change_count,
            mouse_velocity_count,
            scroll_direction_reversal_count,
            rapid_scroll_reversal_count,
            scroll_to_top_count,
            inter_action_gap_count,
            long_idle_gap_count,
            backspace_count,
            mutation_count,
            viewport_resize_count,
            touch_event_count,
            selection_copy_count,
            mouse_sum_x_millipx,
            mouse_sum_x_squared_px2,
            mouse_sum_y_millipx,
            mouse_sum_y_squared_px2,
            mouse_distance_traveled_millipx,
            mouse_velocity_sum_px_per_s,
            mouse_velocity_sum_of_squares_px2_per_s2,
            total_scroll_magnitude_millipx,
            inter_action_gap_sum_ms,
            inter_action_gap_sum_of_squares_ms2,
            network_request_duration_sum_us,
            network_request_duration_sum_of_squares_ms2
        );
        for (count, other) in self
            .path_visit_counts
            .iter_mut()
            .zip(other.path_visit_counts)
        {
            *count = count.saturating_add(other);
        }
        self.max_scroll_y_millipx = self.max_scroll_y_millipx.max(other.max_scroll_y_millipx);
        self.max_idle_gap_ms = self.max_idle_gap_ms.max(other.max_idle_gap_ms);
        union(
            &mut self.visited_url_fingerprints,
            &other.visited_url_fingerprints,
        );
        union(&mut self.click_target_ids, &other.click_target_ids);
        union(&mut self.form_field_ids, &other.form_field_ids);
    }
}

impl From<&BlockFeatures> for SurfacingFeatures {
    fn from(block: &BlockFeatures) -> Self {
        SurfacingFeatures {
            event_count: block.event_count,
            click_count: block.click_count,
            keypress_count: block.keypress_count,
            mouse_activity_count: block.mouse_activity_count,
            rage_click_count: block.rage_click_count,
            dead_click_count: block.dead_click_count,
            quick_back_count: block.quick_back_count,
            page_visit_count: block.page_visit_count,
            text_selection_count: block.text_selection_count,
            scroll_event_count: block.scroll_event_count,
            console_error_count: block.console_error_count,
            console_error_after_click_count: block.console_error_after_click_count,
            console_warn_count: block.console_warn_count,
            network_request_count: block.network_request_count,
            network_failed_request_count: block.network_failed_request_count,
            network_4xx_count: block.network_4xx_count,
            network_5xx_count: block.network_5xx_count,
            network_request_duration_count: block.network_request_duration_count,
            mouse_position_count: block.mouse_position_count,
            mouse_direction_change_count: block.mouse_direction_change_count,
            mouse_velocity_count: block.mouse_velocity_count,
            scroll_direction_reversal_count: block.scroll_direction_reversal_count,
            rapid_scroll_reversal_count: block.rapid_scroll_reversal_count,
            scroll_to_top_count: block.scroll_to_top_count,
            inter_action_gap_count: block.inter_action_gap_count,
            long_idle_gap_count: block.long_idle_gap_count,
            backspace_count: block.backspace_count,
            mutation_count: block.mutation_count,
            viewport_resize_count: block.viewport_resize_count,
            touch_event_count: block.touch_event_count,
            selection_copy_count: block.selection_copy_count,
            path_visit_counts: block.path_token_counts,
            mouse_sum_x_millipx: fixed(block.mouse_sum_x, 1e3),
            mouse_sum_x_squared_px2: fixed(block.mouse_sum_x_squared, 1.0),
            mouse_sum_y_millipx: fixed(block.mouse_sum_y, 1e3),
            mouse_sum_y_squared_px2: fixed(block.mouse_sum_y_squared, 1.0),
            mouse_distance_traveled_millipx: fixed(block.mouse_distance_traveled, 1e3),
            // The TypeScript's velocity is in pixels per millisecond.
            mouse_velocity_sum_px_per_s: fixed(block.mouse_velocity_sum, 1e3),
            mouse_velocity_sum_of_squares_px2_per_s2: fixed(
                block.mouse_velocity_sum_of_squares,
                1e6,
            ),
            total_scroll_magnitude_millipx: fixed(block.total_scroll_magnitude, 1e3),
            inter_action_gap_sum_ms: fixed(block.inter_action_gap_sum_ms, 1.0),
            inter_action_gap_sum_of_squares_ms2: fixed(
                block.inter_action_gap_sum_of_squares_ms,
                1.0,
            ),
            network_request_duration_sum_us: fixed(block.network_request_duration_sum, 1e3),
            network_request_duration_sum_of_squares_ms2: fixed(
                block.network_request_duration_sum_of_squares,
                1.0,
            ),
            max_scroll_y_millipx: fixed(block.max_scroll_y, 1e3),
            max_idle_gap_ms: fixed(block.max_idle_gap_ms, 1.0),
            visited_url_fingerprints: Vec::new(),
            click_target_ids: block.click_target_ids.clone(),
            form_field_ids: block.form_field_ids.clone(),
        }
    }
}

/// `value` in units `scale` times smaller, rounded half away from zero. A value past the `i64` range saturates.
fn fixed(value: f64, scale: f64) -> i64 {
    (value * scale).round() as i64
}

/// The sorted union of two sorted sets.
fn union<T: Ord + Clone>(values: &mut Vec<T>, other: &[T]) {
    if other.is_empty() {
        return;
    }
    values.extend_from_slice(other);
    values.sort_unstable();
    values.dedup();
}

/// A node ID as a set keeps it. The TypeScript keeps any value, but rrweb's node IDs are integers.
fn node_id(inner: &[u8], span: Option<Span>) -> Option<i64> {
    number(inner, span)
        .filter(|id| id.fract() == 0.0 && id.abs() <= MAX_NODE_ID)
        .map(|id| id as i64)
}

/// `text.length` in JavaScript: the UTF-16 code units of a JSON string, counted on its escaped bytes so that nothing
/// is decoded or allocated. An escape is one unit, and so is each half of an escaped surrogate pair.
fn utf16_length(bytes: &[u8], span: Span) -> Option<usize> {
    if !scan::is_string(bytes, span) || span.1 < span.0 + 2 {
        return None;
    }
    let raw = &bytes[span.0 + 1..span.1 - 1];
    let (mut at, mut units) = (0, 0);
    while let Some(&byte) = raw.get(at) {
        let (width, length) = match byte {
            b'\\' if raw.get(at + 1) == Some(&b'u') => (6, 1),
            b'\\' => (2, 1),
            0x00..=0x7f => (1, 1),
            0xc0..=0xdf => (2, 1),
            0xe0..=0xef => (3, 1),
            0xf0..=0xff => (4, 2),
            // A continuation byte, which a valid sequence never starts with.
            _ => (1, 0),
        };
        at += width;
        units += length;
    }
    Some(units)
}

/// JavaScript truthiness of a JSON value.
fn js_truthy(bytes: &[u8], span: Span) -> bool {
    match bytes.get(span.0) {
        Some(b'n' | b'f') => false,
        Some(b'"') => span.1 - span.0 > 2,
        Some(b'-' | b'0'..=b'9') => scan::parse_number(bytes, span).is_some_and(|n| n != 0.0),
        _ => true,
    }
}

/// The [`PATH_TOKENS`] among the segments of the URL's path, one bit per token in their order. A token counts once per
/// URL. `new URL(url).pathname`, or for a URL that does not parse, a relative path up to its query or fragment.
fn path_tokens(url: &str) -> u16 {
    let parsed = url::Url::parse(url);
    let path = match &parsed {
        Ok(parsed) => parsed.path(),
        Err(_) if url.starts_with('/') => url.split(['?', '#']).next().unwrap_or_default(),
        Err(_) => return 0,
    };
    let mut tokens = 0;
    for segment in path.split('/').filter(|s| !s.is_empty()) {
        // A parsed path is ASCII. A relative one can hold a character that lowercases to ASCII, such as the Kelvin sign.
        let lowered = if segment.is_ascii() {
            Cow::Borrowed(segment)
        } else {
            Cow::Owned(segment.to_lowercase())
        };
        for (index, (token, _)) in PATH_TOKENS.iter().enumerate() {
            if lowered.eq_ignore_ascii_case(token) {
                tokens |= 1 << index;
            }
        }
    }
    tokens
}

/// JavaScript's `String.prototype.trim`: its white space and line terminators, which differ from Rust's
/// [`str::trim`] in U+FEFF and U+0085.
pub(crate) fn js_trim(text: &str) -> &str {
    text.trim_matches(|c| {
        matches!(
            c,
            '\u{9}'..='\u{d}'
                | ' '
                | '\u{a0}'
                | '\u{1680}'
                | '\u{2000}'..='\u{200a}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202f}'
                | '\u{205f}'
                | '\u{3000}'
                | '\u{feff}'
        )
    })
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;
    use crate::inspect::session::{BlockInspection, SessionInspector};
    use crate::scan::message::read_message;

    // Expected values traced through `session-feature-recorder.ts` over the same events.

    fn record_blocks(blocks: &[Vec<Value>]) -> Vec<BlockFeatures> {
        let mut session = SessionInspector::default();
        blocks
            .iter()
            .map(|events| {
                let inner = json!({"event": "$snapshot_items", "properties": {
                    "$session_id": "s", "$window_id": "w", "$snapshot_source": "web", "$snapshot_items": events,
                }});
                let payload = json!({"distinct_id": "d", "data": inner.to_string()});
                let message = read_message(payload.to_string().into_bytes()).unwrap();
                let mut block = BlockInspection::default();
                session.observe_message(&mut block, &message);
                block.finish().features
            })
            .collect()
    }

    fn record(events: Vec<Value>) -> BlockFeatures {
        record_blocks(&[events]).remove(0)
    }

    fn incremental(ts: i64, data: Value) -> Value {
        json!({"type": 3, "timestamp": ts, "data": data})
    }

    fn click(ts: i64, x: f64, y: f64, id: i64, kind: Value) -> Value {
        incremental(
            ts,
            json!({"source": 2, "type": kind, "x": x, "y": y, "id": id}),
        )
    }

    fn scroll(ts: i64, mut target: Value) -> Value {
        target["source"] = json!(3);
        incremental(ts, target)
    }

    fn input(ts: i64, id: Option<i64>, text: Value) -> Value {
        let mut data = json!({"source": 5, "text": text});
        if let Some(id) = id {
            data["id"] = json!(id);
        }
        incremental(ts, data)
    }

    fn page(ts: i64, data: Value) -> Value {
        json!({"type": 4, "timestamp": ts, "data": data})
    }

    fn plugin(ts: i64, name: &str, payload: Value) -> Value {
        json!({"type": 6, "timestamp": ts, "data": {"plugin": name, "payload": payload}})
    }

    #[test]
    fn mouse_positions() {
        let f = record(vec![incremental(
            1000,
            json!({"source": 1, "positions": [
                {"x": 0, "y": 0, "timeOffset": 0}, null, {"x": 3, "y": 4, "timeOffset": 10},
                {"x": 0, "y": 0, "timeOffset": 20}, {"x": 0.5, "y": 0},
            ]}),
        )]);
        assert_eq!(
            (
                f.mouse_position_count,
                f.mouse_sum_x,
                f.mouse_sum_x_squared,
                f.mouse_sum_y,
                f.mouse_sum_y_squared
            ),
            (4, 3.5, 9.25, 4.0, 16.0)
        );
        assert_eq!(
            (
                f.mouse_distance_traveled,
                f.mouse_direction_change_count,
                f.mouse_velocity_sum
            ),
            (10.5, 2, 1.0)
        );
        assert_eq!(
            (f.mouse_velocity_sum_of_squares, f.mouse_velocity_count),
            (0.5, 2)
        );
    }

    #[test]
    fn scrolls() {
        // A scroll without a target starts again every time; a null target continues after it.
        let f = record(vec![
            scroll(1000, json!({"id": 1, "y": 0})),
            scroll(1100, json!({"id": 1, "y": 300})),
            scroll(1200, json!({"id": 1, "y": 200})),
            scroll(2200, json!({"id": 1, "y": 900})),
            scroll(2300, json!({"id": 1, "y": 0})),
            scroll(2400, json!({"y": 100})),
            scroll(2500, json!({"y": 400})),
            scroll(2600, json!({"id": null, "y": 100})),
            scroll(2700, json!({"id": 1})),
        ]);
        assert_eq!(
            (
                f.scroll_event_count,
                f.total_scroll_magnitude,
                f.scroll_direction_reversal_count,
                f.rapid_scroll_reversal_count,
                f.scroll_to_top_count,
                f.max_scroll_y
            ),
            (9, 2300.0, 3, 2, 1, 900.0)
        );
    }

    #[test]
    fn clicks_rage_dead_and_touches() {
        let f = record(vec![
            click(1000, 100.0, 100.0, 5, json!(2)),
            click(1200, 110.0, 105.0, 5, json!(2)),
            click(1400, 112.0, 100.0, 6, json!(2)),
            click(1500, 112.0, 101.0, 6, json!(4)),
            click(4000, 500.0, 500.0, 7, json!(2)),
            // The lone click at 4000 did nothing before this context menu, so it was dead.
            click(7000, 900.0, 900.0, 8, json!(3)),
            page(7500, json!({"href": "https://shop.example.com/a"})),
            click(10000, 100.0, 100.0, 9, json!(9)),
            incremental(13000, json!({"source": 2, "type": 2, "id": 10})),
            click(13100, 1.0, 1.0, 11, json!(1)),
            click(13200, 1.0, 1.0, 12, json!("2")),
            click(13300, 1.0, 1.0, 13, json!(7)),
            incremental(13400, json!({"source": 6, "positions": []})),
        ]);
        assert_eq!(
            (
                f.click_count,
                f.rage_click_count,
                f.dead_click_count,
                f.touch_event_count,
                f.mouse_activity_count
            ),
            (8, 2, 1, 3, 12)
        );
        assert_eq!(f.click_target_ids, [5, 6, 7, 8, 9, 10]);
        assert_eq!(
            (
                f.inter_action_gap_count,
                f.inter_action_gap_sum_ms,
                f.inter_action_gap_sum_of_squares_ms,
                f.max_idle_gap_ms
            ),
            (7, 12_000.0, 33_340_000.0, 3000.0)
        );
    }

    #[test]
    fn typing_backspaces_in_utf16_units_and_copies() {
        let selection = |ts: i64| incremental(ts, json!({"source": 14, "ranges": []}));
        let f = record(vec![
            input(1000, Some(20), json!("hello")),
            input(1100, Some(20), json!("hel")),
            input(1200, Some(21), json!("\u{1f600}ab")),
            input(1300, Some(21), json!("a")),
            input(1400, Some(22), json!("a\n\"b\" \u{1}")),
            input(1500, Some(22), json!("")),
            input(1600, None, json!("x")),
            input(1700, Some(23), json!(4)),
            selection(2000),
            input(3500, Some(20), json!("he")),
            input(3600, Some(20), json!("h")),
            selection(5000),
            input(7001, Some(20), json!("")),
        ]);
        assert_eq!(
            (
                f.keypress_count,
                f.backspace_count,
                f.text_selection_count,
                f.selection_copy_count
            ),
            (11, 15, 2, 1)
        );
        assert_eq!(f.form_field_ids, [20, 21, 22, 23]);
    }

    #[test]
    fn gaps_and_console_errors_after_an_action() {
        let console = |ts: i64, level: &str| plugin(ts, "rrweb/console@1", json!({"level": level}));
        let f = record(vec![
            console(500, "error"),
            click(1000, 1.0, 1.0, 1, json!(2)),
            click(1000, 1.0, 1.0, 1, json!(2)),
            input(41000, Some(2), json!("a")),
            // Out of order: no gap counts, but the next starts from here.
            click(2000, 1.0, 1.0, 1, json!(2)),
            console(6999, "error"),
            console(7000, "error"),
            console(1500, "error"),
            console(7100, "warn"),
            console(7200, "info"),
        ]);
        assert_eq!(
            (
                f.inter_action_gap_count,
                f.inter_action_gap_sum_ms,
                f.max_idle_gap_ms,
                f.long_idle_gap_count
            ),
            (1, 40_000.0, 40_000.0, 1)
        );
        assert_eq!(
            (
                f.console_error_count,
                f.console_error_after_click_count,
                f.console_warn_count
            ),
            (4, 1, 1)
        );
    }

    #[test]
    fn navigations_from_any_event_with_javascript_trim_and_path_tokens() {
        let changed = |ts: i64, tag: &str, href: &str| json!({"type": 5, "timestamp": ts, "data": {"tag": tag, "payload": {"href": href}}});
        let f = record(vec![
            page(
                1000,
                json!({"href": "https://shop.example.com/Account/Settings?tab=billing#checkout"}),
            ),
            changed(1500, "$url_changed", "https://shop.example.com/cart"),
            page(1800, json!({"href": "https://shop.example.com/cart"})),
            changed(1900, "$json_ld", "https://shop.example.com/login"),
            page(
                5000,
                json!({"href": "  ", "payload": {"href": "\u{feff}https://shop.example.com/login/LOGIN\u{a0}"}}),
            ),
            page(9000, json!({"href": "/settings/404?next=/admin"})),
            page(12000, json!({"href": "/chec\u{212a}out"})),
            page(15000, json!({"href": "dashboard"})),
            page(
                18000,
                json!({"href": "https://shop.example.com/onboarding/../refund"}),
            ),
            incremental(
                40000,
                json!({"source": 2, "type": 2, "x": 1, "y": 1, "id": 1, "href": "https://shop.example.com/b"}),
            ),
            plugin(
                40500,
                "rrweb/console@1",
                json!({"level": "log", "href": "https://shop.example.com/c"}),
            ),
            incremental(
                41000,
                json!({"source": 0, "adds": [], "removes": [], "texts": [], "attributes": [],
                "payload": {"href": "https://shop.example.com/d"}}),
            ),
        ]);
        assert_eq!(
            (f.page_visit_count, f.quick_back_count, f.visited_urls.len()),
            (11, 3, 10)
        );
        assert!(f
            .visited_urls
            .contains(&"https://shop.example.com/login/LOGIN".to_owned()));
        // login, signup, checkout, cart, billing, settings, account, error, 404, admin, dashboard, onboarding, cancel, refund
        assert_eq!(
            f.path_token_counts,
            [1, 0, 1, 2, 0, 2, 1, 0, 1, 0, 0, 0, 0, 1]
        );
    }

    #[test]
    fn network_requests_from_both_plugins() {
        let f = record(vec![
            plugin(
                1000,
                "rrweb/network@1",
                json!({"requests": [
                    {"status": 200, "duration": 12.5}, {"status": 404, "duration": 0},
                    {"status": null, "responseStatus": 503, "duration": 0.25}, {"responseStatus": 600}, {"status": "500"}, 7,
                ]}),
            ),
            plugin(1100, "posthog/network@1", json!({"21": 500, "39": 100})),
            plugin(1200, "posthog/network@1", json!("")),
            plugin(1300, "posthog/network@1", json!("x")),
            plugin(1400, "posthog/network@1", json!(0)),
            plugin(1500, "other/plugin@1", json!({"requests": [{}]})),
        ]);
        assert_eq!(
            (
                f.network_request_count,
                f.network_failed_request_count,
                f.network_4xx_count,
                f.network_5xx_count
            ),
            (8, 4, 1, 2)
        );
        assert_eq!(
            (
                f.network_request_duration_sum,
                f.network_request_duration_sum_of_squares,
                f.network_request_duration_count
            ),
            (112.75, 10_156.312_5, 3)
        );
    }

    #[test]
    fn skips_the_events_ingestion_drops_and_starts_again_at_each_block() {
        let tap = |ts: Value, id: i64| json!({"type": 3, "timestamp": ts, "data": {"source": 2, "type": 2, "id": id}});
        let f = record(vec![
            json!({"type": 3, "data": {"source": 2, "type": 2, "id": 1}}),
            tap(json!(0), 2),
            tap(json!(-5), 3),
            tap(json!("1000"), 4),
            tap(json!(9e15), 5),
            tap(json!(1000), 6),
            json!({"type": 3, "timestamp": 1001}),
        ]);
        assert_eq!(
            (f.event_count, f.click_count, f.click_target_ids),
            (2, 1, vec![6])
        );

        // Three quick clicks are a rage click in one batch, and none across two.
        let at = |ts: i64| click(ts, 10.0, 10.0, 1, json!(2));
        let blocks = record_blocks(&[vec![at(1000), at(1100)], vec![at(1200)]]);
        assert_eq!(blocks.iter().map(|b| b.rage_click_count).sum::<u64>(), 0);
        assert_eq!(
            record(vec![at(1000), at(1100), at(1200)]).rage_click_count,
            1
        );
    }

    #[test]
    fn keeps_the_first_thousand_values_of_each_set_and_input() {
        let mut events: Vec<Value> = (1..=1001)
            .map(|id| incremental(1000 + id, json!({"source": 2, "type": 2, "id": id, "href": format!("https://a.example/{id}")})))
            .collect();
        events.extend((1..=1001).map(|id| input(5000 + id, Some(id), json!("ab"))));
        // The text of the 1001st input is not remembered, so only the first shrink counts.
        events.extend([
            input(7000, Some(1001), json!("a")),
            input(7001, Some(1), json!("a")),
        ]);
        let f = record(events);
        let mut pages: Vec<String> = (1..=1000)
            .map(|id| format!("https://a.example/{id}"))
            .collect();
        pages.sort_unstable();
        assert_eq!(f.visited_urls, pages);
        assert_eq!(f.click_target_ids, (1..=1000).collect::<Vec<_>>());
        assert_eq!(f.form_field_ids, (1..=1000).collect::<Vec<_>>());
        assert_eq!(f.backspace_count, 1);
    }

    #[test]
    fn stores_each_float_sum_in_the_unit_its_column_names() {
        let block = BlockFeatures {
            mouse_sum_x: 1182.25,
            mouse_sum_y_squared: 647_657.25,
            mouse_distance_traveled: -1.0625,
            mouse_velocity_sum: 0.5,
            mouse_velocity_sum_of_squares: 0.25,
            inter_action_gap_sum_of_squares_ms: 1e300,
            network_request_duration_sum: 1170.35,
            network_request_duration_sum_of_squares: 2.5,
            max_scroll_y: 12_000.25,
            max_idle_gap_ms: 40_000.0,
            ..BlockFeatures::default()
        };
        let stored = SurfacingFeatures::from(&block);
        assert_eq!(
            [
                stored.mouse_sum_x_millipx,
                stored.mouse_sum_y_squared_px2,
                stored.mouse_distance_traveled_millipx,
                stored.mouse_velocity_sum_px_per_s,
                stored.mouse_velocity_sum_of_squares_px2_per_s2,
                stored.inter_action_gap_sum_of_squares_ms2,
                stored.network_request_duration_sum_us,
                stored.network_request_duration_sum_of_squares_ms2,
                stored.max_scroll_y_millipx,
                stored.max_idle_gap_ms,
            ],
            // Halves round away from zero, and a value past the range saturates.
            [
                1_182_250,
                647_657,
                -1_063,
                500,
                250_000,
                i64::MAX,
                1_170_350,
                3,
                12_000_250,
                40_000
            ]
        );
    }
}
