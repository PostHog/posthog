use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::{Offset, Partition, TopicPartition};

use super::poll::InFlightPoll;
use crate::debug_recorder::{DebugEventKind, DebugRecorder, PartitionOffset};

pub(super) struct CompletedPolls {
    recorder: Arc<DebugRecorder>,
    // Counted per poll: polls finish in any order, and the partition frontier
    // passes a finished poll only when every earlier poll is finished too.
    polls: HashMap<u64, PendingPoll>,
    next_poll: u64,
    /// Keyed by partition number, because a completion carries no topic.
    slices: HashMap<Partition, BTreeMap<i64, PollSlice>>,
}

struct PendingPoll {
    poll_id: String,
    dispatched_at: Instant,
    messages: u32,
    unsettled: u32,
    partitions: Vec<PartitionOffset>,
    slice_starts: Vec<(Partition, i64)>,
}

struct PollSlice {
    last: i64,
    poll: u64,
    messages: u32,
    unsettled: u32,
}

impl CompletedPolls {
    pub(super) fn new(recorder: Arc<DebugRecorder>) -> Self {
        Self {
            recorder,
            polls: HashMap::new(),
            next_poll: 0,
            slices: HashMap::new(),
        }
    }

    pub(super) fn submitted(&mut self, poll: &InFlightPoll) {
        let key = self.next_poll;
        let mut pending = PendingPoll {
            poll_id: poll.poll_id.clone(),
            dispatched_at: poll.dispatched_at,
            messages: 0,
            unsettled: 0,
            partitions: Vec::new(),
            slice_starts: Vec::new(),
        };
        for (topic_partition, deliveries) in &poll.partitions {
            // A rejected charge never settles.
            if !poll.uncommitted.contains_key(topic_partition) {
                continue;
            }
            let partition = Partition(topic_partition.partition);
            pending.messages += deliveries.delivered;
            pending.partitions.push(PartitionOffset {
                topic: topic_partition.topic.clone(),
                partition: topic_partition.partition,
                offset: deliveries.span.last,
                lag_ms: deliveries.max_lag_ms.unwrap_or(0),
            });
            pending
                .slice_starts
                .push((partition, deliveries.span.first));
            self.slices.entry(partition).or_default().insert(
                deliveries.span.first,
                PollSlice {
                    last: deliveries.span.last,
                    poll: key,
                    messages: deliveries.delivered,
                    unsettled: deliveries.delivered,
                },
            );
        }
        if pending.messages == 0 {
            return;
        }
        pending.unsettled = pending.messages;
        self.polls.insert(key, pending);
        self.next_poll += 1;
    }

    pub(super) fn settled(&mut self, partition: Partition, offsets: &[Offset]) {
        let Some(slices) = self.slices.get_mut(&partition) else {
            return;
        };
        // The ledger fails a second settle of an offset, so no offset counts twice.
        let mut done = Vec::new();
        for offset in offsets {
            let Some((_, slice)) = slices.range_mut(..=offset.0).next_back() else {
                continue;
            };
            if slice.last < offset.0 || slice.unsettled == 0 {
                continue;
            }
            slice.unsettled -= 1;
            let Some(poll) = self.polls.get_mut(&slice.poll) else {
                continue;
            };
            poll.unsettled -= 1;
            if poll.unsettled == 0 {
                done.push(slice.poll);
            }
        }
        for key in done {
            self.complete(key);
        }
    }

    pub(super) fn revoked(&mut self, topic_partitions: &[TopicPartition]) {
        let mut done = Vec::new();
        for topic_partition in topic_partitions {
            let Some(slices) = self.slices.remove(&Partition(topic_partition.partition)) else {
                continue;
            };
            for slice in slices.into_values() {
                let Some(poll) = self.polls.get_mut(&slice.poll) else {
                    continue;
                };
                poll.messages -= slice.messages;
                poll.unsettled -= slice.unsettled;
                poll.partitions
                    .retain(|partition| partition.partition != topic_partition.partition);
                if poll.unsettled == 0 {
                    done.push(slice.poll);
                }
            }
        }
        for key in done {
            self.complete(key);
        }
    }

    fn complete(&mut self, key: u64) {
        let Some(poll) = self.polls.remove(&key) else {
            return;
        };
        // After a revoke, the next assignment's poll can start at the same offset.
        for (partition, first) in &poll.slice_starts {
            if let Some(slices) = self.slices.get_mut(partition) {
                if slices.get(first).is_some_and(|slice| slice.poll == key) {
                    slices.remove(first);
                }
            }
        }
        if poll.messages == 0 {
            return;
        }
        self.recorder.record(DebugEventKind::PollCompleted {
            batch_id: poll.poll_id,
            accepted: poll.messages,
            duration_ms: poll.dispatched_at.elapsed().as_millis() as u64,
            partitions: poll.partitions,
        });
    }
}
