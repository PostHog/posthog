//! Everything the recorder learns about one session, block by block.

use super::clicks::{ClickKind, ClickTracker};
use super::dom::DomInspector;
use super::events::{fields, number, EventCounter};
use super::rrweb::{
    is_click, CUSTOM, FULL_SNAPSHOT, INCREMENTAL_SNAPSHOT, META, MOUSE_INTERACTION, MUTATION,
};
use super::stats::BlockStats;
use crate::scan::message::{Event, Message};

/// Moments kept per block, so a long block cannot grow its index row without bound.
pub const MAX_MOMENTS_PER_BLOCK: usize = 256;
/// A mutation that adds or removes this many nodes changes what the page shows.
pub const LARGE_DOM_CHANGE_NODES: u32 = 100;

/// A point a reader can seek to without replaying the session from its start.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Moment {
    pub kind: &'static str,
    pub window_id: String,
    pub ts_ms: i64,
    /// The event's position in its block.
    pub event_index: u32,
}

/// The state of one session in this process. It outlives blocks, because a session spans many flushes.
#[derive(Default)]
pub struct SessionInspector {
    dom: DomInspector,
    clicks: ClickTracker,
    last_href: Option<String>,
    /// The session's start is known: its first Meta, full snapshot or incremental snapshot arrived.
    decided: bool,
    /// This process first saw the session after its first event, so the DOM state starts unknown. posthog-js can send
    /// custom and plugin events before the first Meta, so only an incremental snapshot before it marks a cold start.
    cold: bool,
    /// Events before the start was known, counted once it is known not to be cold.
    undecided: u32,
}

/// One session's block in the current flush.
#[derive(Default)]
pub struct BlockInspection {
    counter: EventCounter,
    moments: Vec<Moment>,
    image_urls: Vec<String>,
    events: u32,
}

/// What the inspector learned about one block.
pub struct Inspected {
    pub stats: BlockStats,
    pub moments: Vec<Moment>,
    /// Remote image URLs the block's DOM referenced, for the image fetcher.
    pub image_urls: Vec<String>,
}

impl BlockInspection {
    pub fn finish(self) -> Inspected {
        Inspected {
            stats: self.counter.finish(),
            moments: self.moments,
            image_urls: self.image_urls,
        }
    }
}

impl SessionInspector {
    pub fn observe_message(&mut self, block: &mut BlockInspection, message: &Message) {
        self.dom.start_message();
        let window = message.window_id.as_deref().unwrap_or_default();
        for event in &message.events {
            self.observe(block, &message.inner, event, window);
        }
    }

    fn observe(&mut self, block: &mut BlockInspection, inner: &[u8], event: &Event, window: &str) {
        if !self.decided {
            match event.kind {
                Some(META | FULL_SNAPSHOT) => {
                    self.decided = true;
                    block.counter.stats.events_before_first_full_snapshot +=
                        std::mem::take(&mut self.undecided);
                }
                Some(INCREMENTAL_SNAPSHOT) => {
                    self.decided = true;
                    self.cold = true;
                    self.undecided = 0;
                }
                _ => {}
            }
        }
        let index = block.events;
        block.events += 1;
        let navigations = block.counter.stats.navigations;
        let carried_href = block.counter.observe(inner, event, &mut self.last_href);
        let navigated = block.counter.stats.navigations > navigations;

        let waiting = block.counter.stats.events_before_first_full_snapshot;
        let observed = self
            .dom
            .observe(inner, event, window, &mut block.counter.stats);
        block.image_urls.extend(self.dom.take_image_urls());
        if observed.full_snapshot {
            self.cold = false;
        }
        let stats = &mut block.counter.stats;
        if !self.decided {
            self.undecided += stats.events_before_first_full_snapshot - waiting;
            stats.events_before_first_full_snapshot = waiting;
        }
        if self.cold {
            // Events before the snapshot that this process never saw do not tell whether the session plays.
            stats.events_before_first_full_snapshot = waiting;
            stats.cold_start = true;
        }

        // `session-feature-recorder.ts` resets dead click state on every page URL, changed or not.
        if carried_href {
            self.clicks.navigated();
        }
        let ts = event.timestamp_ms.unwrap_or_default();
        let mut moment = match event.kind {
            Some(FULL_SNAPSHOT) => Some("full_snapshot"),
            Some(META | CUSTOM) if navigated => Some("navigation"),
            Some(INCREMENTAL_SNAPSHOT)
                if event.source == Some(MUTATION) && observed.changed >= LARGE_DOM_CHANGE_NODES =>
            {
                Some("dom_change")
            }
            _ => None,
        };
        if event.kind == Some(INCREMENTAL_SNAPSHOT) && event.source == Some(MOUSE_INTERACTION) {
            if let Some(data) = event.data {
                let [interaction, x, y] = fields(inner, data, [b"type", b"x", b"y"]);
                if number(inner, interaction).is_some_and(|t| is_click(t as u8)) {
                    let position = number(inner, x).zip(number(inner, y));
                    match self.clicks.click(ts, position) {
                        ClickKind::Rage => stats.rage_clicks += 1,
                        ClickKind::AfterDead => stats.dead_clicks += 1,
                        ClickKind::Plain => {}
                    }
                    moment = Some("click");
                }
            }
        }
        if let Some(kind) = moment {
            if block.moments.len() < MAX_MOMENTS_PER_BLOCK {
                block.moments.push(Moment {
                    kind,
                    window_id: window.to_owned(),
                    ts_ms: ts as i64,
                    event_index: index,
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;
    use crate::scan::message::{read_message, Message};

    fn message(items: Value) -> Message {
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": items}});
        read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
        )
        .unwrap()
    }

    fn inspect(session: &mut SessionInspector, message: &Message) -> (BlockStats, Vec<Moment>) {
        let mut block = BlockInspection::default();
        session.observe_message(&mut block, message);
        let inspected = block.finish();
        (inspected.stats, inspected.moments)
    }

    fn big_mutation(ts: i64) -> Value {
        let adds: Vec<Value> = (0..100)
            .map(|i| json!({"parentId": 1, "node": {"type": 3, "id": 1000 + i}}))
            .collect();
        json!({"type": 3, "timestamp": ts, "data": {"source": 0, "adds": adds, "removes": [], "texts": [], "attributes": []}})
    }

    #[test]
    fn records_moments_where_a_reader_can_seek() {
        let click = |ts: i64| json!({"type": 3, "timestamp": ts, "data": {"source": 2, "type": 2, "x": 5, "y": 5}});
        let first = message(json!([
            {"type": 4, "timestamp": 1, "data": {"href": "https://app.example.com/a"}},
            {"type": 2, "timestamp": 2, "data": {"node": {"type": 0, "childNodes": [], "id": 1}}},
            click(3),
            big_mutation(4),
        ]));
        let mut session = SessionInspector::default();
        let (stats, moments) = inspect(&mut session, &first);
        let kinds: Vec<_> = moments.iter().map(|m| (m.kind, m.event_index)).collect();
        assert_eq!(
            kinds,
            vec![
                ("navigation", 0),
                ("full_snapshot", 1),
                ("click", 2),
                ("dom_change", 3)
            ]
        );
        assert!(!stats.cold_start);

        // The next flush continues the run of clicks the previous block started.
        let second = message(json!([click(100), click(200)]));
        assert_eq!(inspect(&mut session, &second).0.rage_clicks, 1);
    }

    #[test]
    fn counts_spa_navigations_and_dead_clicks_as_the_feature_recorder_does() {
        let meta = |ts: i64, path: &str| json!({"type": 4, "timestamp": ts, "data": {"href": format!("https://app.example.com{path}")}});
        let url_changed = |ts: i64, path: &str| json!({"type": 5, "timestamp": ts, "data": {"tag": "$url_changed", "payload": {"href": format!("https://app.example.com{path}")}}});
        let click = |ts: i64, x: i64| json!({"type": 3, "timestamp": ts, "data": {"source": 2, "type": 2, "x": x, "y": 5}});
        // (events, navigations, dead clicks), traced through `session-feature-recorder.ts`.
        let cases = [
            (
                json!([
                    meta(1, "/"),
                    click(2, 5),
                    url_changed(3, "/next"),
                    click(5000, 500),
                    meta(6000, "/"),
                    click(9000, 5)
                ]),
                3,
                0,
            ),
            // The same URL again still means the click did something.
            (
                json!([meta(1, "/"), click(2, 5), meta(3, "/"), click(5000, 500)]),
                1,
                0,
            ),
            (json!([meta(1, "/"), click(2, 5), click(5000, 500)]), 1, 1),
        ];
        for (items, navigations, dead_clicks) in cases {
            let (stats, _) = inspect(&mut SessionInspector::default(), &message(items.clone()));
            assert_eq!(
                (stats.navigations, stats.dead_clicks),
                (navigations, dead_clicks),
                "{items}"
            );
        }
    }

    #[test]
    fn a_custom_event_before_the_first_meta_is_not_a_cold_start() {
        let session = message(json!([
            {"type": 5, "timestamp": 1, "data": {"tag": "$session_id_change", "payload": {}}},
            {"type": 4, "timestamp": 2, "data": {"href": "https://app.example.com/a"}},
            {"type": 2, "timestamp": 3, "data": {"node": {"type": 0, "childNodes": [], "id": 1}}},
        ]));
        let (stats, _) = inspect(&mut SessionInspector::default(), &session);
        assert!(!stats.cold_start);
        assert_eq!(stats.events_before_first_full_snapshot, 2);
    }

    #[test]
    fn marks_a_session_this_process_joined_midway_as_a_cold_start() {
        let mid_session = message(json!([
            big_mutation(1),
            {"type": 3, "timestamp": 2, "data": {"source": 1, "positions": []}},
        ]));
        let (stats, _) = inspect(&mut SessionInspector::default(), &mid_session);
        assert!(stats.cold_start);
        // Nothing here says the session cannot play: its snapshot came before this process saw it.
        assert_eq!(
            (
                stats.events_before_first_full_snapshot,
                stats.orphan_mutations
            ),
            (0, 0)
        );
    }
}
