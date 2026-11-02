//! Messages buffered between flushes, and the per-session inspectors that outlive them.

use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::stream::{self, StreamExt};
use metrics::counter;
use replay_core_v4::compression::{GZIP_MAGIC, MAX_DECOMPRESSED_BYTES};
use replay_core_v4::inspect::dom::{Srcset, UrlLimit};
use replay_core_v4::inspect::session::{BlockInspection, Moment, SessionInspector};
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::scan::cv::{Expansion, MESSAGE_DECODE_BUDGET};
use replay_core_v4::scan::message::{Event, Message};

use crate::process::{check_read, read_within};

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SessionKey {
    pub team_id: i64,
    pub session_id: String,
}

/// A topic partition. The recorder reads a fixed set of topics, so the name is static.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Tp {
    pub topic: &'static str,
    pub partition: i32,
}

/// An admitted message, not decoded yet.
pub struct Raw {
    pub offset: i64,
    pub captured_at_ms: Option<i64>,
    pub payload: Vec<u8>,
    pub content_encoding: Option<String>,
}

impl Raw {
    /// The bytes the payload decompresses to. Decompression allocates the size that the lz4 prefix or the gzip footer
    /// states, or fails, so the flush size counts that instead of the compressed bytes.
    pub fn decoded_len(&self) -> usize {
        let stated = if self.content_encoding.as_deref() == Some("lz4") {
            self.payload.get(..4)
        } else if self.payload.starts_with(&GZIP_MAGIC) {
            self.payload.get(self.payload.len().saturating_sub(4)..)
        } else {
            None
        };
        let stated = stated
            .and_then(|b| <[u8; 4]>::try_from(b).ok())
            .map(|b| u32::from_le_bytes(b) as usize)
            .filter(|&n| n <= MAX_DECOMPRESSED_BYTES);
        self.payload.len().max(stated.unwrap_or(0))
    }
}

/// One session's messages from one partition in the current flush, read under one assignment of that partition.
pub struct Pending {
    pub epoch: u64,
    pub messages: Vec<Raw>,
}

/// The offsets a flush handled on one partition, recorded or skipped alike.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub epoch: u64,
    pub first: i64,
    pub last: i64,
}

/// Where a block's messages came from. A failed flush commits nothing, so every later attempt for the partition
/// starts at the same `start_offset`. Readers use this to remove the rows of earlier attempts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Origin {
    pub tp: Tp,
    /// The first offset the flush handled on the partition.
    pub start_offset: i64,
    /// The block's last message.
    pub end_offset: i64,
    /// The last offset the flush handled on the partition, a skipped message included.
    pub flush_end_offset: i64,
}

/// What a flush hands to the writers.
pub struct Block {
    pub session: SessionKey,
    pub origin: Origin,
    pub messages: Vec<Message>,
    pub stats: BlockStats,
    pub moments: Vec<Moment>,
    /// Remote image URLs the block's DOM referenced.
    pub image_urls: Vec<String>,
    /// Every remote URL in an image slot of the block, which the writer replaces with its reference.
    pub remote_urls: Vec<String>,
    /// Set when the inspector stopped short of naming every remote URL, so that the block must not be stored.
    pub url_limit: Option<UrlLimit>,
    /// The image-slot srcset values of the block, which the writer rebuilds from the candidates it keeps.
    pub srcsets: Vec<Srcset>,
    /// The distinct pages of the block's surfacing features, which the writer stores as fingerprints.
    pub visited_urls: Vec<String>,
    /// The earliest Kafka timestamp of the block's messages, for the capture watermark of the index topic.
    pub captured_at_ms: Option<i64>,
}

/// The decoded `cv` strings one flush keeps, on top of the decoded payloads that the flush size counts.
const FLUSH_DECODE_BUDGET: usize = 512 * 1024 * 1024;

/// The decoded `cv` strings one flush expands into its blocks, kept or decoded again. Small gzip payloads can expand
/// a thousandfold, so this bounds the work, and the images, of such a flush. Later events stay as they arrived.
const FLUSH_EXPAND_BUDGET: usize = 2 * 1024 * 1024 * 1024;

/// The part of [`FLUSH_EXPAND_BUDGET`] one session may use. A session's block compresses on one thread, so this keeps
/// one session from taking longer than a flush attempt may.
const SESSION_EXPAND_BUDGET: usize = 256 * 1024 * 1024;

/// The parsed events one flush holds. The flush size counts the payloads, and an event as small as `{}` takes far more
/// memory parsed than in its payload, so a message that does not fit is skipped.
const FLUSH_EVENTS_BUDGET: usize = 1024 * 1024 * 1024;

struct DecodeBudget {
    kept: AtomicUsize,
    expanded: AtomicUsize,
    events: AtomicUsize,
}

impl DecodeBudget {
    fn new(kept: usize, expanded: usize) -> Self {
        Self {
            kept: AtomicUsize::new(kept),
            expanded: AtomicUsize::new(expanded),
            events: AtomicUsize::new(FLUSH_EVENTS_BUDGET),
        }
    }
}

fn take(budget: &AtomicUsize, bytes: usize) -> bool {
    budget
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |left| {
            left.checked_sub(bytes)
        })
        .is_ok()
}

pub struct Batch {
    pub sessions: BTreeMap<(SessionKey, Tp), Pending>,
    pub spans: HashMap<Tp, Span>,
    bytes: usize,
    started: Instant,
}

impl Default for Batch {
    fn default() -> Self {
        Self {
            sessions: BTreeMap::new(),
            spans: HashMap::new(),
            bytes: 0,
            started: Instant::now(),
        }
    }
}

impl Batch {
    /// Marks an offset handled. A skipped message still moves its partition forward. A message of a newer assignment
    /// drops what an older one left, which Kafka delivers again from the last commit.
    pub fn handled(&mut self, tp: Tp, epoch: u64, offset: i64) {
        match self.spans.get_mut(&tp) {
            Some(span) if span.epoch == epoch => span.last = span.last.max(offset),
            stale => {
                if stale.is_some() {
                    self.retain(|t, e| t != tp || e == epoch);
                }
                self.spans.insert(
                    tp,
                    Span {
                        epoch,
                        first: offset,
                        last: offset,
                    },
                );
            }
        }
    }

    pub fn add(&mut self, tp: Tp, epoch: u64, session: SessionKey, raw: Raw) {
        self.handled(tp, epoch, raw.offset);
        self.bytes += raw.decoded_len();
        self.sessions
            .entry((session, tp))
            .or_insert_with(|| Pending {
                epoch,
                messages: Vec::new(),
            })
            .messages
            .push(raw);
    }

    pub fn should_flush(&self, interval: Duration, max_bytes: usize) -> bool {
        !self.spans.is_empty() && (self.bytes >= max_bytes || self.started.elapsed() >= interval)
    }

    pub fn is_empty(&self) -> bool {
        self.spans.is_empty()
    }

    /// Keeps what was read under an assignment that `keep` accepts. The rest is not committed, so it is read again.
    pub fn retain(&mut self, keep: impl Fn(Tp, u64) -> bool) {
        self.sessions
            .retain(|(_, tp), pending| keep(*tp, pending.epoch));
        self.spans.retain(|tp, span| keep(*tp, span.epoch));
        self.bytes = self
            .sessions
            .values()
            .flat_map(|p| &p.messages)
            .map(Raw::decoded_len)
            .sum();
    }

    /// The next offset to commit on each partition.
    pub fn offsets(&self) -> HashMap<Tp, i64> {
        self.spans
            .iter()
            .map(|(tp, span)| (*tp, span.last + 1))
            .collect()
    }
}

struct Live {
    inspector: SessionInspector,
    partitions: Vec<Tp>,
    last_seen: Instant,
    bytes: usize,
}

impl Live {
    fn new(
        session: &SessionKey,
        inspector: SessionInspector,
        partitions: Vec<Tp>,
        last_seen: Instant,
    ) -> Self {
        let mut live = Self {
            inspector,
            partitions,
            last_seen,
            bytes: 0,
        };
        live.measure(session);
        live
    }

    fn measure(&mut self, session: &SessionKey) {
        self.bytes = std::mem::size_of::<(SessionKey, Live)>()
            + session.session_id.capacity()
            + self.partitions.capacity() * std::mem::size_of::<Tp>()
            + self.inspector.retained_bytes();
    }

    /// Keeps the session's activity and clicks, so its later blocks still count them.
    fn evict_dom(&mut self, session: &SessionKey) {
        self.inspector.evict_dom();
        self.measure(session);
    }
}

/// Session inspectors by session. They keep DOM and click state across flushes.
pub struct Inspectors {
    sessions: HashMap<SessionKey, Live>,
    max_bytes: usize,
}

impl Default for Inspectors {
    fn default() -> Self {
        Self::new(usize::MAX)
    }
}

impl Inspectors {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            sessions: HashMap::new(),
            max_bytes,
        }
    }

    /// Decodes every buffered message and runs it through its session's inspector, with up to `concurrency` sessions
    /// at once off the async runtime. Returns one block per session and partition.
    pub async fn inspect(&mut self, batch: Batch, concurrency: usize) -> Vec<Block> {
        let mut work: BTreeMap<SessionKey, Vec<(Origin, Vec<Raw>)>> = BTreeMap::new();
        for ((session, tp), pending) in batch.sessions {
            let Some(span) = batch.spans.get(&tp) else {
                continue;
            };
            let origin = Origin {
                tp,
                start_offset: span.first,
                end_offset: pending
                    .messages
                    .iter()
                    .map(|m| m.offset)
                    .max()
                    .unwrap_or(span.first),
                flush_end_offset: span.last,
            };
            work.entry(session)
                .or_default()
                .push((origin, pending.messages));
        }
        let budget = Arc::new(DecodeBudget::new(FLUSH_DECODE_BUDGET, FLUSH_EXPAND_BUDGET));
        let tasks: Vec<_> = work
            .into_iter()
            .map(|(session, parts)| {
                let (inspector, partitions, last_seen) = match self.sessions.remove(&session) {
                    Some(live) => (live.inspector, live.partitions, Some(live.last_seen)),
                    None => Default::default(),
                };
                (session, inspector, partitions, last_seen, parts)
            })
            .collect();
        let done: Vec<_> = stream::iter(tasks)
            .map(|(session, inspector, partitions, last_seen, parts)| {
                let budget = budget.clone();
                let key = session.clone();
                let messages: usize = parts.iter().map(|(_, raws)| raws.len()).sum();
                let task = tokio::task::spawn_blocking(move || {
                    let inspected = inspect_session(session, inspector, partitions, parts, &budget);
                    (inspected, last_seen)
                });
                async move { (key, messages, task.await) }
            })
            .buffer_unordered(concurrency.max(1))
            .collect()
            .await;
        let now = Instant::now();
        let mut blocks = Vec::new();
        for (key, messages, result) in done {
            // A panic loses that session's block and its inspector state, and the rest of the flush goes on.
            let ((session, inspector, partitions, session_blocks), last_seen) = match result {
                Ok(inspected) => inspected,
                Err(error) => {
                    tracing::error!(%error, team_id = key.team_id, "inspecting a session panicked: its block is dropped");
                    counter!("ai_research_v4_recorder_messages_total", "outcome" => "panicked")
                        .increment(messages as u64);
                    continue;
                }
            };
            // A session that decoded nothing left its state as it was, and does not count as seen.
            let last_seen = if session_blocks.is_empty() {
                last_seen
            } else {
                Some(now)
            };
            if let Some(last_seen) = last_seen {
                let live = Live::new(&session, inspector, partitions, last_seen);
                self.sessions.insert(session, live);
            }
            blocks.extend(session_blocks);
        }
        self.keep_within_budget();
        blocks.sort_by(|a, b| (&a.session, a.origin.tp).cmp(&(&b.session, b.origin.tp)));
        blocks
    }

    pub fn drop_partitions(&mut self, revoked: &[Tp]) {
        self.sessions
            .retain(|_, live| !live.partitions.iter().any(|tp| revoked.contains(tp)));
    }

    pub fn evict_idle(&mut self, idle: Duration) {
        self.sessions
            .retain(|_, live| live.last_seen.elapsed() < idle);
        metrics::gauge!("ai_research_v4_recorder_live_sessions").set(self.sessions.len() as f64);
        metrics::gauge!("ai_research_v4_recorder_retained_bytes").set(self.retained_bytes() as f64);
    }

    pub fn retained_bytes(&self) -> usize {
        self.sessions.values().map(|live| live.bytes).sum()
    }

    /// Evicts the DOM state of the sessions seen least recently until all fit. An evicted session keeps a small entry
    /// that marks its later blocks unverifiable. Whole sessions go only when those entries alone do not fit.
    fn keep_within_budget(&mut self) {
        let mut total = self.retained_bytes();
        if total > self.max_bytes {
            let mut oldest: Vec<(Instant, SessionKey)> = self
                .sessions
                .iter()
                .map(|(session, live)| (live.last_seen, session.clone()))
                .collect();
            oldest.sort_unstable();
            for (_, session) in &oldest {
                if total <= self.max_bytes {
                    break;
                }
                let live = self.sessions.get_mut(session).expect("listed above");
                let bytes = live.bytes;
                live.evict_dom(session);
                total = total - bytes + live.bytes;
                if live.bytes < bytes {
                    counter!("ai_research_v4_recorder_retained_evictions_total", "kind" => "dom")
                        .increment(1);
                }
            }
            for (_, session) in &oldest {
                if total <= self.max_bytes {
                    break;
                }
                if let Some(live) = self.sessions.remove(session) {
                    total -= live.bytes;
                    counter!("ai_research_v4_recorder_retained_evictions_total", "kind" => "session")
                        .increment(1);
                }
            }
        }
        metrics::gauge!("ai_research_v4_recorder_retained_bytes").set(total as f64);
    }
}

/// `partitions` are those the inspector has seen the session on. Its state goes when any of them is revoked.
fn inspect_session(
    session: SessionKey,
    mut inspector: SessionInspector,
    mut partitions: Vec<Tp>,
    parts: Vec<(Origin, Vec<Raw>)>,
    budget: &DecodeBudget,
) -> (SessionKey, SessionInspector, Vec<Tp>, Vec<Block>) {
    let mut decoded = Vec::with_capacity(parts.len());
    let mut session_spent = 0;
    for (origin, raws) in parts {
        let captured_at_ms = raws.iter().filter_map(|raw| raw.captured_at_ms).min();
        let mut messages = Vec::with_capacity(raws.len());
        for raw in raws {
            // A growing list can hold twice its events, so the reader stops at half of what the budget has room for.
            let max_events = budget.events.load(Ordering::Relaxed) / size_of::<Event>() / 2;
            let message = read_within(raw.payload, raw.content_encoding.as_deref(), max_events)
                .and_then(|m| check_read(&m, &session.session_id).map(|()| m));
            match message {
                Ok(mut message) => {
                    if !take(
                        &budget.events,
                        message.buffered_bytes() - message.inner.len(),
                    ) {
                        counter!("ai_research_v4_recorder_messages_total", "outcome" => "over_budget")
                            .increment(1);
                        continue;
                    }
                    // Decoded once here, for the inspector and the block writer both.
                    let flush_room = budget.expanded.load(Ordering::Relaxed);
                    let session_room = SESSION_EXPAND_BUDGET.saturating_sub(session_spent);
                    let spent = message.decode_compressed_within(flush_room.min(session_room));
                    session_spent += spent;
                    if session_room < flush_room {
                        // The session, not the flush, ran out, so the flush's room stays for the other sessions.
                        if message
                            .events
                            .iter()
                            .any(|e| e.expansion == Some(Expansion::Skipped))
                        {
                            counter!("ai_research_v4_recorder_unexpanded_messages_total")
                                .increment(1);
                        }
                        keep_within(&mut message, spent, usize::MAX, budget);
                    } else {
                        keep_within(&mut message, spent, flush_room, budget);
                    }
                    messages.push(message);
                }
                Err(skip) => {
                    counter!("ai_research_v4_recorder_messages_total", "outcome" => skip.as_str())
                        .increment(1);
                }
            }
        }
        if messages.is_empty() {
            continue;
        }
        if !partitions.contains(&origin.tp) {
            partitions.push(origin.tp);
        }
        counter!("ai_research_v4_recorder_messages_total", "outcome" => "recorded")
            .increment(messages.len() as u64);
        decoded.push((origin, messages, captured_at_ms));
    }
    // A session can have messages on the main and the overflow topic in one flush. The inspector takes them in replay
    // order, so that a mutation never comes before the nodes it changes. Each still counts toward its partition's block.
    let mut inspections: Vec<BlockInspection> =
        decoded.iter().map(|_| BlockInspection::default()).collect();
    let times: Vec<Vec<f64>> = decoded
        .iter()
        .map(|(_, messages, _)| messages.iter().map(replay_time).collect())
        .collect();
    let mut next = vec![0; decoded.len()];
    while let Some(part) = (0..decoded.len())
        .filter(|&part| next[part] < times[part].len())
        .min_by(|&a, &b| times[a][next[a]].total_cmp(&times[b][next[b]]))
    {
        inspector.observe_message(&mut inspections[part], &decoded[part].1[next[part]]);
        next[part] += 1;
    }
    let blocks = decoded
        .into_iter()
        .zip(inspections)
        .map(|((origin, messages, captured_at_ms), block)| {
            let inspected = block.finish();
            Block {
                session: session.clone(),
                origin,
                messages,
                stats: inspected.stats,
                moments: inspected.moments,
                image_urls: inspected.image_urls,
                remote_urls: inspected.remote_urls,
                url_limit: inspected.url_limit,
                srcsets: inspected.srcsets,
                visited_urls: inspected.features.visited_urls,
                captured_at_ms,
            }
        })
        .collect();
    (session, inspector, partitions, blocks)
}

/// When a message's events start. One without a timestamp goes as early as its partition's order allows.
fn replay_time(message: &Message) -> f64 {
    message
        .events
        .iter()
        .find_map(|e| e.timestamp_ms)
        .unwrap_or(f64::NEG_INFINITY)
}

/// Drops the message's decoded strings when the flush has no room left to keep them. The inspector and the block
/// writer then each decode them again, which costs CPU but keeps the flush's memory bounded. When the flush has no
/// room left to expand them at all, they stay as they arrived.
///
/// `spent` is what the decode used, failed events included, and `room` what the flush had left before it.
fn keep_within(message: &mut Message, spent: usize, room: usize, budget: &DecodeBudget) {
    // An event that did not fit in the flush's room uses the room up, so that each later message does not decode one
    // event and then stop.
    let overran = room < MESSAGE_DECODE_BUDGET
        && message
            .events
            .iter()
            .any(|e| e.expansion == Some(Expansion::Skipped));
    let charged = budget
        .expanded
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |left| {
            Some(if overran {
                0
            } else {
                left.saturating_sub(spent)
            })
        })
        .is_ok_and(|left| left >= spent);
    if overran || !charged {
        counter!("ai_research_v4_recorder_unexpanded_messages_total").increment(1);
    }
    let decoded = message.decoded_bytes();
    let replacement = if !charged {
        Some(Expansion::Skipped)
    } else if !take(&budget.kept, decoded) {
        None
    } else {
        return;
    };
    for event in &mut message.events {
        if matches!(event.expansion, Some(Expansion::Decoded(_))) {
            event.expansion = replacement.clone();
        }
    }
}

#[cfg(test)]
mod tests {
    use replay_core_v4::compression::gzip;
    use serde_json::{json, Value};

    use super::*;

    fn tp(partition: i32) -> Tp {
        Tp {
            topic: "main",
            partition,
        }
    }

    fn raw(offset: i64, session: &str, items: Value) -> Raw {
        let inner = json!({"event": "$snapshot_items", "properties": {"$session_id": session, "$window_id": "w", "$snapshot_source": "web", "$snapshot_items": items}});
        Raw {
            offset,
            captured_at_ms: None,
            payload: json!({"distinct_id": "d", "data": inner.to_string()})
                .to_string()
                .into_bytes(),
            content_encoding: None,
        }
    }

    fn key(session: &str) -> SessionKey {
        SessionKey {
            team_id: 7,
            session_id: session.to_owned(),
        }
    }

    #[test]
    fn counts_a_compressed_payload_at_its_decoded_size() {
        let plain = raw(
            1,
            "a",
            json!([{"type": 5, "timestamp": 1, "data": "a".repeat(100_000)}]),
        );
        let size = plain.payload.len();
        let gzipped = Raw {
            payload: gzip(&plain.payload).unwrap(),
            ..plain
        };
        assert!(gzipped.payload.len() < size / 10);
        assert_eq!(gzipped.decoded_len(), size);
    }

    fn snapshot() -> Value {
        json!([{"type": 4, "timestamp": 1, "data": {"href": "https://example.com"}}, {"type": 2, "timestamp": 2, "data": {"node": {"type": 0, "childNodes": [], "id": 1}}}])
    }

    fn mouse() -> Value {
        mouse_at(3)
    }

    fn mouse_at(ts: i64) -> Value {
        json!([{"type": 3, "timestamp": ts, "data": {"source": 1, "positions": []}}])
    }

    #[tokio::test]
    async fn a_revoked_partition_leaves_nothing_behind() {
        let mut batch = Batch::default();
        batch.add(tp(0), 0, key("a"), raw(10, "a", mouse()));
        batch.add(tp(1), 0, key("b"), raw(20, "b", mouse()));
        batch.handled(tp(1), 0, 21);
        let mut inspectors = Inspectors::default();
        batch.retain(|tp, _| tp.partition != 1);
        inspectors.drop_partitions(&[tp(1)]);

        assert_eq!(batch.offsets(), HashMap::from([(tp(0), 11)]));
        let blocks = inspectors.inspect(batch, 2).await;
        assert_eq!(
            blocks
                .iter()
                .map(|b| b.session.session_id.as_str())
                .collect::<Vec<_>>(),
            vec!["a"]
        );
    }

    #[test]
    fn a_reassigned_partition_keeps_only_what_its_new_assignment_read() {
        // The partition was revoked and assigned again inside one poll, so Kafka delivers offset 10 again.
        let mut batch = Batch::default();
        batch.add(tp(0), 0, key("a"), raw(10, "a", mouse()));
        batch.add(tp(0), 0, key("a"), raw(11, "a", mouse()));
        batch.add(tp(0), 1, key("a"), raw(10, "a", mouse()));
        batch.retain(|_, epoch| epoch == 1);

        let pending = &batch.sessions[&(key("a"), tp(0))];
        assert_eq!(
            pending
                .messages
                .iter()
                .map(|m| m.offset)
                .collect::<Vec<_>>(),
            [10]
        );
        assert_eq!(batch.offsets(), HashMap::from([(tp(0), 11)]));
    }

    #[test]
    fn a_flush_without_room_keeps_its_expansions_bounded() {
        let cv = |data: &str| -> String {
            gzip(data.as_bytes())
                .unwrap()
                .iter()
                .map(|&b| char::from(b))
                .collect()
        };
        let data = json!({"node": {"type": 0, "childNodes": [], "id": 1}}).to_string();
        let n = data.len();
        // `room` is what the flush had left to expand when the session decoded the message.
        let kept = |data: &str, kept: usize, expanded: usize, room: usize| {
            let items = json!([{"type": 2, "timestamp": 1, "data": cv(data), "cv": "2024-10"}]);
            let mut message = crate::process::read(raw(1, "a", items).payload, None).unwrap();
            let budget = DecodeBudget::new(kept, expanded);
            let spent = message.decode_compressed_within(room);
            keep_within(&mut message, spent, room, &budget);
            let expansion = match &message.events[0].expansion {
                None => "decode again",
                Some(Expansion::Decoded(_)) => "kept",
                Some(Expansion::Skipped) => "as it arrived",
                Some(Expansion::Failed) => "failed",
                Some(other) => panic!("{other:?}"),
            };
            (
                expansion,
                budget.kept.into_inner(),
                budget.expanded.into_inner(),
            )
        };
        assert_eq!(kept(&data, n, n, n), ("kept", 0, 0));
        assert_eq!(kept(&data, n - 1, n, n), ("decode again", n - 1, 0));
        // An event that does not fit uses up the room, so that later messages do not each decode one event.
        assert_eq!(kept(&data, n, n + 1, n - 1), ("as it arrived", n, 0));
        // Another session took the room while this one decoded.
        assert_eq!(kept(&data, n, n - 1, n), ("as it arrived", n, 0));
        // A string that does not decode still used the room it decompressed.
        assert_eq!(kept("not json", n, n + 8, n + 8), ("failed", n, n));
    }

    #[tokio::test]
    async fn inspects_a_session_on_both_topics_in_replay_order() {
        let overflow = Tp {
            topic: "overflow",
            partition: 0,
        };
        let mut batch = Batch::default();
        batch.add(tp(0), 0, key("a"), raw(10, "a", mouse()));
        batch.add(overflow, 0, key("a"), raw(20, "a", snapshot()));
        let blocks = Inspectors::default().inspect(batch, 1).await;
        let cold: Vec<_> = blocks
            .iter()
            .map(|b| (b.origin.tp.topic, b.stats.cold_start))
            .collect();
        assert_eq!(cold, [("main", false), ("overflow", false)]);
    }

    #[tokio::test]
    async fn revoking_any_partition_a_session_was_seen_on_drops_its_state() {
        let mut inspectors = Inspectors::default();
        let mut first = Batch::default();
        first.add(tp(0), 0, key("a"), raw(1, "a", snapshot()));
        inspectors.inspect(first, 1).await;
        let mut second = Batch::default();
        second.add(tp(1), 0, key("a"), raw(1, "a", mouse()));
        inspectors.inspect(second, 1).await;

        inspectors.drop_partitions(&[tp(0)]);
        let mut third = Batch::default();
        third.add(tp(1), 0, key("a"), raw(2, "a", mouse()));
        let blocks = inspectors.inspect(third, 1).await;
        assert!(blocks[0].stats.cold_start);
    }

    #[tokio::test]
    async fn over_budget_the_session_seen_least_recently_loses_its_dom_state() {
        let flush = |items: &[(&str, Value)]| {
            let mut batch = Batch::default();
            for (offset, (session, value)) in items.iter().enumerate() {
                batch.add(
                    tp(0),
                    0,
                    key(session),
                    raw(offset as i64, session, value.clone()),
                );
            }
            batch
        };
        let mut measure = Inspectors::default();
        measure.inspect(flush(&[("a", snapshot())]), 1).await;
        let one = measure.retained_bytes();

        let mut inspectors = Inspectors::new(one + one / 2);
        inspectors
            .inspect(flush(&[("a", snapshot()), ("a", mouse())]), 1)
            .await;
        inspectors.inspect(flush(&[("b", snapshot())]), 1).await;
        assert!(inspectors.retained_bytes() <= one + one / 2);

        let flags = |blocks: Vec<Block>| -> Vec<_> {
            blocks
                .iter()
                .map(|b| {
                    (
                        b.session.session_id.clone(),
                        b.stats.cold_start,
                        b.stats.node_cap_reached,
                        b.stats.active_ms,
                    )
                })
                .collect()
        };
        let blocks = inspectors
            .inspect(flush(&[("a", mouse_at(1003)), ("b", mouse_at(1003))]), 1)
            .await;
        // `a` lost the DOM its snapshot built, so its blocks do not claim to play until it sends a new one. It keeps
        // its activity, so its active time goes on from its mouse move at 3.
        assert_eq!(
            flags(blocks),
            [
                ("a".to_owned(), true, true, 999),
                ("b".to_owned(), false, false, 1)
            ]
        );
        inspectors.inspect(flush(&[("a", snapshot())]), 1).await;
        let blocks = inspectors.inspect(flush(&[("a", mouse())]), 1).await;
        assert_eq!(flags(blocks), [("a".to_owned(), false, false, 0)]);
    }

    #[tokio::test]
    async fn a_session_that_decodes_nothing_keeps_its_state_as_it_was() {
        let unreadable = |offset: i64| Raw {
            offset,
            captured_at_ms: None,
            payload: b"not json".to_vec(),
            content_encoding: None,
        };
        let mut inspectors = Inspectors::default();
        let mut first = Batch::default();
        first.add(tp(0), 0, key("a"), raw(1, "a", snapshot()));
        inspectors.inspect(first, 1).await;
        let retained = inspectors.retained_bytes();

        let mut second = Batch::default();
        second.add(tp(1), 0, key("a"), unreadable(1));
        second.add(tp(1), 0, key("b"), unreadable(2));
        assert!(inspectors.inspect(second, 1).await.is_empty());
        assert_eq!(inspectors.retained_bytes(), retained);

        // `a` was never recorded from partition 1, so its revoke leaves `a`'s DOM state.
        inspectors.drop_partitions(&[tp(1)]);
        let mut third = Batch::default();
        third.add(tp(0), 0, key("a"), raw(2, "a", mouse()));
        assert!(!inspectors.inspect(third, 1).await[0].stats.cold_start);
    }

    #[tokio::test]
    async fn session_state_carries_across_flushes() {
        let mut inspectors = Inspectors::default();
        let mut first = Batch::default();
        first.add(tp(0), 0, key("a"), raw(1, "a", snapshot()));
        first.add(tp(0), 0, key("b"), raw(2, "b", mouse()));
        inspectors.inspect(first, 2).await;

        let mut second = Batch::default();
        second.add(tp(0), 0, key("a"), raw(3, "a", mouse()));
        second.add(tp(0), 0, key("b"), raw(4, "b", mouse()));
        // A message the flush skips still counts towards the flush's end on the partition.
        second.handled(tp(0), 0, 5);
        let blocks = inspectors.inspect(second, 2).await;
        let seen: Vec<_> = blocks
            .iter()
            .map(|b| {
                (
                    b.session.session_id.as_str(),
                    b.stats.cold_start,
                    b.origin.start_offset,
                    b.origin.end_offset,
                    b.origin.flush_end_offset,
                )
            })
            .collect();
        // `a` started with its snapshot in this process. `b` was already running when this process first saw it.
        assert_eq!(seen, vec![("a", false, 3, 3, 5), ("b", true, 3, 4, 5)]);
    }
}
