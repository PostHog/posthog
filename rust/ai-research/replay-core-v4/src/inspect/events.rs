//! Event-level counts for one block: activity, interactions, navigation, console and network.

use posthog_replay_anonymizer::scan::{self, Span};

use super::rrweb::*;
use super::stats::BlockStats;
use crate::scan::message::Event;

/// The gap after the last active event that ends an active segment, as in `segmentation.ts`.
const ACTIVITY_THRESHOLD_MS: f64 = 5000.0;
/// The status field of a `posthog/network@1` payload, as `session-feature-recorder.ts` reads it.
const POSTHOG_NETWORK_STATUS_KEY: &[u8] = b"21";

/// The value at `key` in the object at `object`, top level only.
pub(crate) fn field(bytes: &[u8], object: Span, key: &[u8]) -> Option<Span> {
    if !scan::is_object(bytes, object) {
        return None;
    }
    scan::object_entries(bytes, object)
        .ok()?
        .filter_map(Result::ok)
        .find(|entry| !entry.key_escaped && &bytes[entry.key.0..entry.key.1] == key)
        .map(|entry| entry.value)
}

/// The values of `keys` in the object at `object`, top level only, in one pass. The first of a repeated key wins.
pub(crate) fn fields<const N: usize>(
    bytes: &[u8],
    object: Span,
    keys: [&[u8]; N],
) -> [Option<Span>; N] {
    let mut found = [None; N];
    if !scan::is_object(bytes, object) {
        return found;
    }
    let Ok(entries) = scan::object_entries(bytes, object) else {
        return found;
    };
    for entry in entries.filter_map(Result::ok).filter(|e| !e.key_escaped) {
        let key = &bytes[entry.key.0..entry.key.1];
        if let Some(index) = keys.iter().position(|&k| k == key) {
            found[index].get_or_insert(entry.value);
        }
    }
    found
}

pub(crate) fn number(bytes: &[u8], span: Option<Span>) -> Option<f64> {
    span.and_then(|span| scan::parse_number(bytes, span))
}

pub(crate) fn text<'b>(bytes: &'b [u8], span: Option<Span>) -> Option<std::borrow::Cow<'b, str>> {
    span.filter(|&span| scan::is_string(bytes, span))
        .and_then(|span| scan::unescape(bytes, span).ok())
}

/// Counts what one block's events did. Navigation needs the session's previous page, so the caller keeps it.
#[derive(Default)]
pub struct EventCounter {
    pub stats: BlockStats,
    timestamps: Vec<(f64, bool)>,
}

impl EventCounter {
    /// Counts one event. Returns whether it carried a page URL, which `session-feature-recorder.ts` treats as a
    /// navigation for dead clicks even when the URL did not change.
    pub fn observe(&mut self, inner: &[u8], event: &Event, last_href: &mut Option<String>) -> bool {
        let stats = &mut self.stats;
        stats.event_count += 1;
        stats.byte_size += (event.span.1 - event.span.0) as u64;
        let active =
            event.kind == Some(INCREMENTAL_SNAPSHOT) && event.source.is_some_and(is_active_source);
        if let Some(ts) = event.timestamp_ms {
            self.timestamps.push((ts, active));
            let ts = ts as i64;
            stats.first_ts_ms = Some(stats.first_ts_ms.map_or(ts, |first| first.min(ts)));
            stats.last_ts_ms = Some(stats.last_ts_ms.map_or(ts, |last| last.max(ts)));
        }
        let Some(data) = event.data else { return false };
        match (event.kind, event.source) {
            (Some(FULL_SNAPSHOT), _) => stats.full_snapshots += 1,
            (Some(META | CUSTOM), _) => {
                let [href, payload, tag, width, height] = fields(
                    inner,
                    data,
                    [b"href", b"payload", b"tag", b"width", b"height"],
                );
                if event.kind == Some(META) {
                    set_viewport(stats, inner, event, width, height);
                }
                let Some(href) = page_url(inner, event.kind, href, payload, tag) else {
                    return false;
                };
                if stats.host.is_none() {
                    stats.host = url::Url::parse(&href)
                        .ok()
                        .and_then(|u| u.host_str().map(str::to_owned));
                }
                if last_href.as_deref() != Some(&*href) {
                    stats.navigations += 1;
                    *last_href = Some(href);
                }
                return true;
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MOUSE_INTERACTION)) => {
                let interaction = number(inner, field(inner, data, b"type")).map(|t| t as u8);
                if interaction.is_some_and(is_click) {
                    stats.clicks += 1;
                }
                if matches!(interaction, Some(TOUCH_START | TOUCH_END)) {
                    stats.touches += 1;
                    stats.touch_input = true;
                }
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MOUSE_MOVE)) => stats.mouse_moves += 1,
            (Some(INCREMENTAL_SNAPSHOT), Some(TOUCH_MOVE)) => {
                stats.touches += 1;
                stats.touch_input = true;
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(SCROLL)) => stats.scrolls += 1,
            (Some(INCREMENTAL_SNAPSHOT), Some(VIEWPORT_RESIZE)) => {
                stats.viewport_resizes += 1;
                let [width, height] = fields(inner, data, [b"width", b"height"]);
                set_viewport(stats, inner, event, width, height);
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(INPUT)) => stats.keypresses += 1,
            (Some(INCREMENTAL_SNAPSHOT), Some(MEDIA_INTERACTION)) => stats.media_events += 1,
            (Some(INCREMENTAL_SNAPSHOT), Some(SELECTION)) => stats.selections += 1,
            (Some(PLUGIN), _) => self.observe_plugin(inner, data),
            _ => {}
        }
        false
    }

    fn observe_plugin(&mut self, inner: &[u8], data: Span) {
        let stats = &mut self.stats;
        let payload = field(inner, data, b"payload");
        match text(inner, field(inner, data, b"plugin")).as_deref() {
            Some("rrweb/console@1") => match payload
                .and_then(|p| text(inner, field(inner, p, b"level")))
                .as_deref()
            {
                Some("error") => stats.console_errors += 1,
                Some("warn") => stats.console_warnings += 1,
                _ => {}
            },
            Some("rrweb/network@1") => {
                let Some(requests) = payload.and_then(|p| field(inner, p, b"requests")) else {
                    return;
                };
                let Ok(items) = scan::array_items(inner, requests) else {
                    return;
                };
                for request in items.filter_map(Result::ok) {
                    // `req.status ?? req.responseStatus`, as `session-feature-recorder.ts` reads it.
                    let [status, response_status] =
                        fields(inner, request, [b"status", b"responseStatus"]);
                    let status = status
                        .filter(|&s| !scan::is_null(inner, s))
                        .or(response_status);
                    count_request(stats, number(inner, status));
                }
            }
            Some("posthog/network@1") => {
                if let Some(payload) = payload.filter(|&p| scan::is_object(inner, p)) {
                    count_request(
                        stats,
                        number(inner, field(inner, payload, POSTHOG_NETWORK_STATUS_KEY)),
                    );
                }
            }
            _ => {}
        }
    }

    /// The block's stats, with active time and the largest gap between events.
    pub fn finish(mut self) -> BlockStats {
        self.timestamps.sort_by(|a, b| a.0.total_cmp(&b.0));
        self.stats.active_ms = active_ms(&self.timestamps);
        self.stats.max_gap_ms = self
            .timestamps
            .windows(2)
            .map(|w| (w[1].0 - w[0].0) as i64)
            .max()
            .unwrap_or(0);
        self.stats
    }
}

fn count_request(stats: &mut BlockStats, status: Option<f64>) {
    stats.network_requests += 1;
    if status.is_some_and(|status| status >= 400.0) {
        stats.network_failures += 1;
    }
}

fn set_viewport(
    stats: &mut BlockStats,
    inner: &[u8],
    event: &Event,
    width: Option<Span>,
    height: Option<Span>,
) {
    stats.set_viewport(
        event.timestamp_ms.map(|ts| ts as i64),
        number(inner, width).map(|w| w as u32),
        number(inner, height).map(|h| h as u32),
    );
}

/// The page URL of a Meta or custom event, by the rules of [`page_url`].
pub fn event_page_url(inner: &[u8], event: &Event) -> Option<String> {
    if !matches!(event.kind, Some(META | CUSTOM)) {
        return None;
    }
    let [href, payload, tag] = fields(inner, event.data?, [b"href", b"payload", b"tag"]);
    page_url(inner, event.kind, href, payload, tag)
}

/// The page URL an event carries, as `hrefFrom` in `rrweb-types.ts` reads it: a Meta event's `href`, or the
/// `payload.href` of a custom event such as posthog-js's `$url_changed`. JSON-LD custom events carry no page.
fn page_url(
    inner: &[u8],
    kind: Option<u8>,
    href: Option<Span>,
    payload: Option<Span>,
    tag: Option<Span>,
) -> Option<String> {
    if kind == Some(CUSTOM) && text(inner, tag).as_deref() == Some("$json_ld") {
        return None;
    }
    let payload_href = payload.and_then(|p| field(inner, p, b"href"));
    [href, payload_href]
        .into_iter()
        .filter_map(|span| text(inner, span))
        .map(|href| href.trim().to_owned())
        .find(|href| !href.is_empty())
}

/// `activeMillisecondsFromSegmentationEvents` from `segmentation.ts`, over events sorted by time.
fn active_ms(events: &[(f64, bool)]) -> i64 {
    let mut total = 0.0;
    let mut segment: Option<(f64, f64, bool)> = None;
    let mut last_active = 0.0;
    for &(ts, active) in events {
        let new_segment = match segment {
            None => true,
            Some((_, _, segment_active)) => {
                (active && !segment_active)
                    || (segment_active && last_active + ACTIVITY_THRESHOLD_MS < ts)
            }
        };
        if active {
            last_active = ts;
        }
        if new_segment {
            if let Some((start, end, true)) = segment {
                total += (end - start).max(1.0);
            }
            segment = Some((ts, ts, active));
        } else if let Some(segment) = segment.as_mut() {
            segment.1 = ts;
        }
    }
    if let Some((start, end, true)) = segment {
        total += (end - start).max(1.0);
    }
    total.floor() as i64
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::scan::message::read_message;

    #[test]
    fn active_time_matches_the_segmentation_the_main_lane_uses() {
        // Traced through `activeMillisecondsFromSegmentationEvents`.
        let cases: [(&[(f64, bool)], i64); 5] = [
            (&[(1000.0, true)], 1),
            (&[(1000.0, true), (3000.0, true), (4000.0, false)], 3000),
            (
                &[
                    (1000.0, true),
                    (7000.0, true),
                    (7500.0, false),
                    (20000.0, true),
                    (24999.5, true),
                ],
                5500,
            ),
            (&[(1000.0, false), (2000.0, false)], 0),
            (
                &[
                    (1000.0, false),
                    (2000.0, true),
                    (8000.0, false),
                    (9000.0, true),
                ],
                2,
            ),
        ];
        for (events, expected) in cases {
            assert_eq!(active_ms(events), expected, "{events:?}");
        }
    }

    #[test]
    fn counts_what_a_blocks_events_did() {
        // `status` wins over `responseStatus`, and posthog-js's own plugin keeps the status under key 21.
        let network = json!({"plugin": "rrweb/network@1", "payload": {"requests": [{"responseStatus": 200}, {"responseStatus": 503}, {"status": 404, "responseStatus": 200}]}});
        let posthog_network =
            json!({"plugin": "posthog/network@1", "payload": {"21": 500, "39": 12}});
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": "s", "$snapshot_items": [
            {"type": 4, "timestamp": 1000, "data": {"href": "https://app.example.com/a", "width": 1280, "height": 720}},
            {"type": 2, "timestamp": 1001, "data": {"node": {}}},
            {"type": 3, "timestamp": 1500, "data": {"source": 2, "type": 2, "id": 5}},
            {"type": 3, "timestamp": 1600, "data": {"source": 2, "type": 1, "id": 5}},
            {"type": 3, "timestamp": 1700, "data": {"source": 2, "type": 9, "id": 5}},
            {"type": 3, "timestamp": 1800, "data": {"source": 5, "text": "x", "id": 6}},
            {"type": 6, "timestamp": 1900, "data": {"plugin": "rrweb/console@1", "payload": {"level": "error"}}},
            {"type": 6, "timestamp": 2000, "data": network},
            {"type": 6, "timestamp": 2000, "data": posthog_network},
            {"type": 4, "timestamp": 9000, "data": {"href": "https://app.example.com/a"}},
            {"type": 4, "timestamp": 9100, "data": {"href": "https://app.example.com/b"}},
            // A single-page app navigates without a Meta event. JSON-LD carries no page.
            {"type": 5, "timestamp": 9200, "data": {"tag": "$url_changed", "payload": {"href": "https://app.example.com/c"}}},
            {"type": 5, "timestamp": 9300, "data": {"tag": "$json_ld", "payload": {"href": "https://app.example.com/d"}}},
        ]}});
        let message = read_message(
            json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
        )
        .unwrap();
        let mut counter = EventCounter::default();
        let mut last_href = None;
        for event in &message.events {
            counter.observe(&message.inner, event, &mut last_href);
        }
        let stats = counter.finish();

        assert_eq!(
            (stats.first_ts_ms, stats.last_ts_ms, stats.event_count),
            (Some(1000), Some(9300), 13)
        );
        assert_eq!(stats.host.as_deref(), Some("app.example.com"));
        // The same page twice in a row is one navigation.
        assert_eq!(stats.navigations, 3);
        assert_eq!(
            (stats.viewport_width, stats.viewport_height),
            (Some(1280), Some(720))
        );
        assert_eq!(
            (
                stats.full_snapshots,
                stats.clicks,
                stats.touches,
                stats.keypresses
            ),
            (1, 2, 1, 1)
        );
        assert!(stats.touch_input);
        assert_eq!(
            (
                stats.console_errors,
                stats.network_requests,
                stats.network_failures
            ),
            (1, 4, 3)
        );
        // Activity runs 1500 to 1800, and the plugin events within 5 seconds extend the segment to 2000.
        assert_eq!((stats.active_ms, stats.max_gap_ms), (500, 7000));
    }
}
