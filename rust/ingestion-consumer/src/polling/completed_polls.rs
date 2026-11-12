use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::{Offset, TopicPartition};

use super::poll::{InFlightPoll, PartitionDeliveries};
use crate::debug_recorder::{DebugEventKind, DebugRecorder, PartitionOffset};

type PollKey = u64;

// Not the partition frontier: polls finish in any order, and the frontier
// passes a poll only after every earlier poll on the partition finishes.
pub(super) struct CompletedPolls {
    recorder: Arc<DebugRecorder>,
    polls: HashMap<PollKey, PendingPoll>,
    next_poll: PollKey,
    partitions: HashMap<TopicPartition, PartitionShares>,
}

impl CompletedPolls {
    pub(super) fn new(recorder: Arc<DebugRecorder>) -> Self {
        Self {
            recorder,
            polls: HashMap::new(),
            next_poll: 0,
            partitions: HashMap::new(),
        }
    }

    pub(super) fn record_poll(&mut self, poll: &InFlightPoll) {
        // A rejected charge never settles.
        let charged: Vec<_> = poll
            .partitions
            .iter()
            .filter(|(topic_partition, deliveries)| {
                deliveries.delivered > 0 && poll.uncommitted.contains_key(*topic_partition)
            })
            .collect();
        if charged.is_empty() {
            return;
        }
        let key = self.next_poll;
        self.next_poll += 1;
        for &(topic_partition, deliveries) in &charged {
            self.partitions
                .entry(topic_partition.clone())
                .or_default()
                .add(PartitionShare::new(key, deliveries));
        }
        self.polls.insert(key, PendingPoll::new(poll, &charged));
    }

    pub(super) fn settled(&mut self, topic_partition: &TopicPartition, offsets: &[Offset]) {
        let Some(shares) = self.partitions.get_mut(topic_partition) else {
            return;
        };
        let mut done = Vec::new();
        // The ledger fails a second settle of an offset, so no offset counts twice.
        for &offset in offsets {
            let Some(share) = shares.share_of(offset).filter(|share| !share.is_settled()) else {
                continue;
            };
            share.settle_one();
            let Some(poll) = self.polls.get_mut(&share.poll) else {
                continue;
            };
            poll.settle_one();
            if poll.is_settled() {
                done.push(share.poll);
            }
        }
        for key in done {
            self.complete(key);
        }
    }

    pub(super) fn forget(&mut self, topic_partitions: &[TopicPartition]) {
        let mut done = Vec::new();
        for topic_partition in topic_partitions {
            let Some(shares) = self.partitions.remove(topic_partition) else {
                continue;
            };
            for share in shares.into_shares() {
                let Some(poll) = self.polls.get_mut(&share.poll) else {
                    continue;
                };
                poll.leave(topic_partition, &share);
                if poll.is_settled() {
                    done.push(share.poll);
                }
            }
        }
        for key in done {
            self.complete(key);
        }
    }

    fn complete(&mut self, key: PollKey) {
        let Some(poll) = self.polls.remove(&key) else {
            return;
        };
        for (topic_partition, first) in &poll.share_starts {
            if let Some(shares) = self.partitions.get_mut(topic_partition) {
                shares.remove(*first, key);
            }
        }
        if let Some(event) = poll.into_event() {
            self.recorder.record(event);
        }
    }
}

struct PendingPoll {
    poll_id: String,
    dispatched_at: Instant,
    messages: u32,
    unsettled: u32,
    partitions: Vec<PartitionOffset>,
    share_starts: Vec<(TopicPartition, i64)>,
}

impl PendingPoll {
    fn new(poll: &InFlightPoll, charged: &[(&TopicPartition, &PartitionDeliveries)]) -> Self {
        let messages = charged
            .iter()
            .map(|(_, deliveries)| deliveries.delivered)
            .sum();
        Self {
            poll_id: poll.poll_id.clone(),
            dispatched_at: poll.dispatched_at,
            messages,
            unsettled: messages,
            partitions: charged
                .iter()
                .map(|&(topic_partition, deliveries)| PartitionOffset {
                    topic: topic_partition.topic.clone(),
                    partition: topic_partition.partition,
                    offset: deliveries.span.last,
                    lag_ms: deliveries.max_lag_ms.unwrap_or(0),
                })
                .collect(),
            share_starts: charged
                .iter()
                .map(|&(topic_partition, deliveries)| {
                    (topic_partition.clone(), deliveries.span.first)
                })
                .collect(),
        }
    }

    fn settle_one(&mut self) {
        self.unsettled -= 1;
    }

    fn is_settled(&self) -> bool {
        self.unsettled == 0
    }

    fn leave(&mut self, topic_partition: &TopicPartition, share: &PartitionShare) {
        self.messages -= share.messages;
        self.unsettled -= share.unsettled;
        self.partitions.retain(|partition| {
            partition.partition != topic_partition.partition
                || partition.topic != topic_partition.topic
        });
    }

    fn into_event(self) -> Option<DebugEventKind> {
        (self.messages > 0).then(|| DebugEventKind::PollCompleted {
            batch_id: self.poll_id,
            accepted: self.messages,
            duration_ms: self.dispatched_at.elapsed().as_millis() as u64,
            partitions: self.partitions,
        })
    }
}

struct PartitionShare {
    poll: PollKey,
    first: i64,
    last: i64,
    messages: u32,
    unsettled: u32,
}

impl PartitionShare {
    fn new(poll: PollKey, deliveries: &PartitionDeliveries) -> Self {
        Self {
            poll,
            first: deliveries.span.first,
            last: deliveries.span.last,
            messages: deliveries.delivered,
            unsettled: deliveries.delivered,
        }
    }

    fn contains(&self, offset: Offset) -> bool {
        (self.first..=self.last).contains(&offset.0)
    }

    fn settle_one(&mut self) {
        self.unsettled -= 1;
    }

    fn is_settled(&self) -> bool {
        self.unsettled == 0
    }
}

#[derive(Default)]
struct PartitionShares {
    by_first: BTreeMap<i64, PartitionShare>,
}

impl PartitionShares {
    fn add(&mut self, share: PartitionShare) {
        self.by_first.insert(share.first, share);
    }

    /// Shares never overlap: the ledger rejects a charge that is not above
    /// every offset charged before it in the same generation.
    fn share_of(&mut self, offset: Offset) -> Option<&mut PartitionShare> {
        self.by_first
            .range_mut(..=offset.0)
            .next_back()
            .map(|(_, share)| share)
            .filter(|share| share.contains(offset))
    }

    /// After a revoke or an assignment, a new poll's share can start at the
    /// same offset, so only the given poll's share is removed.
    fn remove(&mut self, first: i64, poll: PollKey) {
        if self
            .by_first
            .get(&first)
            .is_some_and(|share| share.poll == poll)
        {
            self.by_first.remove(&first);
        }
    }

    fn into_shares(self) -> impl Iterator<Item = PartitionShare> {
        self.by_first.into_values()
    }
}
