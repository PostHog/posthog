//! Messages buffered between flushes, and the per-session inspectors that outlive them.

use std::collections::{BTreeMap, HashMap};
use std::time::{Duration, Instant};

use futures::stream::{self, StreamExt};
use metrics::counter;
use replay_core_v4::inspect::session::{BlockInspection, Moment, SessionInspector};
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::scan::message::Message;

use crate::process::{check_read, read};

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
    pub payload: Vec<u8>,
    pub content_encoding: Option<String>,
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
        self.bytes += raw.payload.len();
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
            .map(|m| m.payload.len())
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
}

/// Session inspectors by session. They keep DOM and click state across flushes.
#[derive(Default)]
pub struct Inspectors {
    sessions: HashMap<SessionKey, Live>,
}

impl Inspectors {
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
            };
            work.entry(session)
                .or_default()
                .push((origin, pending.messages));
        }
        let tasks: Vec<_> = work
            .into_iter()
            .map(|(session, parts)| {
                let inspector = self
                    .sessions
                    .remove(&session)
                    .map(|live| live.inspector)
                    .unwrap_or_default();
                (session, inspector, parts)
            })
            .collect();
        let done: Vec<_> = stream::iter(tasks)
            .map(|(session, inspector, parts)| {
                tokio::task::spawn_blocking(move || inspect_session(session, inspector, parts))
            })
            .buffer_unordered(concurrency.max(1))
            .collect()
            .await;
        let now = Instant::now();
        let mut blocks = Vec::new();
        for result in done {
            let (session, inspector, partitions, session_blocks) =
                result.expect("inspecting a session panicked");
            self.sessions.insert(
                session,
                Live {
                    inspector,
                    partitions,
                    last_seen: now,
                },
            );
            blocks.extend(session_blocks);
        }
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
        metrics::gauge!("replay_recorder_v4_live_sessions").set(self.sessions.len() as f64);
    }
}

fn inspect_session(
    session: SessionKey,
    mut inspector: SessionInspector,
    parts: Vec<(Origin, Vec<Raw>)>,
) -> (SessionKey, SessionInspector, Vec<Tp>, Vec<Block>) {
    let mut blocks = Vec::new();
    let mut partitions = Vec::new();
    for (origin, raws) in parts {
        partitions.push(origin.tp);
        let mut messages = Vec::with_capacity(raws.len());
        for raw in raws {
            let message = read(raw.payload, raw.content_encoding.as_deref())
                .and_then(|m| check_read(&m, &session.session_id).map(|()| m));
            match message {
                Ok(mut message) => {
                    // Decoded once here, for the inspector and the block writer both.
                    message.decode_compressed();
                    messages.push(message);
                }
                Err(skip) => {
                    counter!("replay_recorder_v4_messages_total", "outcome" => skip.as_str())
                        .increment(1);
                }
            }
        }
        if messages.is_empty() {
            continue;
        }
        counter!("replay_recorder_v4_messages_total", "outcome" => "recorded")
            .increment(messages.len() as u64);
        let mut block = BlockInspection::default();
        for message in &messages {
            inspector.observe_message(&mut block, message);
        }
        let inspected = block.finish();
        blocks.push(Block {
            session: session.clone(),
            origin,
            messages,
            stats: inspected.stats,
            moments: inspected.moments,
            image_urls: inspected.image_urls,
        });
    }
    (session, inspector, partitions, blocks)
}

#[cfg(test)]
mod tests {
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

    fn snapshot() -> Value {
        json!([{"type": 4, "timestamp": 1, "data": {"href": "https://example.com"}}, {"type": 2, "timestamp": 2, "data": {"node": {"type": 0, "childNodes": [], "id": 1}}}])
    }

    fn mouse() -> Value {
        json!([{"type": 3, "timestamp": 3, "data": {"source": 1, "positions": []}}])
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
        let blocks = inspectors.inspect(second, 2).await;
        let seen: Vec<_> = blocks
            .iter()
            .map(|b| {
                (
                    b.session.session_id.as_str(),
                    b.stats.cold_start,
                    b.origin.start_offset,
                    b.origin.end_offset,
                )
            })
            .collect();
        // `a` started with its snapshot in this process. `b` was already running when this process first saw it.
        assert_eq!(seen, vec![("a", false, 3, 3), ("b", true, 3, 4)]);
    }
}
