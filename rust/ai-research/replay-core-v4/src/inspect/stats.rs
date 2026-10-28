//! One row of the v4 block index. Every value covers its block only, so a session row is a fold of its block rows:
//! [`fold_session`].

/// Fingerprints a block or session row keeps. A session row with this many has visited this many pages or more.
pub const MAX_URL_FINGERPRINTS: usize = 10;
/// Window IDs a block or session row keeps. A session row with this many has this many windows or more.
pub const MAX_WINDOW_IDS: usize = 32;

/// The block index columns from `replay-data.md`, apart from the location columns the writer adds.
/// The order is only a tie-break that makes [`fold_session`] independent of the order of its input.
#[derive(Debug, Clone, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct BlockStats {
    pub first_ts_ms: Option<i64>,
    pub last_ts_ms: Option<i64>,
    pub event_count: u64,
    pub byte_size: u64,
    pub host: Option<String>,

    /// Full snapshots that decoded.
    pub full_snapshots: u32,
    /// Events, in any window, before the session's first full snapshot that decoded. A replay shows nothing until then.
    /// Events of a session this process joined midway do not count.
    pub events_before_first_full_snapshot: u32,
    pub orphan_mutations: u32,
    /// Events the recorder could not read in full: a `cv` value that did not decompress, or that the decode budget
    /// left as it arrived, and a full snapshot or mutation that inspection could not decode or walk. Each event counts
    /// once. A message that does not read at all is skipped before it reaches a block, so it does not count here.
    pub decode_failures: u32,
    /// The largest time between two events. When blocks overlap in time, [`BlockStats::merge`] cannot see how their
    /// events interleave, so the folded value is an upper bound.
    pub max_gap_ms: i64,
    pub dom_nodes: u32,
    pub dom_text_chars: u64,
    pub remote_stylesheets: u32,
    pub inline_stylesheets: u32,
    pub iframes: u32,
    pub canvases: u32,
    pub videos: u32,
    pub shadow_roots: u32,
    pub cold_start: bool,
    pub node_cap_reached: bool,
    /// The block had more moments than the index row keeps.
    pub moments_truncated: bool,

    /// The active time this block's events add to the session's, so that the blocks sum to it. When the block
    /// continues an active segment of an earlier block, this includes the time between the two.
    pub active_ms: i64,
    pub clicks: u32,
    /// Every mouse interaction event, of any type, clicks and touches included.
    pub mouse_interactions: u32,
    pub rage_clicks: u32,
    pub dead_clicks: u32,
    pub keypresses: u32,
    pub scrolls: u32,
    pub mouse_moves: u32,
    pub touches: u32,
    pub touch_moves: u32,
    pub selections: u32,
    pub media_events: u32,
    pub viewport_resizes: u32,
    pub navigations: u32,
    /// The distinct pages the block saw, at most [`MAX_URL_FINGERPRINTS`] in the order it first saw them. Each is a
    /// [`crate::refs::url_fingerprint`] under the session's fingerprint key, so it compares only within the session.
    pub url_fingerprints: Vec<String>,
    /// The distinct `$window_id` values of the block's messages, at most [`MAX_WINDOW_IDS`] in the order it first saw
    /// them. A window spans blocks, so a session's window count is the length of its folded list.
    pub window_ids: Vec<String>,
    pub console_errors: u32,
    pub console_warnings: u32,
    pub network_requests: u32,
    pub network_failures: u32,

    pub viewport_width: Option<u32>,
    pub viewport_height: Option<u32>,
    /// The time of the event that set the viewport, so that a fold keeps the latest viewport.
    pub viewport_ts_ms: Option<i64>,
    pub touch_input: bool,

    pub images_extracted: u32,
    pub image_bytes: u64,
    pub images_inline: u32,
    pub image_urls: u32,

    /// The bytes of the block's lines as the writer stores them before compression, with `cv` values expanded and
    /// images moved out.
    pub written_jsonl_bytes: u64,
    /// The longest of those lines.
    pub max_written_event_bytes: u64,
}

impl BlockStats {
    /// Keeps the viewport of the latest event that gives one. Of two events at the same time, the later call wins.
    pub fn set_viewport(&mut self, ts_ms: Option<i64>, width: Option<u32>, height: Option<u32>) {
        if (width.is_none() && height.is_none()) || ts_ms < self.viewport_ts_ms {
            return;
        }
        self.viewport_ts_ms = ts_ms;
        self.viewport_width = width.or(self.viewport_width);
        self.viewport_height = height.or(self.viewport_height);
    }

    /// Folds the next block in time into this one: sums, minimum and maximum times, the first host, the latest
    /// viewport and the pages in the order the session first saw them.
    /// The blocks must come in [`fold_session`] order.
    pub fn merge(&mut self, later: &BlockStats) {
        if let (Some(last), Some(first)) = (self.last_ts_ms, later.first_ts_ms) {
            self.max_gap_ms = self.max_gap_ms.max(first - last);
        }
        self.first_ts_ms = min_option(self.first_ts_ms, later.first_ts_ms);
        self.last_ts_ms = self.last_ts_ms.max(later.last_ts_ms);
        self.host = self.host.take().or_else(|| later.host.clone());
        self.max_gap_ms = self.max_gap_ms.max(later.max_gap_ms);
        self.dom_nodes = self.dom_nodes.max(later.dom_nodes);
        self.dom_text_chars = self.dom_text_chars.max(later.dom_text_chars);
        self.cold_start |= later.cold_start;
        self.node_cap_reached |= later.node_cap_reached;
        self.moments_truncated |= later.moments_truncated;
        self.max_written_event_bytes = self
            .max_written_event_bytes
            .max(later.max_written_event_bytes);
        union(
            &mut self.url_fingerprints,
            &later.url_fingerprints,
            MAX_URL_FINGERPRINTS,
        );
        union(&mut self.window_ids, &later.window_ids, MAX_WINDOW_IDS);
        self.touch_input |= later.touch_input;
        self.set_viewport(
            later.viewport_ts_ms,
            later.viewport_width,
            later.viewport_height,
        );
        macro_rules! sum {
            ($($field:ident),*) => { $( self.$field += later.$field; )* };
        }
        // The inspector stops counting events before the first full snapshot once the session has one, so a block
        // that overlaps the snapshot's block can still hold some.
        sum!(
            event_count,
            byte_size,
            full_snapshots,
            events_before_first_full_snapshot,
            orphan_mutations,
            decode_failures,
            remote_stylesheets,
            inline_stylesheets,
            iframes,
            canvases,
            videos,
            shadow_roots,
            active_ms,
            clicks,
            mouse_interactions,
            rage_clicks,
            dead_clicks,
            keypresses,
            scrolls,
            mouse_moves,
            touches,
            touch_moves,
            selections,
            media_events,
            viewport_resizes,
            navigations,
            console_errors,
            console_warnings,
            network_requests,
            network_failures,
            images_extracted,
            image_bytes,
            images_inline,
            image_urls,
            written_jsonl_bytes
        );
    }
}

/// A session's row: its block rows sorted by first event time, then folded left. Blocks without a time go last.
pub fn fold_session(mut blocks: Vec<BlockStats>) -> BlockStats {
    blocks.sort_by(|a, b| (a.first_ts_ms.is_none(), a).cmp(&(b.first_ts_ms.is_none(), b)));
    let mut blocks = blocks.into_iter();
    let mut session = blocks.next().unwrap_or_default();
    for block in blocks {
        session.merge(&block);
    }
    session
}

/// Appends the values of `later` that `values` does not hold, up to `cap` values in all.
fn union(values: &mut Vec<String>, later: &[String], cap: usize) {
    for value in later {
        if values.len() >= cap {
            break;
        }
        if !values.contains(value) {
            values.push(value.clone());
        }
    }
}

fn min_option(a: Option<i64>, b: Option<i64>) -> Option<i64> {
    match (a, b) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block(first: i64, last: i64, host: &str, full_snapshots: u32, waiting: u32) -> BlockStats {
        let pages = (first / 1_000..first / 1_000 + 6).map(|page| format!("{page:016x}"));
        BlockStats {
            first_ts_ms: Some(first),
            last_ts_ms: Some(last),
            event_count: 10,
            host: Some(host.to_owned()),
            full_snapshots,
            events_before_first_full_snapshot: waiting,
            max_gap_ms: 100,
            viewport_width: Some(first as u32),
            viewport_ts_ms: Some(first),
            decode_failures: 1,
            moments_truncated: first == 3_000,
            mouse_interactions: 2,
            touch_moves: 3,
            url_fingerprints: pages.collect(),
            window_ids: (first / 1_000..first / 1_000 + 20)
                .map(|w| format!("w{w}"))
                .collect(),
            written_jsonl_bytes: 500,
            max_written_event_bytes: first as u64 / 10,
            ..BlockStats::default()
        }
    }

    #[test]
    fn folds_a_session_the_same_in_any_order() {
        let blocks = [
            block(1_000, 2_000, "first.example.com", 0, 4),
            block(3_000, 4_000, "second.example.com", 1, 2),
            // An idle minute between blocks is the session's largest gap.
            block(64_000, 65_000, "third.example.com", 1, 0),
            BlockStats::default(),
        ];
        let session = fold_session(blocks.to_vec());
        for order in [[3, 2, 1, 0], [2, 0, 3, 1], [1, 3, 0, 2]] {
            assert_eq!(
                fold_session(order.map(|i| blocks[i].clone()).to_vec()),
                session
            );
        }
        assert_eq!(session.max_gap_ms, 60_000);
        assert_eq!(session.host.as_deref(), Some("first.example.com"));
        assert_eq!(session.viewport_width, Some(64_000));
        assert_eq!(session.events_before_first_full_snapshot, 6);
        assert_eq!(
            (
                session.decode_failures,
                session.mouse_interactions,
                session.touch_moves,
                session.written_jsonl_bytes,
                session.max_written_event_bytes,
                session.moments_truncated
            ),
            (3, 6, 9, 1_500, 6_400, true)
        );
        // Pages 1 to 6, 3 to 8 and 64 to 69: the first ten distinct, in the order the session first saw them.
        let pages: Vec<String> = (1..=8)
            .chain(64..=65)
            .map(|page| format!("{page:016x}"))
            .collect();
        assert_eq!(session.url_fingerprints, pages);
        // Windows 1 to 20, 3 to 22 and 64 to 83: the first 32 distinct, in the order the session first saw them.
        let windows: Vec<String> = (1..=22).chain(64..=73).map(|w| format!("w{w}")).collect();
        assert_eq!(session.window_ids, windows);
        assert_eq!(
            (session.first_ts_ms, session.last_ts_ms),
            (Some(1_000), Some(65_000))
        );
    }

    #[test]
    fn counts_the_waiting_events_of_a_block_that_overlaps_the_snapshots_block() {
        let main = block(1_000, 5_000, "a.example.com", 1, 2);
        let overflow = block(1_500, 2_500, "a.example.com", 0, 1);
        assert_eq!(
            fold_session(vec![main, overflow]).events_before_first_full_snapshot,
            3
        );
    }

    #[test]
    fn keeps_the_latest_viewport_when_blocks_overlap() {
        let resized_late = BlockStats {
            viewport_ts_ms: Some(10_000),
            ..block(1_000, 11_000, "a.example.com", 1, 0)
        };
        let resized_early = BlockStats {
            viewport_ts_ms: Some(3_000),
            ..block(2_000, 4_000, "a.example.com", 0, 0)
        };
        let session = fold_session(vec![resized_late, resized_early]);
        assert_eq!(session.viewport_width, Some(1_000));
    }
}
