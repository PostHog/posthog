//! One row of the v4 block index. Every value covers its block only, so a session row is a fold of its block rows:
//! [`fold_session`].

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

    pub active_ms: i64,
    pub clicks: u32,
    pub rage_clicks: u32,
    pub dead_clicks: u32,
    pub keypresses: u32,
    pub scrolls: u32,
    pub mouse_moves: u32,
    pub touches: u32,
    pub selections: u32,
    pub media_events: u32,
    pub viewport_resizes: u32,
    pub navigations: u32,
    pub console_errors: u32,
    pub console_warnings: u32,
    pub network_requests: u32,
    pub network_failures: u32,

    pub viewport_width: Option<u32>,
    pub viewport_height: Option<u32>,
    pub touch_input: bool,

    pub images_extracted: u32,
    pub image_bytes: u64,
    pub images_inline: u32,
    pub image_urls: u32,
}

impl BlockStats {
    /// Folds the next block in time into this one: sums, minimum and maximum times, the first host and the last viewport.
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
        self.touch_input |= later.touch_input;
        self.viewport_width = later.viewport_width.or(self.viewport_width);
        self.viewport_height = later.viewport_height.or(self.viewport_height);
        // A session's events before its first full snapshot all sit in the blocks before that snapshot.
        if self.full_snapshots == 0 {
            self.events_before_first_full_snapshot += later.events_before_first_full_snapshot;
        }
        macro_rules! sum {
            ($($field:ident),*) => { $( self.$field += later.$field; )* };
        }
        sum!(
            event_count,
            byte_size,
            full_snapshots,
            orphan_mutations,
            remote_stylesheets,
            inline_stylesheets,
            iframes,
            canvases,
            videos,
            shadow_roots,
            active_ms,
            clicks,
            rage_clicks,
            dead_clicks,
            keypresses,
            scrolls,
            mouse_moves,
            touches,
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
            image_urls
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
        BlockStats {
            first_ts_ms: Some(first),
            last_ts_ms: Some(last),
            event_count: 10,
            host: Some(host.to_owned()),
            full_snapshots,
            events_before_first_full_snapshot: waiting,
            max_gap_ms: 100,
            viewport_width: Some(first as u32),
            ..BlockStats::default()
        }
    }

    #[test]
    fn folds_a_session_the_same_in_any_order() {
        let blocks = [
            block(1_000, 2_000, "first.example.com", 0, 4),
            block(3_000, 4_000, "second.example.com", 1, 2),
            // An idle minute between blocks is the session's largest gap.
            block(64_000, 65_000, "third.example.com", 1, 9),
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
            (session.first_ts_ms, session.last_ts_ms),
            (Some(1_000), Some(65_000))
        );
    }
}
