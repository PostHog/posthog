//! The consumer's ledger over submitted polls: which offsets each poll
//! delivered per partition, how many of them completions have covered and
//! accepted, and which partitions a rebalance took away. The consumer loop
//! pushes a poll after submitting it to the batcher, credits completions as
//! they arrive, strips revoked partitions, and pops the oldest poll once it
//! is covered.

use std::collections::{HashMap, VecDeque};
use std::time::Instant;

use common_kafka_consumer::{Charge, GroupCompletion, Offset, TopicPartition};
use metrics::counter;
use tracing::warn;

use crate::order_sentinel::OffsetSpan;

/// One delivered message, as the batch records it against its partition.
pub struct Delivery {
    pub offset: i64,
    pub charge: Charge,
    /// Kafka message timestamp (ms).
    pub kafka_ts: i64,
    /// Ingestion lag (ms); `None` without a parseable `now` header.
    pub lag_ms: Option<i64>,
}

/// What a batch saw delivered from one partition, folded in one map entry
/// per message. The span bounds what the batch delivered; the stamped
/// charges feed the ledger.
pub struct PartitionDeliveries {
    /// The offsets the batch delivered, first to last.
    pub span: OffsetSpan,
    /// Ledger generation the charges are stamped with.
    pub generation: u64,
    /// Ledger generations version seen when the charges were last stamped.
    /// Comparing it per message is cheaper than reading the generation.
    pub generations_version_seen: u64,
    /// The slice charged to the ledger: offsets delivered under `generation`.
    pub charges: Vec<(Offset, Charge)>,
    /// Max Kafka message timestamp (ms) — for `latest_processed_timestamp_ms`.
    pub latest_kafka_ts: i64,
    /// Max ingestion lag (ms) — for `ingestion_lag_ms`.
    pub max_lag_ms: Option<i64>,
    /// Messages the poll delivered, covered, and accepted from this
    /// partition, so a revoked partition can leave the poll exactly.
    pub delivered: u32,
    pub covered: u32,
    pub accepted: u32,
}

impl PartitionDeliveries {
    pub fn new(generation: u64, generations_version: u64, delivery: &Delivery) -> Self {
        Self {
            span: OffsetSpan::new(delivery.offset),
            generation,
            generations_version_seen: generations_version,
            charges: vec![(Offset(delivery.offset), delivery.charge)],
            latest_kafka_ts: delivery.kafka_ts,
            max_lag_ms: delivery.lag_ms,
            delivered: 1,
            covered: 0,
            accepted: 0,
        }
    }

    /// Record one more delivery. `generation` is consulted only when
    /// `generations_version` moved since the last stamp. A moved generation
    /// means the partition was revoked and regained inside this batch: the
    /// offsets buffered so far belong to the old assignment and Kafka
    /// redelivers them, so the ledger slice restarts. The span keeps them,
    /// so the commit sentinel still sees the whole delivered range.
    pub fn record(
        &mut self,
        generations_version: u64,
        generation: impl FnOnce() -> u64,
        delivery: &Delivery,
    ) {
        self.span.extend(delivery.offset);
        self.delivered += 1;
        self.latest_kafka_ts = self.latest_kafka_ts.max(delivery.kafka_ts);
        if let Some(lag_ms) = delivery.lag_ms {
            self.max_lag_ms = Some(self.max_lag_ms.map_or(lag_ms, |max| max.max(lag_ms)));
        }
        if generations_version != self.generations_version_seen {
            self.generations_version_seen = generations_version;
            let generation = generation();
            if generation != self.generation {
                self.generation = generation;
                self.charges.clear();
            }
        }
        self.charges
            .push((Offset(delivery.offset), delivery.charge));
    }
}

/// One submitted poll, awaiting its group completions. The consumer
/// correlates completions to it by assignment epoch, partition, and offset;
/// the poll commits only once completions cover every message.
pub struct InFlightPoll {
    /// Consumer-side id for logs and debug events only; the batcher's
    /// internal batch id never crosses the boundary.
    pub poll_id: String,
    /// The epoch the batcher stamped on this poll's completions.
    pub assignment_epoch: u64,
    pub partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub message_count: u32,
    /// Messages covered by completions so far, accepted or not.
    pub covered: u32,
    /// Worker-accepted messages so far. The poll commits only when this
    /// reaches `message_count`.
    pub accepted: u32,
    pub dispatched_at: Instant,
}

impl InFlightPoll {
    pub fn is_complete(&self) -> bool {
        self.covered >= self.message_count
    }
}

/// The submitted polls, oldest first.
#[derive(Default)]
pub struct InFlightPolls {
    polls: VecDeque<InFlightPoll>,
}

impl InFlightPolls {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.polls.len()
    }

    pub fn is_empty(&self) -> bool {
        self.polls.is_empty()
    }

    pub fn push(&mut self, poll: InFlightPoll) {
        self.polls.push_back(poll);
    }

    pub fn front(&self) -> Option<&InFlightPoll> {
        self.polls.front()
    }

    pub fn pop_front(&mut self) -> Option<InFlightPoll> {
        self.polls.pop_front()
    }

    /// Remove revoked partitions from the polls, and remove polls left
    /// empty. Only the revoked partitions' slices go: a poll's kept
    /// partitions keep their counts and settle their ledger charges at
    /// commit, so the frontier never crosses a hole. Dropping whole polls
    /// here froze kept partitions' commits under cooperative rebalancing.
    /// Returns the number of messages removed.
    pub fn strip_revoked(&mut self, revoked: &[TopicPartition]) -> u64 {
        let mut stripped: u64 = 0;
        for poll in self.polls.iter_mut() {
            let mut removed_delivered = 0u32;
            let mut removed_covered = 0u32;
            let mut removed_accepted = 0u32;
            poll.partitions.retain(|topic_partition, deliveries| {
                if revoked.contains(topic_partition) {
                    removed_delivered += deliveries.delivered;
                    removed_covered += deliveries.covered;
                    removed_accepted += deliveries.accepted;
                    false
                } else {
                    true
                }
            });
            if removed_delivered > 0 {
                stripped += u64::from(removed_delivered);
                poll.message_count = poll.message_count.saturating_sub(removed_delivered);
                poll.covered = poll.covered.saturating_sub(removed_covered);
                poll.accepted = poll.accepted.saturating_sub(removed_accepted);
            }
        }
        self.polls.retain(|poll| poll.message_count > 0);
        stripped
    }

    /// Credit each of a completion's offsets to the poll that contains it:
    /// the one collected under the same assignment epoch whose span holds
    /// the offset. Within one epoch, poll spans are disjoint per partition,
    /// so at most one poll matches per offset. A key-table run merges
    /// messages from several polls into one send, so one completion can
    /// span polls; crediting per offset keeps every poll's count exact.
    /// Acceptance credits the leading offsets, so a worker that
    /// under-reports shorts the tail poll's accepted check, matching
    /// [`send_group_completions`]'s split across groups. An offset that
    /// matches no poll (its partition was revoked and reassigned while the
    /// group was out, or its poll is gone) is discarded; a completion with
    /// any discarded offset counts as stale once.
    ///
    /// [`send_group_completions`]: crate::batcher
    pub fn apply_completion(&mut self, completion: GroupCompletion) {
        let mut accepted = completion.accepted;
        let mut unmatched: u64 = 0;
        'offsets: for offset in &completion.offsets {
            let is_accepted = accepted > 0;
            accepted = accepted.saturating_sub(1);
            for poll in self
                .polls
                .iter_mut()
                .filter(|poll| poll.assignment_epoch == completion.assignment_epoch)
            {
                for (topic_partition, deliveries) in poll.partitions.iter_mut() {
                    if topic_partition.partition == completion.partition.0
                        && deliveries.span.first <= offset.0
                        && offset.0 <= deliveries.span.last
                    {
                        poll.covered += 1;
                        poll.accepted += u32::from(is_accepted);
                        deliveries.covered += 1;
                        deliveries.accepted += u32::from(is_accepted);
                        continue 'offsets;
                    }
                }
            }
            unmatched += 1;
        }
        if unmatched > 0 {
            counter!("ingestion_consumer_stale_group_completions_total").increment(1);
            warn!(
                partition = %completion.partition,
                unmatched,
                epoch = completion.assignment_epoch,
                "Discarding completion offsets that match no in-flight poll"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_kafka_consumer::{Offset as MessageOffset, Partition};

    fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
        let mut partitions = HashMap::new();
        partitions.insert(
            TopicPartition::new("test", partition),
            PartitionDeliveries {
                span: OffsetSpan { first, last },
                generation: 0,
                generations_version_seen: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: count,
                covered: 0,
                accepted: 0,
            },
        );
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions,
            message_count: count,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        }
    }

    fn polls(polls: impl IntoIterator<Item = InFlightPoll>) -> InFlightPolls {
        InFlightPolls {
            polls: polls.into_iter().collect(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64], accepted: u32) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            offsets: offsets.iter().map(|o| MessageOffset(*o)).collect(),
            accepted,
        }
    }

    #[test]
    fn apply_completion_credits_the_poll_holding_the_offsets() {
        let mut in_flight = polls([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        in_flight.apply_completion(completion(1, 0, &[4, 6], 2));

        assert_eq!(in_flight.polls[0].covered, 0);
        assert_eq!(in_flight.polls[1].covered, 2);
        assert_eq!(in_flight.polls[1].accepted, 2);
        assert!(!in_flight.polls[1].is_complete());

        in_flight.apply_completion(completion(1, 0, &[5, 7], 2));
        assert!(in_flight.polls[1].is_complete());
    }

    #[test]
    fn apply_completion_spanning_two_polls_credits_each() {
        // A key-table run merges messages from consecutive polls into one
        // send, so its completion spans both spans.
        let mut in_flight = polls([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        in_flight.apply_completion(completion(1, 0, &[2, 3, 4, 5], 4));

        assert_eq!(in_flight.polls[0].covered, 2);
        assert_eq!(in_flight.polls[0].accepted, 2);
        assert_eq!(in_flight.polls[1].covered, 2);
        assert_eq!(in_flight.polls[1].accepted, 2);
    }

    #[test]
    fn apply_completion_under_report_shorts_the_tail_poll() {
        let mut in_flight = polls([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        in_flight.apply_completion(completion(1, 0, &[2, 3, 4, 5], 3));

        assert_eq!(
            in_flight.polls[0].accepted, 2,
            "leading offsets are accepted"
        );
        assert_eq!(
            in_flight.polls[1].accepted, 1,
            "the tail poll fails its accepted check"
        );
        assert_eq!(in_flight.polls[1].covered, 2);
    }

    #[test]
    fn strip_revoked_keeps_the_other_partitions_slices() {
        // A cooperative rebalance revokes one partition of a two-partition
        // poll. The kept partition's slice must stay accounted, or its
        // ledger charges never settle and its commits freeze at the hole.
        let mut two = poll(1, 0, 0, 1, 4);
        two.partitions.insert(
            TopicPartition::new("test", 1),
            PartitionDeliveries {
                span: OffsetSpan {
                    first: 10,
                    last: 11,
                },
                generation: 0,
                generations_version_seen: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: 2,
                covered: 0,
                accepted: 0,
            },
        );
        two.partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .delivered = 2;
        let mut in_flight = polls([two]);
        // Partition 1 already had one message covered before the revoke.
        in_flight.apply_completion(completion(1, 1, &[10], 1));

        let stripped = in_flight.strip_revoked(&[TopicPartition::new("test", 1)]);

        assert_eq!(stripped, 2);
        assert_eq!(in_flight.polls[0].message_count, 2);
        assert_eq!(
            in_flight.polls[0].covered, 0,
            "the revoked slice's credit goes"
        );
        assert!(!in_flight.polls[0].is_complete());

        // The kept partition completes the poll; a late completion for the
        // revoked partition is discarded, not credited.
        in_flight.apply_completion(completion(1, 1, &[11], 1));
        assert_eq!(in_flight.polls[0].covered, 0);
        in_flight.apply_completion(completion(1, 0, &[0, 1], 2));
        assert!(in_flight.polls[0].is_complete());
        assert_eq!(in_flight.polls[0].accepted, 2);
    }

    #[test]
    fn strip_revoked_removes_an_emptied_poll() {
        let mut in_flight = polls([poll(1, 0, 0, 3, 4), poll(1, 2, 0, 3, 4)]);

        let stripped = in_flight.strip_revoked(&[TopicPartition::new("test", 0)]);

        assert_eq!(stripped, 4);
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight.polls[0].message_count, 4);
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        // The same offsets exist in two polls when a partition was revoked,
        // reassigned, and replayed. The epoch keeps each incarnation's
        // completions in its own poll.
        let mut in_flight = polls([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        in_flight.apply_completion(completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight.polls[0].covered, 0);
        assert_eq!(in_flight.polls[1].covered, 4);
    }

    #[test]
    fn apply_completion_discards_a_completion_matching_no_poll() {
        let mut in_flight = polls([poll(1, 0, 0, 3, 4)]);

        // Wrong partition, then wrong epoch: neither may be credited.
        in_flight.apply_completion(completion(1, 2, &[1], 1));
        in_flight.apply_completion(completion(9, 0, &[1], 1));

        assert_eq!(in_flight.polls[0].covered, 0);
        assert_eq!(in_flight.polls[0].accepted, 0);
    }
}
