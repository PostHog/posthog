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

/// One session's messages from one partition in the current flush. Capture keys messages by session, so a session
/// has one partition per topic.
pub struct Pending {
    pub messages: Vec<Raw>,
}

/// What a flush hands to the writers.
pub struct Block {
    pub session: SessionKey,
    pub messages: Vec<Message>,
    pub stats: BlockStats,
    pub moments: Vec<Moment>,
    /// Remote image URLs the block's DOM referenced.
    pub image_urls: Vec<String>,
}

pub struct Batch {
    pub sessions: BTreeMap<(SessionKey, Tp), Pending>,
    /// The last offset handled on each partition, recorded or skipped alike.
    pub offsets: HashMap<Tp, i64>,
    bytes: usize,
    started: Instant,
}

impl Default for Batch {
    fn default() -> Self {
        Self {
            sessions: BTreeMap::new(),
            offsets: HashMap::new(),
            bytes: 0,
            started: Instant::now(),
        }
    }
}

impl Batch {
    /// Marks an offset handled. A skipped message still moves its partition forward.
    pub fn handled(&mut self, tp: Tp, offset: i64) {
        let last = self.offsets.entry(tp).or_insert(offset);
        *last = (*last).max(offset);
    }

    pub fn add(&mut self, tp: Tp, session: SessionKey, raw: Raw) {
        self.handled(tp, raw.offset);
        self.bytes += raw.payload.len();
        self.sessions
            .entry((session, tp))
            .or_insert_with(|| Pending {
                messages: Vec::new(),
            })
            .messages
            .push(raw);
    }

    pub fn should_flush(&self, interval: Duration, max_bytes: usize) -> bool {
        !self.offsets.is_empty() && (self.bytes >= max_bytes || self.started.elapsed() >= interval)
    }

    /// Forgets partitions this process no longer owns. Their messages are not committed, so the new owner reads them.
    pub fn drop_partitions(&mut self, revoked: &[Tp]) {
        self.sessions.retain(|(_, tp), _| !revoked.contains(tp));
        for tp in revoked {
            self.offsets.remove(tp);
        }
        self.bytes = self
            .sessions
            .values()
            .flat_map(|p| &p.messages)
            .map(|m| m.payload.len())
            .sum();
    }
}

/// Session inspectors by session. They keep DOM and click state across flushes.
#[derive(Default)]
pub struct Inspectors {
    sessions: HashMap<SessionKey, (SessionInspector, Vec<Tp>, Instant)>,
}

impl Inspectors {
    /// Decodes every buffered message and runs it through its session's inspector, with up to `concurrency` sessions
    /// at once off the async runtime. Returns one block per session.
    pub async fn inspect(
        &mut self,
        batch: Batch,
        concurrency: usize,
    ) -> (Vec<Block>, HashMap<Tp, i64>) {
        let mut by_session: BTreeMap<SessionKey, (Vec<Tp>, Vec<Raw>)> = BTreeMap::new();
        for ((session, tp), pending) in batch.sessions {
            let (tps, raws) = by_session.entry(session).or_default();
            tps.push(tp);
            raws.extend(pending.messages);
        }
        let tasks: Vec<_> = by_session
            .into_iter()
            .map(|(session, (tps, raws))| {
                let (inspector, mut partitions) = self
                    .sessions
                    .remove(&session)
                    .map(|(inspector, partitions, _)| (inspector, partitions))
                    .unwrap_or_default();
                for tp in tps {
                    if !partitions.contains(&tp) {
                        partitions.push(tp);
                    }
                }
                (session, inspector, partitions, raws)
            })
            .collect();
        let done: Vec<_> = stream::iter(tasks)
            .map(|(session, inspector, partitions, raws)| {
                tokio::task::spawn_blocking(move || {
                    let (inspector, block) = inspect_session(&session, inspector, raws);
                    (session, inspector, partitions, block)
                })
            })
            .buffer_unordered(concurrency.max(1))
            .collect()
            .await;
        let now = Instant::now();
        let mut blocks = Vec::new();
        for result in done {
            let (session, inspector, partitions, block) =
                result.expect("inspecting a session panicked");
            self.sessions.insert(session, (inspector, partitions, now));
            blocks.extend(block);
        }
        blocks.sort_by(|a, b| a.session.cmp(&b.session));
        (blocks, batch.offsets)
    }

    pub fn drop_partitions(&mut self, revoked: &[Tp]) {
        self.sessions
            .retain(|_, (_, partitions, _)| !partitions.iter().any(|tp| revoked.contains(tp)));
    }

    pub fn evict_idle(&mut self, idle: Duration) {
        self.sessions
            .retain(|_, (_, _, last_seen)| last_seen.elapsed() < idle);
        metrics::gauge!("replay_recorder_v4_live_sessions").set(self.sessions.len() as f64);
    }
}

fn inspect_session(
    session: &SessionKey,
    mut inspector: SessionInspector,
    raws: Vec<Raw>,
) -> (SessionInspector, Option<Block>) {
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
        return (inspector, None);
    }
    counter!("replay_recorder_v4_messages_total", "outcome" => "recorded")
        .increment(messages.len() as u64);
    let mut block = BlockInspection::default();
    for message in &messages {
        inspector.observe_message(&mut block, message);
    }
    let inspected = block.finish();
    let block = Block {
        session: session.clone(),
        messages,
        stats: inspected.stats,
        moments: inspected.moments,
        image_urls: inspected.image_urls,
    };
    (inspector, Some(block))
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;

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

    fn tp(partition: i32) -> Tp {
        Tp {
            topic: "main",
            partition,
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
        batch.add(tp(0), key("a"), raw(10, "a", mouse()));
        batch.add(tp(1), key("b"), raw(20, "b", mouse()));
        batch.handled(tp(1), 21);
        let mut inspectors = Inspectors::default();
        batch.drop_partitions(&[tp(1)]);
        inspectors.drop_partitions(&[tp(1)]);

        let (blocks, offsets) = inspectors.inspect(batch, 2).await;
        assert_eq!(
            blocks
                .iter()
                .map(|b| b.session.session_id.as_str())
                .collect::<Vec<_>>(),
            vec!["a"]
        );
        assert_eq!(offsets, HashMap::from([(tp(0), 10)]));
    }

    #[tokio::test]
    async fn session_state_carries_across_flushes() {
        let mut inspectors = Inspectors::default();
        let mut first = Batch::default();
        first.add(tp(0), key("a"), raw(1, "a", snapshot()));
        first.add(tp(0), key("b"), raw(2, "b", mouse()));
        inspectors.inspect(first, 2).await;

        let mut second = Batch::default();
        second.add(tp(0), key("a"), raw(3, "a", mouse()));
        second.add(tp(0), key("b"), raw(4, "b", mouse()));
        let (blocks, _) = inspectors.inspect(second, 2).await;
        let cold: Vec<_> = blocks
            .iter()
            .map(|b| (b.session.session_id.as_str(), b.stats.cold_start))
            .collect();
        // `a` started with its snapshot in this process. `b` was already running when this process first saw it.
        assert_eq!(cold, vec![("a", false), ("b", true)]);
    }
}
