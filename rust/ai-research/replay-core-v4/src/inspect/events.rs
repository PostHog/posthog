//! Event-level counts for one block: activity, interactions, navigation, console and network.

use std::collections::BTreeSet;
use std::ops::Bound;

use crate::bytescan::{self as scan, Span};

use super::rrweb::*;
use super::stats::BlockStats;
use crate::scan::message::Event;

/// The gap after the last active event that ends an active segment, as in `segmentation.ts`.
const ACTIVITY_THRESHOLD_MS: f64 = 5000.0;
/// The distinct times an open inactive segment keeps. Past this the oldest go, so a late active event older than all
/// that remain changes nothing. Out-of-order input then costs a log-time insert, and the state stays small.
const MAX_INACTIVE_TIMES: usize = 1024;
/// The status field of a `posthog/network@1` payload, as `session-feature-recorder.ts` reads it.
const POSTHOG_NETWORK_STATUS_KEY: &[u8] = b"21";
/// The longest DNS name. A longer host resolves nowhere, so it names no site.
const MAX_HOST_BYTES: usize = 253;

/// The page's host as the index stores it. A domain names the customer's site, so it stays, but an IP address can name
/// one machine, so it becomes `[ip_address]` with the WHATWG host parser v3 uses.
fn page_host(href: &str) -> Option<String> {
    let url = url::Url::parse(href).ok()?;
    let host = url.host_str()?;
    if host.len() > MAX_HOST_BYTES {
        return None;
    }
    if !host.is_empty() && !matches!(url::Host::parse(host), Ok(url::Host::Domain(_))) {
        return Some("[ip_address]".to_owned());
    }
    Some(host.to_owned())
}

/// The value at `key` in the object at `object`, top level only. The last of a repeated key wins, as in `JSON.parse`,
/// so that the inspector reads the value the player reads.
pub(crate) fn field(bytes: &[u8], object: Span, key: &[u8]) -> Option<Span> {
    if !scan::is_object(bytes, object) {
        return None;
    }
    scan::object_entries(bytes, object)
        .ok()?
        .filter_map(Result::ok)
        .filter(|entry| !entry.key_escaped && &bytes[entry.key.0..entry.key.1] == key)
        .last()
        .map(|entry| entry.value)
}

/// The values of `keys` in the object at `object`, top level only, in one pass. The last of a repeated key wins.
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
            found[index] = Some(entry.value);
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

/// Counts what one block's events did. Navigation and active time need the session's earlier events, so the caller
/// keeps that state.
#[derive(Default)]
pub struct EventCounter {
    pub stats: BlockStats,
    timestamps: Vec<f64>,
}

impl EventCounter {
    /// Counts one event. Returns whether it carried a page URL, which `session-feature-recorder.ts` treats as a
    /// navigation for dead clicks even when the URL did not change.
    pub fn observe(
        &mut self,
        inner: &[u8],
        event: &Event,
        last_href: &mut Option<String>,
        activity: &mut Activity,
    ) -> bool {
        let stats = &mut self.stats;
        stats.event_count += 1;
        stats.byte_size += (event.span.1 - event.span.0) as u64;
        let active =
            event.kind == Some(INCREMENTAL_SNAPSHOT) && event.source.is_some_and(is_active_source);
        if let Some(ts) = event.timestamp_ms {
            self.timestamps.push(ts);
            let before = activity.total_ms();
            activity.observe(ts, active);
            stats.active_ms += activity.total_ms() - before;
            let ts = ts as i64;
            stats.first_ts_ms = Some(stats.first_ts_ms.map_or(ts, |first| first.min(ts)));
            stats.last_ts_ms = Some(stats.last_ts_ms.map_or(ts, |last| last.max(ts)));
        }
        let Some(data) = event.data else { return false };
        match (event.kind, event.source) {
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
                    stats.host = page_host(&href);
                }
                if last_href.as_deref() != Some(&*href) {
                    stats.navigations += 1;
                    *last_href = Some(href);
                }
                return true;
            }
            (Some(INCREMENTAL_SNAPSHOT), Some(MOUSE_INTERACTION)) => {
                stats.mouse_interactions += 1;
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
                stats.touch_moves += 1;
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

    /// The block's stats, with the largest gap between events.
    pub fn finish(mut self) -> BlockStats {
        self.timestamps.sort_by(f64::total_cmp);
        self.stats.max_gap_ms = self
            .timestamps
            .windows(2)
            .map(|w| (w[1] - w[0]) as i64)
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

/// `activeMillisecondsFromSegmentationEvents` from `segmentation.ts`, run over a whole session so that block active
/// times sum to the session's wherever the block boundaries fall.
#[derive(Debug, Default)]
pub struct Activity {
    segment: Option<Segment>,
    closed_ms: f64,
}

#[derive(Debug)]
enum Segment {
    Active {
        start: f64,
        end: f64,
        last_active: f64,
    },
    /// The distinct times of the segment's newest events. A late active event splits the segment at its time, and
    /// where the parts after it end depends on each of these times.
    Inactive { times: BTreeSet<Time> },
}

/// A timestamp ordered by `total_cmp`. A parsed number is never NaN.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Time(f64);

impl Eq for Time {}

impl PartialOrd for Time {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Time {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.0.total_cmp(&other.0)
    }
}

impl Segment {
    fn open(ts: f64, active: bool) -> Self {
        if active {
            Segment::Active {
                start: ts,
                end: ts,
                last_active: ts,
            }
        } else {
            Segment::Inactive {
                times: BTreeSet::from([Time(ts)]),
            }
        }
    }
}

impl Activity {
    /// A late event, for example from another window, counts as if in order when it falls in the open segment. An
    /// older one changes nothing, because the segments before the open one are closed.
    pub fn observe(&mut self, ts: f64, active: bool) {
        match &mut self.segment {
            None => self.segment = Some(Segment::open(ts, active)),
            Some(Segment::Active { start, .. }) if ts < *start => {}
            Some(Segment::Inactive { times })
                if times.first().is_some_and(|first| ts < first.0) => {}
            Some(Segment::Active {
                start,
                end,
                last_active,
            }) => {
                if ts <= *end {
                    if active {
                        *last_active = last_active.max(ts);
                    }
                } else if *last_active + ACTIVITY_THRESHOLD_MS < ts {
                    self.closed_ms += (*end - *start).max(1.0);
                    self.segment = Some(Segment::open(ts, active));
                } else {
                    *end = ts;
                    if active {
                        *last_active = ts;
                    }
                }
            }
            Some(Segment::Inactive { times }) => {
                // Of equal times, the one that came first sorts first, as in the main lane's stable sort.
                if !active {
                    if times.insert(Time(ts)) && times.len() > MAX_INACTIVE_TIMES {
                        times.pop_first();
                    }
                    return;
                }
                // The events up to `ts` stay in the inactive part. The active segment from `ts` takes the events
                // within the threshold after it, and the events after those open a new inactive segment.
                let limit = Time(ts + ACTIVITY_THRESHOLD_MS);
                let end = times
                    .range((Bound::Excluded(Time(ts)), Bound::Included(limit)))
                    .next_back()
                    .map_or(ts, |t| t.0);
                if times
                    .range((Bound::Excluded(limit), Bound::Unbounded))
                    .next()
                    .is_some()
                {
                    self.closed_ms += (end - ts).max(1.0);
                    let mut later = times.split_off(&limit);
                    later.remove(&limit);
                    *times = later;
                } else {
                    self.segment = Some(Segment::Active {
                        start: ts,
                        end,
                        last_active: ts,
                    });
                }
            }
        }
    }

    pub fn total_ms(&self) -> i64 {
        let open = match self.segment {
            Some(Segment::Active { start, end, .. }) => (end - start).max(1.0),
            _ => 0.0,
        };
        (self.closed_ms + open).floor() as i64
    }

    pub fn retained_bytes(&self) -> usize {
        match &self.segment {
            // A B-tree node holds its keys with spare room and edges, about twice the size of the keys.
            Some(Segment::Inactive { times }) => times.len() * 2 * std::mem::size_of::<Time>(),
            _ => 0,
        }
    }
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
        let active_ms = |events: &[(f64, bool)]| {
            let mut activity = Activity::default();
            for &(ts, active) in events {
                activity.observe(ts, active);
            }
            activity.total_ms()
        };
        for (events, expected) in cases {
            assert_eq!(active_ms(events), expected, "{events:?}");
        }
        // Another window's late event inside the open segment counts as if it came in order.
        let late: [&[(f64, bool)]; 3] = [
            &[
                (1000.0, true),
                (4000.0, false),
                (3000.0, true),
                (8500.0, true),
            ],
            // A late active event splits an open inactive segment, and the active part keeps the later events.
            &[(1000.0, false), (4000.0, false), (3000.0, true)],
            &[
                (1000.0, false),
                (4000.0, false),
                (9000.0, false),
                (3000.0, true),
                (9500.0, true),
            ],
        ];
        for events in late {
            let mut in_order = events.to_vec();
            in_order.sort_by(|a, b| a.0.total_cmp(&b.0));
            assert_eq!(active_ms(events), active_ms(&in_order), "{events:?}");
        }
        assert_eq!(active_ms(late[1]), 1000);
    }

    #[test]
    fn keeps_a_bounded_history_for_late_events() {
        // Each time lands just after the first, which made a sorted list move its whole tail on every insert.
        let mut activity = Activity::default();
        activity.observe(1000.0, false);
        for i in 0..200_000 {
            activity.observe(1_000_000_000.0 - f64::from(i), false);
        }
        assert!(activity.retained_bytes() <= MAX_INACTIVE_TIMES * 2 * std::mem::size_of::<f64>());
        // A late active event older than every kept time changes nothing. One among them still splits the segment.
        activity.observe(2000.0, true);
        assert_eq!(activity.total_ms(), 0);
        activity.observe(999_999_990.5, true);
        assert_eq!(activity.total_ms(), 9);
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
            {"type": 3, "timestamp": 1750, "data": {"source": 6, "positions": []}},
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
        let (mut last_href, mut activity) = (None, Activity::default());
        for event in &message.events {
            counter.observe(&message.inner, event, &mut last_href, &mut activity);
        }
        let stats = counter.finish();

        assert_eq!(
            (stats.first_ts_ms, stats.last_ts_ms, stats.event_count),
            (Some(1000), Some(9300), 14)
        );
        assert_eq!(stats.host.as_deref(), Some("app.example.com"));
        let label = "a".repeat(63);
        let longest = format!("{label}.{label}.{label}.{}", "a".repeat(61));
        for (href, host) in [
            ("https://192.168.0.1/a", Some("[ip_address]")),
            ("https://0300.0250.0.1/a", Some("[ip_address]")),
            ("http://[::1]:8080/a", Some("[ip_address]")),
            ("https://app.example.com:8443/a", Some("app.example.com")),
            (&format!("https://{longest}/a"), Some(longest.as_str())),
            (&format!("https://a{longest}/a"), None),
        ] {
            assert_eq!(page_host(href).as_deref(), host, "{href}");
        }
        // The same page twice in a row is one navigation.
        assert_eq!(stats.navigations, 3);
        assert_eq!(
            (stats.viewport_width, stats.viewport_height),
            (Some(1280), Some(720))
        );
        assert_eq!((stats.clicks, stats.touches, stats.keypresses), (2, 2, 1));
        // Every mouse interaction counts, of any type, and a touch move is a touch too.
        assert_eq!((stats.mouse_interactions, stats.touch_moves), (3, 1));
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
