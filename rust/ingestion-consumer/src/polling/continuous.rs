use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::{Charge, GroupCompletion, Offset, TopicPartition};
use metrics::{counter, gauge};
use tracing::warn;

use super::poll::{debug_partition_offsets, InFlightPoll, PartitionDeliveries};
use crate::charge_limit::ChargeLimit;
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::settlement::{Commit, Settlement};

/// Nothing waits on a submitted poll: the partition budget and the in-flight
/// limit bound admission.
pub(crate) struct ContinuousPolling {
    in_flight: InFlight,
    uncommitted: UncommittedCharges,
    limits: ChargeLimit,
    at_limit: bool,
}

impl ContinuousPolling {
    pub(crate) fn new(
        limits: ChargeLimit,
        group_id: String,
        debug_recorder: Option<Arc<DebugRecorder>>,
    ) -> Self {
        Self {
            in_flight: InFlight::new(group_id, debug_recorder),
            uncommitted: UncommittedCharges::default(),
            limits,
            at_limit: false,
        }
    }

    pub(crate) fn admits(&mut self, building: Charge) -> bool {
        let at_limit = self.limits.reached(self.uncommitted.total() + building);
        if at_limit && !self.at_limit {
            counter!("ingestion_consumer_in_flight_limit_reached_total").increment(1);
        }
        self.at_limit = at_limit;
        !at_limit
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.in_flight.is_empty()
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        self.uncommitted.charged(&poll);
        self.in_flight.submitted(poll);
    }

    pub(crate) fn completed(
        &mut self,
        completion: &GroupCompletion,
        settlement: &dyn Settlement,
    ) -> anyhow::Result<()> {
        let processed = self
            .in_flight
            .apply(completion, |topic_partition, generation, run| {
                settlement.settle_run(topic_partition, generation, run)
            })?;
        counter!("ingestion_consumer_messages_processed_total").increment(processed);
        Ok(())
    }

    pub(crate) fn committed(&mut self, commit: &Commit) {
        self.uncommitted.committed(commit);
    }

    /// Returns the messages removed.
    pub(crate) fn revoked(&mut self, topic_partitions: &[TopicPartition]) -> u64 {
        self.uncommitted.revoked(topic_partitions);
        self.in_flight.drop_revoked(topic_partitions)
    }
}

struct Slice {
    poll: u64,
    assignment_epoch: u64,
    deliveries: PartitionDeliveries,
}

impl Slice {
    fn uncovered(&self) -> u32 {
        self.deliveries
            .delivered
            .saturating_sub(self.deliveries.covered)
    }
}

struct InFlight {
    partitions: HashMap<TopicPartition, VecDeque<Slice>>,
    latest_processed_ms: HashMap<TopicPartition, i64>,
    group_id: String,
    next_poll: u64,
    /// Filled only with a debug recorder, for its `PollCompleted` event.
    polls: HashMap<u64, PollProgress>,
    debug_recorder: Option<Arc<DebugRecorder>>,
}

struct PollProgress {
    poll_id: String,
    slices: usize,
    completed_slices: usize,
    accepted: u32,
    dispatched_at: Instant,
    partitions: Vec<PartitionOffset>,
}

impl InFlight {
    fn new(group_id: String, debug_recorder: Option<Arc<DebugRecorder>>) -> Self {
        Self {
            partitions: HashMap::new(),
            latest_processed_ms: HashMap::new(),
            group_id,
            next_poll: 0,
            polls: HashMap::new(),
            debug_recorder,
        }
    }

    fn is_empty(&self) -> bool {
        self.partitions.is_empty()
    }

    fn submitted(&mut self, poll: InFlightPoll) {
        let seq = self.next_poll;
        self.next_poll += 1;
        if self.debug_recorder.is_some() {
            self.polls.insert(
                seq,
                PollProgress {
                    poll_id: poll.poll_id.clone(),
                    slices: poll.partitions.len(),
                    completed_slices: 0,
                    accepted: 0,
                    dispatched_at: poll.dispatched_at,
                    partitions: debug_partition_offsets(&poll.partitions),
                },
            );
        }
        for (topic_partition, deliveries) in poll.partitions {
            self.partitions
                .entry(topic_partition)
                .or_default()
                .push_back(Slice {
                    poll: seq,
                    assignment_epoch: poll.assignment_epoch,
                    deliveries,
                });
        }
    }

    /// Credit each run of a completion's offsets to the oldest slice with the
    /// completion's epoch whose span holds the run, and settle the charged
    /// offsets under that slice's generation. An offset with no slice is
    /// stale: its partition was revoked while the group was out. Returns the
    /// offsets that matched a slice.
    fn apply(
        &mut self,
        completion: &GroupCompletion,
        mut settle: impl FnMut(&TopicPartition, u64, &[Offset]) -> anyhow::Result<()>,
    ) -> anyhow::Result<u64> {
        if (completion.accepted as usize) < completion.offsets.len() {
            anyhow::bail!(
                "accepted {}/{} messages — not committing offsets",
                completion.accepted,
                completion.offsets.len()
            );
        }
        let mut unmatched: u64 = 0;
        let mut remaining = completion.offsets.as_slice();
        while let Some(first) = remaining.first() {
            let found = self
                .partitions
                .iter_mut()
                .filter(|(topic_partition, _)| topic_partition.partition == completion.partition.0)
                .find_map(|(topic_partition, slices)| {
                    let index = slices.iter().position(|slice| {
                        let span = slice.deliveries.span;
                        slice.assignment_epoch == completion.assignment_epoch
                            && span.first <= first.0
                            && first.0 <= span.last
                    })?;
                    Some((topic_partition, slices, index))
                });
            let Some((topic_partition, slices, index)) = found else {
                unmatched += 1;
                remaining = &remaining[1..];
                continue;
            };
            let slice = &mut slices[index];
            let span = slice.deliveries.span;
            let run_len = remaining
                .iter()
                .take_while(|offset| span.first <= offset.0 && offset.0 <= span.last)
                .count();
            let (run, rest) = remaining.split_at(run_len);
            slice.deliveries.covered += run_len as u32;
            slice.deliveries.accepted += run_len as u32;
            let settleable = slice.deliveries.credit_run(run);
            if !settleable.is_empty() {
                settle(topic_partition, slice.deliveries.generation, &settleable)?;
            }
            let mut finished = None;
            if slice.uncovered() == 0 {
                let slice = slices.remove(index).expect("the index is in range");
                finished = Some((slice.poll, slice.deliveries.accepted));
                let latest = self
                    .latest_processed_ms
                    .entry(topic_partition.clone())
                    .or_insert(i64::MIN);
                if slice.deliveries.latest_kafka_ts > *latest {
                    *latest = slice.deliveries.latest_kafka_ts;
                    // Same name as the Node.js consumer's gauge, so one dashboard reads both.
                    gauge!(
                        "latest_processed_timestamp_ms",
                        "topic" => topic_partition.topic.clone(),
                        "partition" => topic_partition.partition.to_string(),
                        "groupId" => self.group_id.clone()
                    )
                    .set(*latest as f64);
                }
                if slices.is_empty() {
                    let topic_partition = topic_partition.clone();
                    self.partitions.remove(&topic_partition);
                }
            }
            if let Some((poll, accepted)) = finished {
                self.slice_finished(poll, Some(accepted));
            }
            remaining = rest;
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
        Ok(completion.offsets.len() as u64 - unmatched)
    }

    /// Returns the messages dropped.
    fn drop_revoked(&mut self, revoked: &[TopicPartition]) -> u64 {
        let mut stripped: u64 = 0;
        let mut dropped_polls = Vec::new();
        for topic_partition in revoked {
            let Some(slices) = self.partitions.remove(topic_partition) else {
                continue;
            };
            for slice in slices {
                stripped += u64::from(slice.deliveries.delivered);
                dropped_polls.push(slice.poll);
            }
        }
        for poll in dropped_polls {
            self.slice_finished(poll, None);
        }
        stripped
    }

    /// A poll completes when its last slice is covered or revoked, as long as
    /// one slice was covered: a poll the revoke emptied completes nothing.
    fn slice_finished(&mut self, poll: u64, accepted: Option<u32>) {
        let Some(progress) = self.polls.get_mut(&poll) else {
            return;
        };
        progress.slices -= 1;
        if let Some(accepted) = accepted {
            progress.completed_slices += 1;
            progress.accepted += accepted;
        }
        if progress.slices > 0 {
            return;
        }
        let progress = self.polls.remove(&poll).expect("the poll is tracked");
        if progress.completed_slices == 0 {
            return;
        }
        record_if(&self.debug_recorder, || DebugEventKind::PollCompleted {
            batch_id: progress.poll_id,
            accepted: progress.accepted,
            duration_ms: progress.dispatched_at.elapsed().as_millis() as u64,
            partitions: progress.partitions,
        });
    }
}

#[derive(Default)]
struct UncommittedCharges {
    partitions: HashMap<TopicPartition, Charge>,
    total: Charge,
}

impl UncommittedCharges {
    fn total(&self) -> Charge {
        self.total
    }

    fn charged(&mut self, poll: &InFlightPoll) {
        for (topic_partition, &charge) in &poll.uncommitted {
            let previous = self.partitions.insert(topic_partition.clone(), charge);
            self.replace(previous, charge);
        }
    }

    fn committed(&mut self, commit: &Commit) {
        for (topic_partition, &charge) in &commit.uncommitted {
            if let Some(partition) = self.partitions.get_mut(topic_partition) {
                let previous = std::mem::replace(partition, charge);
                self.replace(Some(previous), charge);
            }
        }
    }

    fn revoked(&mut self, revoked: &[TopicPartition]) {
        for topic_partition in revoked {
            let previous = self.partitions.remove(topic_partition);
            self.replace(previous, Charge::ZERO);
        }
    }

    fn replace(&mut self, previous: Option<Charge>, charge: Charge) {
        self.total = self.total - previous.unwrap_or(Charge::ZERO) + charge;
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use common_kafka_consumer::{Offset as MessageOffset, Partition};

    use super::*;
    use crate::order_sentinel::OffsetSpan;

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn poll(epoch: u64, partition: i32, generation: u64, first: i64, last: i64) -> InFlightPoll {
        let deliveries = PartitionDeliveries {
            span: OffsetSpan { first, last },
            generation,
            charges: (first..=last)
                .map(|offset| {
                    (
                        MessageOffset(offset),
                        Charge {
                            events: 1,
                            bytes: 10,
                        },
                    )
                })
                .collect(),
            payload_bytes: 0,
            latest_kafka_ts: last,
            max_lag_ms: None,
            delivered: (last - first + 1) as u32,
            covered: 0,
            accepted: 0,
            credited: HashSet::default(),
        };
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions: HashMap::from([(p(partition), deliveries)]),
            uncommitted: HashMap::new(),
            message_count: (last - first + 1) as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: std::time::Instant::now(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64]) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            offsets: offsets
                .iter()
                .map(|&offset| MessageOffset(offset))
                .collect(),
            accepted: offsets.len() as u32,
        }
    }

    fn charge(events: u64, bytes: u64) -> Charge {
        Charge { events, bytes }
    }

    fn settled_runs(
        in_flight: &mut InFlight,
        completion: &GroupCompletion,
    ) -> Vec<(i32, u64, Vec<i64>)> {
        let mut runs = Vec::new();
        in_flight
            .apply(completion, |topic_partition, generation, offsets| {
                runs.push((
                    topic_partition.partition,
                    generation,
                    offsets.iter().map(|offset| offset.0).collect(),
                ));
                Ok(())
            })
            .unwrap();
        runs
    }

    #[test]
    fn a_slice_stays_in_flight_until_completions_cover_it() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));

        assert_eq!(
            settled_runs(&mut in_flight, &completion(1, 0, &[0, 1])),
            vec![(0, 0, vec![0, 1])]
        );
        assert!(!in_flight.is_empty());

        settled_runs(&mut in_flight, &completion(1, 0, &[2, 3]));
        assert!(in_flight.is_empty());
    }

    #[test]
    fn a_completion_spanning_two_polls_settles_each_under_its_generation() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        in_flight.submitted(poll(1, 0, 1, 4, 7));

        assert_eq!(
            settled_runs(&mut in_flight, &completion(1, 0, &[2, 3, 4, 5])),
            vec![(0, 0, vec![2, 3]), (0, 1, vec![4, 5])]
        );
    }

    #[test]
    fn a_completion_from_another_epoch_settles_nothing() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(2, 0, 1, 0, 3));

        let processed = in_flight
            .apply(&completion(1, 0, &[0, 1, 2, 3]), |_, _, _| {
                panic!("a stale completion settles nothing")
            })
            .unwrap();
        assert_eq!(processed, 0);
        assert!(!in_flight.is_empty());
    }

    #[test]
    fn a_completion_a_worker_did_not_accept_in_full_is_an_error() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        let mut short = completion(1, 0, &[0, 1]);
        short.accepted = 1;

        let error = in_flight
            .apply(&short, |_, _, _| Ok(()))
            .expect_err("a dropped message must not commit");
        assert!(error.to_string().contains("accepted 1/2"), "{error}");
    }

    #[test]
    fn a_revoke_drops_only_the_revoked_partitions_slices() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        in_flight.submitted(poll(1, 1, 0, 10, 11));
        in_flight.submitted(poll(1, 0, 0, 4, 5));
        settled_runs(&mut in_flight, &completion(1, 0, &[0]));

        let stripped = in_flight.drop_revoked(&[p(0)]);

        assert_eq!(stripped, 6);
        assert!(
            settled_runs(&mut in_flight, &completion(1, 0, &[1, 2, 3])).is_empty(),
            "a late completion for the revoked slice is stale"
        );
        assert_eq!(
            settled_runs(&mut in_flight, &completion(1, 1, &[10, 11])),
            vec![(1, 0, vec![10, 11])]
        );
    }

    fn charged_poll(partition: i32, uncommitted: Charge) -> InFlightPoll {
        let mut poll = poll(1, partition, 0, 0, 0);
        poll.uncommitted = HashMap::from([(p(partition), uncommitted)]);
        poll
    }

    fn commit_leaving(partition: i32, uncommitted: Charge) -> Commit {
        Commit {
            offsets: HashMap::new(),
            uncommitted: HashMap::from([(p(partition), uncommitted)]),
            resume: Vec::new(),
        }
    }

    #[test]
    fn the_uncommitted_total_follows_each_partitions_latest_charge() {
        let mut uncommitted = UncommittedCharges::default();
        uncommitted.charged(&charged_poll(0, charge(4, 40)));
        uncommitted.charged(&charged_poll(1, charge(2, 20)));
        uncommitted.charged(&charged_poll(0, charge(6, 60)));
        assert_eq!(uncommitted.total(), charge(8, 80));

        uncommitted.committed(&commit_leaving(0, charge(1, 10)));
        assert_eq!(uncommitted.total(), charge(3, 30));
    }

    #[test]
    fn a_revoke_releases_the_partitions_charge() {
        let mut uncommitted = UncommittedCharges::default();
        uncommitted.charged(&charged_poll(0, charge(4, 40)));
        uncommitted.charged(&charged_poll(1, charge(2, 20)));

        uncommitted.revoked(&[p(0), p(2)]);

        assert_eq!(uncommitted.total(), charge(2, 20));
    }

    fn completed_polls(recorder: &DebugRecorder) -> Vec<(String, u32)> {
        recorder
            .backlog()
            .into_iter()
            .filter_map(|event| match event.kind {
                DebugEventKind::PollCompleted {
                    batch_id, accepted, ..
                } => Some((batch_id, accepted)),
                _ => None,
            })
            .collect()
    }

    fn two_partition_poll() -> InFlightPoll {
        let mut both = poll(1, 0, 0, 0, 1);
        both.partitions.extend(poll(1, 1, 0, 10, 11).partitions);
        both
    }

    #[test]
    fn a_poll_completes_for_the_debug_ui_once_its_last_slice_is_covered() {
        let recorder = DebugRecorder::new(100, std::time::Duration::from_secs(60));
        let mut in_flight = InFlight::new("test".into(), Some(Arc::clone(&recorder)));
        in_flight.submitted(two_partition_poll());

        settled_runs(&mut in_flight, &completion(1, 0, &[0, 1]));
        assert!(
            completed_polls(&recorder).is_empty(),
            "partition 1 is still in flight"
        );

        settled_runs(&mut in_flight, &completion(1, 1, &[10, 11]));
        assert_eq!(
            completed_polls(&recorder),
            vec![("poll-1-0-0".to_string(), 4)]
        );
    }

    #[test]
    fn a_revoked_slice_ends_its_poll_without_counting_as_accepted() {
        let recorder = DebugRecorder::new(100, std::time::Duration::from_secs(60));
        let mut in_flight = InFlight::new("test".into(), Some(Arc::clone(&recorder)));
        in_flight.submitted(two_partition_poll());
        in_flight.submitted(poll(1, 2, 0, 20, 21));

        settled_runs(&mut in_flight, &completion(1, 0, &[0, 1]));
        in_flight.drop_revoked(&[p(1), p(2)]);

        assert_eq!(
            completed_polls(&recorder),
            vec![("poll-1-0-0".to_string(), 2)],
            "the poll the revoke emptied completes nothing"
        );
    }
}
