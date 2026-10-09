//! Per-key message queues that keep per-key order: a key has at most one run
//! out, and its later messages wait until that run settles.

use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};
use std::num::NonZeroUsize;
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
    /// An unkeyed group gets a synthetic key: it has no per-key order to keep.
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

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ReadySize {
    pub messages: usize,
    pub bytes: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RunCap {
    pub messages: Option<NonZeroUsize>,
    pub bytes: Option<NonZeroUsize>,
}

impl RunCap {
    pub fn reached(&self, size: ReadySize) -> bool {
        self.messages.is_some_and(|cap| size.messages >= cap.get())
            || self.bytes.is_some_and(|cap| size.bytes >= cap.get())
    }
}

impl std::ops::AddAssign for ReadySize {
    fn add_assign(&mut self, other: Self) {
        self.messages += other.messages;
        self.bytes += other.bytes;
    }
}

pub struct ReadyRun {
    pub class: RequestClass,
    pub run: KeyRun,
    pub bytes: usize,
    pub first_arrival: Instant,
}

impl ReadyRun {
    fn size(&self) -> ReadySize {
        ReadySize {
            messages: self.run.messages.len(),
            bytes: self.bytes,
        }
    }
}

/// Every settle releases a claim the queues handed out, so this is a
/// bookkeeping bug.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("settled key {routing_key} without a claim")]
pub struct UnclaimedSettle {
    pub routing_key: String,
}

struct Segment {
    class: RequestClass,
    queued_at: Instant,
    bytes: usize,
    messages: Vec<SerializedKafkaMessage>,
}

impl Segment {
    fn size(&self) -> ReadySize {
        ReadySize {
            messages: self.messages.len(),
            bytes: self.bytes,
        }
    }
}

struct Claim {
    assignment_epoch: u64,
    /// Requeued messages of these partitions drop; the new owner replays them.
    revoked: Vec<(String, i32)>,
}

#[derive(Default)]
struct KeyState {
    segments: VecDeque<Segment>,
    claim: Option<Claim>,
    retry_at: Option<Instant>,
}

impl KeyState {
    fn is_ready(&self) -> bool {
        self.claim.is_none() && self.retry_at.is_none() && !self.segments.is_empty()
    }

    fn is_idle(&self) -> bool {
        self.claim.is_none() && self.retry_at.is_none() && self.segments.is_empty()
    }

    fn ready_size(&self) -> Option<(RequestClass, ReadySize)> {
        if !self.is_ready() {
            return None;
        }
        let front = self.segments.front()?;
        Some((front.class, front.size()))
    }

    fn append(
        &mut self,
        class: RequestClass,
        messages: Vec<SerializedKafkaMessage>,
        now: Instant,
        cap: RunCap,
    ) {
        let mut messages = messages.into_iter();
        while messages.len() > 0 {
            let open = self
                .segments
                .back()
                .is_some_and(|back| back.class == class && !cap.reached(back.size()));
            if !open {
                self.segments.push_back(Segment {
                    class,
                    queued_at: now,
                    bytes: 0,
                    messages: Vec::new(),
                });
            }
            let back = self.segments.back_mut().expect("an open back segment");
            for message in messages.by_ref() {
                back.bytes += message.payload_bytes();
                back.messages.push(message);
                if cap.reached(back.size()) {
                    break;
                }
            }
        }
    }

    fn claim_front(&mut self) -> Segment {
        let segment = self.segments.pop_front().expect("a ready key has messages");
        self.claim = Some(Claim {
            assignment_epoch: segment.class.assignment_epoch,
            revoked: Vec::new(),
        });
        segment
    }
}

/// Per class, the sum of every ready key's `ready_size`, in send order:
/// replays first, then by assignment epoch. Older work holds back commits
/// and polling, so it goes ahead of newer work.
#[derive(Default)]
struct ReadySizes(Vec<(RequestClass, ReadySize)>);

impl ReadySizes {
    fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    fn as_slice(&self) -> &[(RequestClass, ReadySize)] {
        &self.0
    }

    /// Replaces one key's share: `before` is its `ready_size` before a
    /// change, `after` the one after.
    fn replace(
        &mut self,
        before: Option<(RequestClass, ReadySize)>,
        after: Option<(RequestClass, ReadySize)>,
    ) {
        if let Some((class, size)) = before {
            let index = self.0.iter().position(|(c, _)| *c == class);
            debug_assert!(index.is_some(), "no ready size for {class:?}");
            if let Some(index) = index {
                let total = &mut self.0[index].1;
                debug_assert!(
                    total.messages >= size.messages && total.bytes >= size.bytes,
                    "ready size for {class:?} underflows"
                );
                total.messages = total.messages.saturating_sub(size.messages);
                total.bytes = total.bytes.saturating_sub(size.bytes);
                if total.messages == 0 {
                    debug_assert_eq!(total.bytes, 0, "bytes left for {class:?}");
                    self.0.remove(index);
                }
            }
        }
        if let Some((class, size)) = after {
            match self.0.iter_mut().find(|(c, _)| *c == class) {
                Some((_, total)) => {
                    total.messages += size.messages;
                    total.bytes += size.bytes;
                }
                None => {
                    let at = self
                        .0
                        .partition_point(|(c, _)| send_order(c) < send_order(&class));
                    self.0.insert(at, (class, size));
                }
            }
        }
    }
}

fn send_order(class: &RequestClass) -> (bool, u64) {
    (!class.replay, class.assignment_epoch)
}

#[derive(Default)]
pub struct KeyQueues {
    /// Seeded per map, because routing keys are customer-chosen.
    keys: HashMap<Arc<str>, KeyState, ahash::RandomState>,
    /// Can hold stale keys; `take_runs` skips them.
    ready_keys: VecDeque<Arc<str>>,
    waiting_keys: BTreeSet<(Instant, Arc<str>)>,
    ready_sizes: ReadySizes,
    run_cap: RunCap,
    queued_messages: usize,
    queued_bytes: usize,
    claimed_keys: usize,
}

impl KeyQueues {
    pub fn new(run_cap: RunCap) -> Self {
        Self {
            run_cap,
            ..Self::default()
        }
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
        self.waiting_keys.len()
    }

    pub fn next_retry_at(&self) -> Option<Instant> {
        self.waiting_keys.first().map(|(at, _)| *at)
    }

    pub fn has_ready(&self) -> bool {
        !self.ready_sizes.is_empty()
    }

    pub fn ready_sizes(&self) -> &[(RequestClass, ReadySize)] {
        self.ready_sizes.as_slice()
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
        let before = state.ready_size();
        state.append(class, messages, now, self.run_cap);
        self.ready_sizes.replace(before, state.ready_size());
        if !was_ready && state.is_ready() {
            self.ready_keys.push_back(routing_key);
        }
    }

    pub fn promote_due(&mut self, now: Instant) {
        while let Some((at, _)) = self.waiting_keys.first() {
            if *at > now {
                break;
            }
            let (_, key) = self.waiting_keys.pop_first().expect("checked non-empty");
            if let Some(state) = self.keys.get_mut(&key) {
                let before = state.ready_size();
                state.retry_at = None;
                self.ready_sizes.replace(before, state.ready_size());
                if state.is_ready() {
                    self.ready_keys.push_back(key);
                }
            }
        }
    }

    /// Claims ready runs of `class` in ready order until `full` holds for
    /// their total size. Ready keys of other classes keep their place.
    pub fn take_runs(
        &mut self,
        class: RequestClass,
        full: impl Fn(ReadySize) -> bool,
    ) -> Vec<ReadyRun> {
        let mut taken = ReadySize::default();
        let mut runs = Vec::new();
        let mut skipped = Vec::new();
        while !full(taken) {
            let Some(key) = self.next_ready(class, &mut skipped) else {
                break;
            };
            let run = self.claim(key);
            taken += run.size();
            runs.push(run);
        }
        for key in skipped.into_iter().rev() {
            self.ready_keys.push_front(key);
        }
        runs
    }

    fn next_ready(&mut self, class: RequestClass, skipped: &mut Vec<Arc<str>>) -> Option<Arc<str>> {
        while let Some(key) = self.ready_keys.pop_front() {
            match self.keys.get(&key).and_then(KeyState::ready_size) {
                Some((next, _)) if next == class => return Some(key),
                Some(_) => skipped.push(key),
                None => {}
            }
        }
        None
    }

    fn claim(&mut self, key: Arc<str>) -> ReadyRun {
        let state = self
            .keys
            .get_mut(&key)
            .expect("next_ready returns ready keys");
        let segment = state.claim_front();
        let size = segment.size();
        self.ready_sizes.replace(Some((segment.class, size)), None);
        debug_assert!(self.queued_messages >= size.messages);
        self.queued_messages = self.queued_messages.saturating_sub(size.messages);
        self.queued_bytes = self.queued_bytes.saturating_sub(size.bytes);
        self.claimed_keys += 1;
        ReadyRun {
            class: segment.class,
            bytes: size.bytes,
            first_arrival: segment.queued_at,
            run: KeyRun {
                routing_key: key,
                messages: segment.messages,
            },
        }
    }

    pub fn settle(
        &mut self,
        routing_key: &Arc<str>,
        mut requeued: Vec<SerializedKafkaMessage>,
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
            requeued.retain(|message| {
                !claim.revoked.iter().any(|(topic, partition)| {
                    topic.as_str() == &*message.topic && *partition == message.partition
                })
            });
        }
        if !requeued.is_empty() {
            let bytes = payload_bytes(&requeued);
            self.queued_messages += requeued.len();
            self.queued_bytes += bytes;
            // Ahead of later arrivals and under the run's epoch, so the replay
            // keeps offset order.
            state.segments.push_front(Segment {
                class: RequestClass {
                    assignment_epoch: claim.assignment_epoch,
                    replay: true,
                },
                queued_at: now,
                bytes,
                messages: requeued,
            });
            if let Some(at) = retry_at.filter(|at| *at > now) {
                state.retry_at = Some(at);
                self.waiting_keys.insert((at, Arc::clone(routing_key)));
            }
        }

        self.ready_sizes.replace(None, state.ready_size());
        if state.is_idle() {
            self.keys.remove(&**routing_key);
            return Ok(true);
        }
        if state.is_ready() {
            self.ready_keys.push_back(Arc::clone(routing_key));
        }
        Ok(false)
    }

    pub fn purge(&mut self, revoked: &[(String, i32)]) -> Vec<Arc<str>> {
        let revoked_set: HashSet<(&str, i32)> = revoked
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        let mut purged = 0usize;
        let mut purged_bytes = 0usize;
        for (key, state) in self.keys.iter_mut() {
            let before = state.ready_size();
            if let Some(claim) = &mut state.claim {
                for revocation in revoked {
                    if !claim.revoked.contains(revocation) {
                        claim.revoked.push(revocation.clone());
                    }
                }
            }
            for segment in state.segments.iter_mut() {
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
            state
                .segments
                .retain(|segment| !segment.messages.is_empty());
            // The wait was for the requeued messages the revoke just dropped.
            if !state.segments.iter().any(|segment| segment.class.replay) {
                if let Some(at) = state.retry_at.take() {
                    self.waiting_keys.remove(&(at, key.clone()));
                    if state.is_ready() {
                        self.ready_keys.push_back(key.clone());
                    }
                }
            }
            self.ready_sizes.replace(before, state.ready_size());
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
        self.ready_keys
            .retain(|key| keys.get(key).is_some_and(KeyState::is_ready));
        evicted_keys
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use common_kafka_consumer::{GroupMessage, Partition};

    use super::*;
    use crate::batcher::test_support::{message, offsets};

    fn key(routing_key: &str) -> Arc<str> {
        Arc::from(routing_key)
    }

    const FRESH: RequestClass = RequestClass {
        assignment_epoch: 0,
        replay: false,
    };

    fn take_all(queues: &mut KeyQueues, now: Instant) -> Vec<ReadyRun> {
        queues.promote_due(now);
        let mut runs = Vec::new();
        while let Some(&(class, _)) = queues.ready_sizes().first() {
            runs.extend(queues.take_runs(class, |_| false));
        }
        runs
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
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![1], false)]
        );

        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 2), message("a", 0, 3)],
            now,
        );
        assert!(
            take_all(&mut queues, now).is_empty(),
            "one run per key is out"
        );

        assert_eq!(queues.settle(&key("a"), Vec::new(), None, now), Ok(false));
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![2, 3], false)]
        );
        assert_eq!(queues.settle(&key("a"), Vec::new(), None, now), Ok(true));
        assert_eq!(queues.key_count(), 0);
    }

    #[test]
    fn keys_past_the_message_limit_stay_unclaimed_and_keep_their_turn() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        for routing_key in ["a", "b", "c"] {
            queues.push(key(routing_key), 0, vec![message(routing_key, 0, 1)], now);
        }

        assert_eq!(
            claimed(&queues.take_runs(FRESH, |taken| taken.messages >= 1)),
            vec![("a", vec![1], false)]
        );
        assert_eq!(queues.claimed_keys(), 1);
        assert_eq!(queues.queued_messages(), 2);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("b", vec![1], false), ("c", vec![1], false)]
        );
    }

    #[test]
    fn requeued_messages_go_first_as_replay_after_their_retry_time() {
        let now = Instant::now();
        let retry_at = now + Duration::from_millis(100);
        let mut queues = KeyQueues::default();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 0, 2)],
            now,
        );
        take_all(&mut queues, now);
        queues.push(key("a"), 0, vec![message("a", 0, 3)], now);

        let requeued = vec![message("a", 0, 2)];
        assert_eq!(
            queues.settle(&key("a"), requeued, Some(retry_at), now),
            Ok(false)
        );
        assert!(
            take_all(&mut queues, now).is_empty(),
            "waits for its retry time"
        );
        assert_eq!(queues.next_retry_at(), Some(retry_at));

        assert_eq!(
            claimed(&take_all(&mut queues, retry_at)),
            vec![("a", vec![2], true)]
        );
        queues
            .settle(&key("a"), Vec::new(), None, retry_at)
            .expect("claimed");
        assert_eq!(
            claimed(&take_all(&mut queues, retry_at)),
            vec![("a", vec![3], false)]
        );
    }

    #[test]
    fn a_run_stops_at_an_epoch_boundary() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 1, vec![message("a", 0, 1)], now);
        queues.push(key("a"), 2, vec![message("a", 0, 2)], now);

        let runs = take_all(&mut queues, now);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].class.assignment_epoch, 1);
        assert_eq!(offsets(&runs[0].run.messages), vec![1]);
    }

    #[test]
    fn a_revoke_drops_queued_messages_and_requeued_messages_of_the_partition() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 1, 7)],
            now,
        );
        take_all(&mut queues, now);
        queues.push(key("a"), 0, vec![message("a", 0, 2)], now);
        queues.push(key("b"), 0, vec![message("b", 0, 5)], now);

        let evicted = queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(evicted, vec![Arc::<str>::from("b")]);
        assert_eq!(queues.queued_messages(), 0);

        let requeued = vec![message("a", 0, 1), message("a", 1, 7)];
        queues
            .settle(&key("a"), requeued, None, now)
            .expect("claimed");
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![7], true)],
            "only the message of the kept partition returns"
        );
    }

    #[test]
    fn a_revoke_that_drops_the_requeued_messages_ends_their_wait() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        take_all(&mut queues, now);
        queues.push(key("a"), 0, vec![message("a", 1, 7)], now);
        let retry_at = now + Duration::from_millis(100);
        queues
            .settle(&key("a"), vec![message("a", 0, 1)], Some(retry_at), now)
            .expect("claimed");

        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.next_retry_at(), None);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![7], false)]
        );
    }

    #[test]
    fn a_settle_without_a_claim_is_an_error() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        assert!(queues
            .settle(&key("a"), vec![message("a", 0, 1)], None, now)
            .is_err());
        assert_eq!(queues.queued_messages(), 1);
    }

    #[test]
    fn a_key_split_over_groups_is_one_run_and_an_unkeyed_group_gets_its_own_key() {
        let group = |partition: i32, key: Option<&str>, offsets: &[i64]| Group {
            partition: Partition(partition),
            key: key.map(str::to_string),
            messages: offsets
                .iter()
                .map(|&offset| GroupMessage {
                    offset: Offset(offset),
                    message: SerializedKafkaMessage {
                        key: key.map(str::to_string),
                        ..message("unused", partition, offset)
                    },
                })
                .collect(),
        };
        let runs = KeyRun::from_groups(vec![
            group(0, Some("a"), &[1]),
            group(1, None, &[5]),
            group(2, Some("a"), &[7]),
        ]);
        let shapes: Vec<_> = runs
            .iter()
            .map(|run| (&*run.routing_key, offsets(&run.messages)))
            .collect();
        assert_eq!(shapes, vec![("a", vec![1, 7]), (":1:5", vec![5])]);
    }

    #[test]
    fn pushes_of_one_class_before_a_claim_share_one_segment_and_leave_as_one_run() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        queues.push(key("a"), 0, vec![message("a", 0, 2)], now);
        assert_eq!(queues.keys[&key("a")].segments.len(), 1);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![1, 2], false)]
        );
    }

    #[test]
    fn queued_bytes_follow_messages_through_claim_requeue_and_purge() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 1, 2)],
            now,
        );
        take_all(&mut queues, now);
        assert_eq!(queues.queued_bytes(), 0);

        let requeued = vec![message("a", 0, 1), message("a", 1, 2)];
        let requeued_bytes = payload_bytes(&requeued);
        queues
            .settle(&key("a"), requeued, None, now)
            .expect("claimed");
        assert_eq!(queues.queued_bytes(), requeued_bytes);

        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.queued_bytes(), message("a", 1, 2).payload_bytes());
    }

    #[test]
    fn repeated_failures_keep_one_replay_segment_ahead_of_every_later_arrival() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        let failed = || vec![message("a", 0, 1), message("a", 0, 2)];
        queues.push(key("a"), 0, failed(), now);
        take_all(&mut queues, now);
        queues.push(key("a"), 0, vec![message("a", 0, 3)], now);
        queues
            .settle(&key("a"), failed(), None, now)
            .expect("claimed");
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![1, 2], true)]
        );

        queues.push(key("a"), 0, vec![message("a", 0, 4)], now);
        queues
            .settle(&key("a"), failed(), None, now)
            .expect("claimed");
        assert_eq!(queues.queued_messages(), 4);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![1, 2], true)]
        );
        queues
            .settle(&key("a"), Vec::new(), None, now)
            .expect("claimed");
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![3, 4], false)]
        );
        assert_eq!(queues.settle(&key("a"), Vec::new(), None, now), Ok(true));
        assert_eq!(queues.queued_messages(), 0);
        assert_eq!(queues.queued_bytes(), 0);
    }

    #[test]
    fn a_key_evicted_by_a_purge_and_pushed_again_is_claimed_once() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 0, vec![message("a", 0, 1)], now);
        queues.push(key("a"), 0, vec![message("a", 0, 2)], now);
        assert_eq!(
            queues.purge(&[("events".to_string(), 0)]),
            vec![Arc::<str>::from("a")]
        );

        queues.push(key("a"), 0, vec![message("a", 1, 5)], now);
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![5], false)]
        );
        assert_eq!(queues.claimed_keys(), 1);
        assert!(take_all(&mut queues, now).is_empty());
    }

    #[test]
    fn a_double_purge_does_not_double_count() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(
            key("a"),
            0,
            vec![message("a", 0, 1), message("a", 1, 2)],
            now,
        );
        queues.purge(&[("events".to_string(), 0)]);
        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.queued_messages(), 1);
        assert_eq!(queues.queued_bytes(), message("a", 1, 2).payload_bytes());
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![2], false)]
        );
    }

    #[test]
    fn a_partially_revoked_requeue_keeps_waiting_for_its_retry() {
        let now = Instant::now();
        let retry_at = now + Duration::from_millis(100);
        let mut queues = KeyQueues::default();
        let spanning = || vec![message("a", 0, 1), message("a", 1, 7)];
        queues.push(key("a"), 0, spanning(), now);
        take_all(&mut queues, now);
        queues
            .settle(&key("a"), spanning(), Some(retry_at), now)
            .expect("claimed");

        queues.purge(&[("events".to_string(), 0)]);
        assert_eq!(queues.next_retry_at(), Some(retry_at));
        assert!(take_all(&mut queues, now).is_empty());
        assert_eq!(
            claimed(&take_all(&mut queues, retry_at)),
            vec![("a", vec![7], true)]
        );
    }

    #[test]
    fn ready_sizes_count_each_ready_keys_next_run_only() {
        let now = Instant::now();
        let epoch = |assignment_epoch| RequestClass {
            assignment_epoch,
            replay: false,
        };
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 1, vec![message("a", 0, 1)], now);
        queues.push(key("a"), 2, vec![message("a", 0, 2)], now);
        queues.push(key("b"), 1, vec![message("b", 0, 3)], now);
        let size = |messages| ReadySize {
            messages,
            bytes: message("a", 0, 1).payload_bytes() * messages,
        };
        assert_eq!(queues.ready_sizes(), &[(epoch(1), size(2))]);

        queues.take_runs(epoch(1), |_| false);
        assert!(!queues.has_ready(), "a's epoch-2 run waits for its claim");

        queues
            .settle(&key("a"), Vec::new(), None, now)
            .expect("claimed");
        assert_eq!(queues.ready_sizes(), &[(epoch(2), size(1))]);
    }

    #[test]
    fn a_take_of_one_class_leaves_other_classes_in_their_turn() {
        let now = Instant::now();
        let mut queues = KeyQueues::default();
        queues.push(key("a"), 2, vec![message("a", 0, 1)], now);
        queues.push(key("b"), 1, vec![message("b", 0, 2)], now);
        queues.push(key("c"), 2, vec![message("c", 0, 3)], now);

        let older_epoch = RequestClass {
            assignment_epoch: 1,
            replay: false,
        };
        assert_eq!(
            claimed(&queues.take_runs(older_epoch, |_| false)),
            vec![("b", vec![2], false)]
        );
        assert_eq!(
            claimed(&take_all(&mut queues, now)),
            vec![("a", vec![1], false), ("c", vec![3], false)]
        );
    }

    #[test]
    fn a_push_past_the_run_cap_starts_a_new_segment_and_runs_leave_in_order() {
        let now = Instant::now();
        let mut queues = KeyQueues::new(RunCap {
            messages: NonZeroUsize::new(2),
            bytes: None,
        });
        let messages = |offsets: &[i64]| offsets.iter().map(|&o| message("a", 0, o)).collect();
        queues.push(key("a"), 0, messages(&[1, 2, 3]), now);
        queues.push(key("a"), 0, messages(&[4, 5]), now);
        assert_eq!(queues.keys[&key("a")].segments.len(), 3);

        for expected in [vec![1, 2], vec![3, 4], vec![5]] {
            assert_eq!(
                claimed(&take_all(&mut queues, now)),
                vec![("a", expected, false)]
            );
            queues
                .settle(&key("a"), Vec::new(), None, now)
                .expect("claimed");
        }
    }
}
