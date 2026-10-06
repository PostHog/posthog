//! Per-key FIFO queues with at most one claimed run per key, which
//! preserves per-key order.

use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};
use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::Offset;

use super::request::RequestClass;
use crate::types::{Group, SerializedKafkaMessage};

#[derive(Clone, Debug)]
pub struct KeyRun {
    pub routing_key: Arc<str>,
    pub messages: Vec<SerializedKafkaMessage>,
}

impl KeyRun {
    /// One run per routing key of a poll. The Kafka key is the routing key.
    /// An unkeyed group gets a synthetic key from its partition and first
    /// offset, because it carries no per-key order to preserve.
    pub fn from_groups(groups: Vec<Group>) -> Vec<KeyRun> {
        let mut runs: Vec<KeyRun> = Vec::with_capacity(groups.len());
        let mut index_by_key: HashMap<Arc<str>, usize> = HashMap::new();
        for group in groups {
            let routing_key: Arc<str> = match group.key {
                Some(key) => key.into(),
                None => {
                    let first = group.messages.first().map_or(Offset(-1), |m| m.offset);
                    format!(":{}:{}", group.partition, first).into()
                }
            };
            let messages = group.messages.into_iter().map(|m| m.message);
            match index_by_key.get(&routing_key) {
                Some(&index) => runs[index].messages.extend(messages),
                None => {
                    index_by_key.insert(routing_key.clone(), runs.len());
                    runs.push(KeyRun {
                        routing_key,
                        messages: messages.collect(),
                    });
                }
            }
        }
        runs
    }
}

pub(super) fn payload_bytes(messages: &[SerializedKafkaMessage]) -> usize {
    messages
        .iter()
        .map(SerializedKafkaMessage::payload_bytes)
        .sum()
}

pub struct ReadyRun {
    pub class: RequestClass,
    pub run: KeyRun,
    pub bytes: usize,
    pub first_arrival: Instant,
}

/// Every settle releases a claim the key queues handed out, so a settle
/// without one is a bookkeeping bug.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("settled key {routing_key} without a claim")]
pub struct UnclaimedSettle {
    pub routing_key: String,
}

/// One push's messages, or one settle's unprocessed messages. Kept whole, so
/// a claim of one segment hands its messages on without copying them.
struct Segment {
    class: RequestClass,
    queued_at: Instant,
    bytes: usize,
    messages: Vec<SerializedKafkaMessage>,
}

struct Claim {
    assignment_epoch: u64,
    /// Partitions revoked while the run was out. Their unprocessed messages
    /// drop, because the new partition owner replays them.
    revoked: Vec<(String, i32)>,
}

/// A key is in one of four states. An idle key is absent from the table. A
/// ready key has queued messages and no claim. A claimed key has one run
/// out: waiting for a worker or on the wire. A waiting key
/// holds unprocessed messages until `retry_at`. Arrivals for a claimed or
/// waiting key queue behind it.
#[derive(Default)]
struct KeyState {
    /// Never holds an empty segment.
    queue: VecDeque<Segment>,
    claim: Option<Claim>,
    retry_at: Option<Instant>,
}

impl KeyState {
    fn is_ready(&self) -> bool {
        self.claim.is_none() && self.retry_at.is_none() && !self.queue.is_empty()
    }

    fn is_idle(&self) -> bool {
        self.claim.is_none() && self.retry_at.is_none() && self.queue.is_empty()
    }
}

#[derive(Default)]
pub struct KeyQueues {
    /// Keyed by customer-chosen routing keys, so the hasher is seeded per
    /// map to resist collision flooding.
    keys: HashMap<Arc<str>, KeyState, ahash::RandomState>,
    /// Ready keys in the order they became ready, so claims stay fair across
    /// keys. An entry can be stale; `take_ready` skips keys that are no
    /// longer ready.
    ready: VecDeque<Arc<str>>,
    waiting: BTreeSet<(Instant, Arc<str>)>,
    queued_messages: usize,
    queued_bytes: usize,
    claimed_keys: usize,
}

impl KeyQueues {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn key_count(&self) -> usize {
        self.keys.len()
    }

    pub fn queued_messages(&self) -> usize {
        self.queued_messages
    }

    pub fn queued_bytes(&self) -> usize {
        self.queued_bytes
    }

    pub fn claimed_keys(&self) -> usize {
        self.claimed_keys
    }

    pub fn waiting_keys(&self) -> usize {
        self.waiting.len()
    }

    pub fn next_retry_at(&self) -> Option<Instant> {
        self.waiting.first().map(|(at, _)| *at)
    }

    pub fn has_ready(&self) -> bool {
        self.ready
            .iter()
            .any(|key| self.keys.get(key).is_some_and(KeyState::is_ready))
    }

    pub fn push(
        &mut self,
        routing_key: Arc<str>,
        assignment_epoch: u64,
        messages: Vec<SerializedKafkaMessage>,
        now: Instant,
    ) {
        if messages.is_empty() {
            return;
        }
        let bytes = payload_bytes(&messages);
        self.queued_messages += messages.len();
        self.queued_bytes += bytes;
        let class = RequestClass {
            assignment_epoch,
            replay: false,
        };
        let state = match self.keys.get_mut(&*routing_key) {
            Some(state) => state,
            None => self.keys.entry(Arc::clone(&routing_key)).or_default(),
        };
        let was_ready = state.is_ready();
        state.queue.push_back(Segment {
            class,
            queued_at: now,
            bytes,
            messages,
        });
        if !was_ready && state.is_ready() {
            self.ready.push_back(routing_key);
        }
    }

    pub fn take_ready(&mut self, now: Instant) -> Vec<ReadyRun> {
        while let Some((at, _)) = self.waiting.first() {
            if *at > now {
                break;
            }
            let (_, key) = self.waiting.pop_first().expect("checked non-empty");
            if let Some(state) = self.keys.get_mut(&key) {
                state.retry_at = None;
                if state.is_ready() {
                    self.ready.push_back(key);
                }
            }
        }

        let mut runs = Vec::with_capacity(self.ready.len());
        while let Some(key) = self.ready.pop_front() {
            let Some(state) = self.keys.get_mut(&key) else {
                continue;
            };
            if !state.is_ready() {
                continue;
            }
            let Segment {
                class,
                queued_at: first_arrival,
                mut bytes,
                mut messages,
            } = state.queue.pop_front().expect("a ready key has messages");
            while state
                .queue
                .front()
                .is_some_and(|segment| segment.class == class)
            {
                let next = state.queue.pop_front().expect("checked");
                bytes += next.bytes;
                messages.extend(next.messages);
            }
            debug_assert!(self.queued_messages >= messages.len());
            self.queued_messages = self.queued_messages.saturating_sub(messages.len());
            self.queued_bytes = self.queued_bytes.saturating_sub(bytes);
            state.claim = Some(Claim {
                assignment_epoch: class.assignment_epoch,
                revoked: Vec::new(),
            });
            self.claimed_keys += 1;
            runs.push(ReadyRun {
                class,
                run: KeyRun {
                    routing_key: key,
                    messages,
                },
                bytes,
                first_arrival,
            });
        }
        runs
    }

    /// Release the key's claim. `unprocessed` goes back to the front of the
    /// queue as replay messages under the claimed run's epoch, ahead of
    /// anything that arrived while the run was out, so the redelivery keeps
    /// offset order. Returns whether the key left the table.
    pub fn settle(
        &mut self,
        routing_key: &Arc<str>,
        mut unprocessed: Vec<SerializedKafkaMessage>,
        retry_at: Option<Instant>,
        now: Instant,
    ) -> Result<bool, UnclaimedSettle> {
        let unclaimed = || UnclaimedSettle {
            routing_key: routing_key.to_string(),
        };
        let Some(state) = self.keys.get_mut(&**routing_key) else {
            return Err(unclaimed());
        };
        let Some(claim) = state.claim.take() else {
            return Err(unclaimed());
        };
        self.claimed_keys = self.claimed_keys.saturating_sub(1);

        if !claim.revoked.is_empty() {
            unprocessed.retain(|message| {
                !claim.revoked.iter().any(|(topic, partition)| {
                    topic.as_str() == &*message.topic && *partition == message.partition
                })
            });
        }
        if !unprocessed.is_empty() {
            let bytes = payload_bytes(&unprocessed);
            self.queued_messages += unprocessed.len();
            self.queued_bytes += bytes;
            state.queue.push_front(Segment {
                class: RequestClass {
                    assignment_epoch: claim.assignment_epoch,
                    replay: true,
                },
                queued_at: now,
                bytes,
                messages: unprocessed,
            });
            if let Some(at) = retry_at.filter(|at| *at > now) {
                state.retry_at = Some(at);
                self.waiting.insert((at, Arc::clone(routing_key)));
            }
        }

        if state.is_idle() {
            self.keys.remove(&**routing_key);
            return Ok(true);
        }
        if state.is_ready() {
            self.ready.push_back(Arc::clone(routing_key));
        }
        Ok(false)
    }

    /// Returns the keys that left the table.
    pub fn purge(&mut self, revoked: &[(String, i32)]) -> Vec<Arc<str>> {
        let revoked_set: HashSet<(&str, i32)> = revoked
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        let mut purged = 0usize;
        let mut purged_bytes = 0usize;
        for (key, state) in self.keys.iter_mut() {
            if let Some(claim) = &mut state.claim {
                for revocation in revoked {
                    if !claim.revoked.contains(revocation) {
                        claim.revoked.push(revocation.clone());
                    }
                }
            }
            for segment in state.queue.iter_mut() {
                let before = segment.messages.len();
                segment.messages.retain(|message| {
                    let keep = !revoked_set.contains(&(&*message.topic, message.partition));
                    if !keep {
                        segment.bytes -= message.payload_bytes();
                        purged_bytes += message.payload_bytes();
                    }
                    keep
                });
                purged += before - segment.messages.len();
            }
            state.queue.retain(|segment| !segment.messages.is_empty());
            // The wait belongs to the unprocessed messages. Once the revoke drops
            // them, newer messages behind them must not wait for their retry.
            if !state.queue.iter().any(|segment| segment.class.replay) {
                if let Some(at) = state.retry_at.take() {
                    self.waiting.remove(&(at, key.clone()));
                    if state.is_ready() {
                        self.ready.push_back(key.clone());
                    }
                }
            }
        }
        self.queued_messages = self.queued_messages.saturating_sub(purged);
        self.queued_bytes = self.queued_bytes.saturating_sub(purged_bytes);

        let evicted_keys: Vec<Arc<str>> = self
            .keys
            .iter()
            .filter(|(_, state)| state.is_idle())
            .map(|(key, _)| key.clone())
            .collect();
        for key in &evicted_keys {
            self.keys.remove(key);
        }
        let keys = &self.keys;
        self.ready
            .retain(|key| keys.get(key).is_some_and(KeyState::is_ready));
        evicted_keys
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::batcher::test_support::{message, offsets};

    fn key(routing_key: &str) -> Arc<str> {
        Arc::from(routing_key)
    }

    fn claimed(runs: &[ReadyRun]) -> Vec<(&str, Vec<i64>, bool)> {
        runs.iter()
            .map(|run| {
                (
                    &*run.run.routing_key,
                    offsets(&run.run.messages),
                    run.class.replay,
                )
            })
            .collect()
    }

    #[test]
    fn arrivals_for_a_claimed_key_wait_for_its_settle() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![1], false)]
        );

        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 2), message("a", 0, 3)],
            now,
        );
        assert!(queues.take_ready(now).is_empty(), "one run per key is out");

        assert_eq!(queues.settle(&key("a"), Vec::new(), None, now), Ok(false));
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![2, 3], false)]
        );
        assert_eq!(queues.settle(&key("a"), Vec::new(), None, now), Ok(true));
        assert_eq!(queues.key_count(), 0);
    }

    #[test]
    fn unprocessed_messages_go_first_as_replay_after_their_retry_time() {
        let now = Instant::now();
        let retry_at = now + Duration::from_millis(100);
        let mut queues = KeyQueues::new();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 0, 2)],
            now,
        );
        queues.take_ready(now);
        queues.push(key("a"), 0, vec![message("a", 0, 3)], now);

        let unprocessed = vec![message("a", 0, 2)];
        assert_eq!(
            queues.settle(&key("a"), unprocessed, Some(retry_at), now),
            Ok(false)
        );
        assert!(
            queues.take_ready(now).is_empty(),
            "waits for its retry time"
        );
        assert_eq!(queues.next_retry_at(), Some(retry_at));

        assert_eq!(
            claimed(&queues.take_ready(retry_at)),
            vec![("a", vec![2], true)]
        );
        queues
            .settle(&key("a"), Vec::new(), None, retry_at)
            .expect("claimed");
        assert_eq!(
            claimed(&queues.take_ready(retry_at)),
            vec![("a", vec![3], false)]
        );
    }

    #[test]
    fn a_run_stops_at_an_epoch_boundary() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push(key("a"), 1, vec![message("a", 0, 1)], now);
        queues.push(key("a"), 2, vec![message("a", 0, 2)], now);

        let runs = queues.take_ready(now);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].class.assignment_epoch, 1);
        assert_eq!(offsets(&runs[0].run.messages), vec![1]);
    }

    #[test]
    fn a_revoke_drops_queued_messages_and_unprocessed_messages_of_the_partition() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 1, 7)],
            now,
        );
        queues.take_ready(now);
        queues.push(key("a"), 0, vec![message("a", 0, 2)], now);
        queues.push(key("b"), 0, vec![message("b", 0, 5)], now);

        let evicted = queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(evicted, vec![Arc::<str>::from("b")]);
        assert_eq!(queues.queued_messages(), 0);

        let unprocessed = vec![message("a", 0, 1), message("a", 1, 7)];
        queues
            .settle(&key("a"), unprocessed, None, now)
            .expect("claimed");
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![7], true)],
            "only the message of the kept partition returns"
        );
    }

    #[test]
    fn a_revoke_that_drops_the_unprocessed_messages_ends_their_wait() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        queues.take_ready(now);
        queues.push(key("a"), 0, vec![message("a", 1, 7)], now);
        let retry_at = now + Duration::from_millis(100);
        queues
            .settle(&key("a"), vec![message("a", 0, 1)], Some(retry_at), now)
            .expect("claimed");

        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.next_retry_at(), None);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![7], false)]
        );
    }

    #[test]
    fn a_settle_without_a_claim_is_an_error() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        assert!(queues
            .settle(&key("a"), vec![message("a", 0, 1)], None, now)
            .is_err());
        assert_eq!(queues.queued_messages(), 1);
    }
}
