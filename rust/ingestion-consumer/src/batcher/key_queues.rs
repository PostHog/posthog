//! Per-key FIFO queues with at most one claimed run per key, which
//! preserves per-key order.

use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};
use std::time::Instant;

use common_kafka_consumer::Offset;

use super::request_class::RequestClass;
use crate::types::{Group, SerializedKafkaMessage};

#[derive(Clone, Debug)]
pub struct KeyRun {
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
}

impl KeyRun {
    /// One run per routing key of a poll. The Kafka key is the routing key.
    /// An unkeyed group gets a synthetic key from its partition and first
    /// offset, because it carries no per-key order to preserve.
    pub fn from_groups(groups: Vec<Group>) -> Vec<KeyRun> {
        let mut runs: Vec<KeyRun> = Vec::with_capacity(groups.len());
        let mut index_by_key: HashMap<String, usize> = HashMap::new();
        for group in groups {
            let routing_key = match group.key {
                Some(key) => key,
                None => {
                    let first = group.messages.first().map_or(Offset(-1), |m| m.offset);
                    format!(":{}:{}", group.partition, first)
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

#[derive(Debug, PartialEq, Eq)]
pub enum Settled {
    Evicted,
    Kept,
    Stale,
}

pub struct Purged {
    pub messages: usize,
    pub evicted_keys: Vec<String>,
}

struct QueuedMessage {
    class: RequestClass,
    queued_at: Instant,
    message: SerializedKafkaMessage,
}

struct Claim {
    assignment_epoch: u64,
    /// Partitions revoked while the run was out. Their returned messages
    /// drop, because the new partition owner replays them.
    revoked: Vec<(String, i32)>,
}

/// A key is in one of four states. An idle key is absent from the table. A
/// ready key has queued messages and no claim. A claimed key has one run
/// out: in the packer, waiting for a worker, or on the wire. A waiting key
/// holds returned messages until `retry_at`. Arrivals for a claimed or
/// waiting key queue behind it.
#[derive(Default)]
struct KeyState {
    queue: VecDeque<QueuedMessage>,
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
    keys: HashMap<String, KeyState>,
    /// Ready keys in the order they became ready, so claims stay fair across
    /// keys. An entry can be stale; `take_ready` skips keys that are no
    /// longer ready.
    ready: VecDeque<String>,
    waiting: BTreeSet<(Instant, String)>,
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
        routing_key: &str,
        assignment_epoch: u64,
        messages: Vec<SerializedKafkaMessage>,
        now: Instant,
    ) {
        if messages.is_empty() {
            return;
        }
        self.queued_messages += messages.len();
        self.queued_bytes += payload_bytes(&messages);
        let class = RequestClass {
            assignment_epoch,
            replay: false,
        };
        let state = self.keys.entry(routing_key.to_string()).or_default();
        let was_ready = state.is_ready();
        state
            .queue
            .extend(messages.into_iter().map(|message| QueuedMessage {
                class,
                queued_at: now,
                message,
            }));
        if !was_ready && state.is_ready() {
            self.ready.push_back(routing_key.to_string());
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
            let front = state.queue.front().expect("a ready key has messages");
            let class = front.class;
            let first_arrival = front.queued_at;
            let mut messages = Vec::new();
            while state
                .queue
                .front()
                .is_some_and(|queued| queued.class == class)
            {
                messages.push(state.queue.pop_front().expect("checked").message);
            }
            let bytes = payload_bytes(&messages);
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

    /// Release the key's claim. `returned` goes back to the front of the
    /// queue as replay messages under the claimed run's epoch, ahead of
    /// anything that arrived while the run was out, so the redelivery keeps
    /// offset order.
    pub fn settle(
        &mut self,
        routing_key: &str,
        mut returned: Vec<SerializedKafkaMessage>,
        retry_at: Option<Instant>,
        now: Instant,
    ) -> Settled {
        let Some(state) = self.keys.get_mut(routing_key) else {
            return Settled::Stale;
        };
        let Some(claim) = state.claim.take() else {
            return Settled::Stale;
        };
        self.claimed_keys = self.claimed_keys.saturating_sub(1);

        if !claim.revoked.is_empty() {
            returned.retain(|message| {
                !claim.revoked.iter().any(|(topic, partition)| {
                    topic.as_str() == &*message.topic && *partition == message.partition
                })
            });
        }
        if !returned.is_empty() {
            self.queued_messages += returned.len();
            self.queued_bytes += payload_bytes(&returned);
            let class = RequestClass {
                assignment_epoch: claim.assignment_epoch,
                replay: true,
            };
            for message in returned.into_iter().rev() {
                state.queue.push_front(QueuedMessage {
                    class,
                    queued_at: now,
                    message,
                });
            }
            if let Some(at) = retry_at.filter(|at| *at > now) {
                state.retry_at = Some(at);
                self.waiting.insert((at, routing_key.to_string()));
            }
        }

        if state.is_idle() {
            self.keys.remove(routing_key);
            return Settled::Evicted;
        }
        if state.is_ready() {
            self.ready.push_back(routing_key.to_string());
        }
        Settled::Kept
    }

    pub fn purge(&mut self, revoked: &[(String, i32)]) -> Purged {
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
            let before = state.queue.len();
            state.queue.retain(|queued| {
                let keep =
                    !revoked_set.contains(&(&*queued.message.topic, queued.message.partition));
                if !keep {
                    purged_bytes += queued.message.payload_bytes();
                }
                keep
            });
            purged += before - state.queue.len();
            // The wait belongs to the returned messages. Once the revoke drops
            // them, newer messages behind them must not wait for their retry.
            if !state.queue.iter().any(|queued| queued.class.replay) {
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

        let evicted_keys: Vec<String> = self
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
        Purged {
            messages: purged,
            evicted_keys,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::batcher::test_support::{message, offsets};

    fn claimed(runs: &[ReadyRun]) -> Vec<(&str, Vec<i64>, bool)> {
        runs.iter()
            .map(|run| {
                (
                    run.run.routing_key.as_str(),
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
        queues.push("a", 0, vec![message("a", 0, 1)], now);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![1], false)]
        );

        queues.push("a", 0, vec![message("a", 0, 2), message("a", 0, 3)], now);
        assert!(queues.take_ready(now).is_empty(), "one run per key is out");

        assert_eq!(queues.settle("a", Vec::new(), None, now), Settled::Kept);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![2, 3], false)]
        );
        assert_eq!(queues.settle("a", Vec::new(), None, now), Settled::Evicted);
        assert_eq!(queues.key_count(), 0);
    }

    #[test]
    fn returned_messages_go_first_as_replay_after_their_retry_time() {
        let now = Instant::now();
        let retry_at = now + Duration::from_millis(100);
        let mut queues = KeyQueues::new();
        queues.push("a", 0, vec![message("a", 0, 1), message("a", 0, 2)], now);
        queues.take_ready(now);
        queues.push("a", 0, vec![message("a", 0, 3)], now);

        let returned = vec![message("a", 0, 2)];
        assert_eq!(
            queues.settle("a", returned, Some(retry_at), now),
            Settled::Kept
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
        queues.settle("a", Vec::new(), None, retry_at);
        assert_eq!(
            claimed(&queues.take_ready(retry_at)),
            vec![("a", vec![3], false)]
        );
    }

    #[test]
    fn a_run_stops_at_an_epoch_boundary() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push("a", 1, vec![message("a", 0, 1)], now);
        queues.push("a", 2, vec![message("a", 0, 2)], now);

        let runs = queues.take_ready(now);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].class.assignment_epoch, 1);
        assert_eq!(offsets(&runs[0].run.messages), vec![1]);
    }

    #[test]
    fn a_revoke_drops_queued_messages_and_returned_messages_of_the_partition() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push("a", 0, vec![message("a", 0, 1), message("a", 1, 7)], now);
        queues.take_ready(now);
        queues.push("a", 0, vec![message("a", 0, 2)], now);
        queues.push("b", 0, vec![message("b", 0, 5)], now);

        let purged = queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(purged.messages, 2);
        assert_eq!(purged.evicted_keys, vec!["b".to_string()]);
        assert_eq!(queues.queued_messages(), 0);

        let returned = vec![message("a", 0, 1), message("a", 1, 7)];
        queues.settle("a", returned, None, now);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![7], true)],
            "only the message of the kept partition returns"
        );
    }

    #[test]
    fn a_revoke_that_drops_the_returned_messages_ends_their_wait() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push("a", 0, vec![message("a", 0, 1)], now);
        queues.take_ready(now);
        queues.push("a", 0, vec![message("a", 1, 7)], now);
        let retry_at = now + Duration::from_millis(100);
        queues.settle("a", vec![message("a", 0, 1)], Some(retry_at), now);

        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.next_retry_at(), None);
        assert_eq!(
            claimed(&queues.take_ready(now)),
            vec![("a", vec![7], false)]
        );
    }

    #[test]
    fn a_settle_without_a_claim_is_stale() {
        let now = Instant::now();
        let mut queues = KeyQueues::new();
        queues.push("a", 0, vec![message("a", 0, 1)], now);
        assert_eq!(
            queues.settle("a", vec![message("a", 0, 1)], None, now),
            Settled::Stale
        );
        assert_eq!(queues.queued_messages(), 1);
    }
}
