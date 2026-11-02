use std::collections::{HashMap, VecDeque};
use std::sync::Arc;

use common_kafka_consumer::{GroupCompletion, Offset, TopicPartition};
use metrics::{counter, gauge};
use rdkafka::message::Message;
use tokio::time::Instant;
use tracing::warn;

use super::poll::{debug_partition_offsets, InFlightPoll, PartitionDeliveries};
use super::{report_revoked, Collector, Parts, PollingStrategy, Step};
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder};
use crate::settlement::Settlement;

/// Admits up to `max_in_flight_polls` polls, and frees a slot only when the
/// oldest poll is covered.
pub(crate) struct CappedPolling {
    collector: Collector,
    settlement: Arc<dyn Settlement>,
    max_in_flight_polls: usize,
    in_flight_polls: VecDeque<InFlightPoll>,
    accepting_new_batches: bool,
    commit_due: bool,
    group_id: String,
    debug_recorder: Option<Arc<DebugRecorder>>,
}

impl CappedPolling {
    pub(crate) fn new(parts: Parts, max_in_flight_polls: usize) -> Self {
        Self {
            collector: Collector::new(parts.limits),
            settlement: parts.settlement,
            max_in_flight_polls: max_in_flight_polls.max(1),
            in_flight_polls: VecDeque::new(),
            accepting_new_batches: true,
            commit_due: false,
            group_id: parts.group_id,
            debug_recorder: parts.debug_recorder,
        }
    }
}

impl PollingStrategy for CappedPolling {
    fn reading(&mut self) -> bool {
        self.accepting_new_batches && self.in_flight_polls.len() < self.max_in_flight_polls
    }

    fn deadline(&self) -> Option<Instant> {
        self.collector.deadline()
    }

    fn received<M: Message>(&mut self, message: &M, now: Instant) {
        self.collector.add(message, now);
    }

    fn completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()> {
        let settlement = &*self.settlement;
        apply_completion(
            &mut self.in_flight_polls,
            completion,
            |tp, generation, run| settlement.settle_run(tp, generation, run).map(drop),
        )?;
        self.commit_due = true;
        Ok(())
    }

    fn ticked(&mut self) {
        self.commit_due = true;
    }

    fn revoked(&mut self, topic_partitions: &[TopicPartition]) {
        let building = self.collector.remove_partitions(topic_partitions) as u64;
        let in_flight = strip_revoked_partitions(&mut self.in_flight_polls, topic_partitions);
        self.report_in_flight();
        report_revoked(building + in_flight);
    }

    fn shutdown(&mut self) {
        self.accepting_new_batches = false;
        self.collector.discard();
    }

    fn submitted(&mut self, poll: InFlightPoll) {
        self.in_flight_polls.push_back(poll);
        self.report_in_flight();
    }

    fn next_step(&mut self, now: Instant) -> Option<Step> {
        while self
            .in_flight_polls
            .front()
            .is_some_and(InFlightPoll::is_complete)
        {
            if let Err(err) = self.retire_oldest_poll() {
                return Some(Step::Fail(err));
            }
            self.commit_due = true;
        }
        if std::mem::take(&mut self.commit_due) {
            if let Some(commit) = self.settlement.take_due(now.into_std()) {
                return Some(Step::Commit(commit));
            }
        }
        if let Some(collected) = self.collector.take_ready(now) {
            return Some(Step::Submit(collected));
        }
        (!self.accepting_new_batches && self.in_flight_polls.is_empty()).then_some(Step::Stop)
    }
}

impl CappedPolling {
    fn retire_oldest_poll(&mut self) -> anyhow::Result<()> {
        let poll = pop_committable(&mut self.in_flight_polls)?;
        self.report_in_flight();
        self.settlement.settle_poll(&poll.charged_slices())?;
        emit_latest_processed_timestamp_metrics(&poll.partitions, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::PollCompleted {
            batch_id: poll.poll_id.clone(),
            accepted: poll.accepted,
            duration_ms: poll.dispatched_at.elapsed().as_millis() as u64,
            partitions: debug_partition_offsets(&poll.partitions),
        });
        counter!("ingestion_consumer_messages_processed_total").increment(poll.accepted as u64);
        counter!("ingestion_consumer_batches_processed_total").increment(1);
        Ok(())
    }

    fn report_in_flight(&self) {
        gauge!("ingestion_consumer_in_flight_batches").set(self.in_flight_polls.len() as f64);
    }
}

/// Keeps the other partitions' slices: a dropped slice never settles, and
/// its partition's commits stop at that hole.
fn strip_revoked_partitions(
    in_flight_polls: &mut VecDeque<InFlightPoll>,
    revoked: &[TopicPartition],
) -> u64 {
    let mut stripped: u64 = 0;
    for poll in in_flight_polls.iter_mut() {
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
    in_flight_polls.retain(|poll| poll.message_count > 0);
    stripped
}

/// A key-table run can merge several polls into one send, so a completion
/// can span polls. Within one epoch, spans are disjoint per partition, so an
/// offset matches at most one poll.
fn apply_completion(
    in_flight: &mut VecDeque<InFlightPoll>,
    completion: &GroupCompletion,
    mut settle: impl FnMut(&TopicPartition, u64, &[Offset]) -> anyhow::Result<()>,
) -> anyhow::Result<()> {
    let fully_accepted = completion.accepted as usize == completion.offsets.len();
    let mut accepted = completion.accepted;
    let mut unmatched: u64 = 0;
    let mut remaining = completion.offsets.as_slice();
    'runs: while let Some(first) = remaining.first() {
        for poll in in_flight
            .iter_mut()
            .filter(|poll| poll.assignment_epoch == completion.assignment_epoch)
        {
            for (topic_partition, deliveries) in poll.partitions.iter_mut() {
                let span = deliveries.span;
                if topic_partition.partition != completion.partition.0
                    || first.0 < span.first
                    || span.last < first.0
                {
                    continue;
                }
                let run_len = remaining
                    .iter()
                    .take_while(|offset| span.first <= offset.0 && offset.0 <= span.last)
                    .count();
                let (run, rest) = remaining.split_at(run_len);
                let run_accepted = accepted.min(run_len as u32);
                accepted -= run_accepted;
                poll.covered += run_len as u32;
                poll.accepted += run_accepted;
                deliveries.covered += run_len as u32;
                deliveries.accepted += run_accepted;
                let settleable = deliveries.credit_run(run);
                if fully_accepted && !settleable.is_empty() {
                    settle(topic_partition, deliveries.generation, &settleable)?;
                }
                remaining = rest;
                continue 'runs;
            }
        }
        unmatched += 1;
        remaining = &remaining[1..];
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
    Ok(())
}

fn pop_committable(in_flight: &mut VecDeque<InFlightPoll>) -> anyhow::Result<InFlightPoll> {
    let poll = in_flight.pop_front().expect("front is present");
    if poll.accepted < poll.message_count {
        anyhow::bail!(
            "accepted {}/{} messages — not committing offsets",
            poll.accepted,
            poll.message_count
        );
    }
    if let Some((topic_partition, offset)) = poll.uncredited_charge() {
        counter!("ingestion_consumer_commit_violations_total", "kind" => "uncredited").increment(1);
        anyhow::bail!(
            "offset {} of {}/{} has no completion — not committing offsets",
            offset.0,
            topic_partition.topic,
            topic_partition.partition
        );
    }
    Ok(poll)
}

fn emit_latest_processed_timestamp_metrics(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    group_id: &str,
) {
    // Same name as the Node.js consumer's gauge, so one dashboard reads both.
    for (topic_partition, partition) in partitions {
        gauge!(
            "latest_processed_timestamp_ms",
            "topic" => topic_partition.topic.clone(),
            "partition" => topic_partition.partition.to_string(),
            "groupId" => group_id.to_string()
        )
        .set(partition.latest_kafka_ts as f64);
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::time::{Duration, Instant};

    use common_kafka_consumer::{Charge, Offset as MessageOffset, Partition, TopicOffsetLedger};

    use super::super::harness::{p, Harness};
    use super::*;
    use crate::order_sentinel::OffsetSpan;
    use crate::partition_budget::BudgetLimits;
    use crate::settlement::{charge_offsets, GroupSettlement};

    fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
        let mut partitions = HashMap::new();
        partitions.insert(
            TopicPartition::new("test", partition),
            PartitionDeliveries {
                span: OffsetSpan { first, last },
                generation: 0,
                payload_bytes: 0,
                charges: (first..=last)
                    .map(|offset| (MessageOffset(offset), Charge::ZERO))
                    .collect(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: count,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
            },
        );
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions,
            uncommitted: HashMap::new(),
            message_count: count,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64], accepted: u32) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            generation: 0,
            offsets: offsets.iter().map(|o| MessageOffset(*o)).collect(),
            accepted,
        }
    }

    fn credit(in_flight: &mut VecDeque<InFlightPoll>, completion: GroupCompletion) {
        apply_completion(in_flight, &completion, |_, _, _| Ok(())).unwrap();
    }

    #[test]
    fn an_accepted_completion_settles_one_run_per_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        in_flight[1]
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .generation = 1;
        let mut runs = Vec::new();

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            |topic_partition, generation, offsets| {
                runs.push((topic_partition.partition, generation, offsets.to_vec()));
                Ok(())
            },
        )
        .unwrap();

        assert_eq!(
            runs,
            vec![
                (0, 0, vec![MessageOffset(2), MessageOffset(3)]),
                (0, 1, vec![MessageOffset(4), MessageOffset(5)]),
            ],
            "each run carries its own poll's generation"
        );
    }

    #[test]
    fn a_completion_spanning_two_polls_commits_once_the_prefix_is_whole() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        let partition = TopicPartition::new("test", 0);
        charge_offsets(&ledger, &partition, 0, &[0, 1, 2, 3, 4, 5, 6, 7]);
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        let mut settle = |topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]| {
            settlement
                .settle_run(topic_partition, generation, offsets)
                .map(drop)
        };

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            &mut settle,
        )
        .unwrap();
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "offsets 0 and 1 are still in flight"
        );

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[0, 1, 6, 7], 4),
            &mut settle,
        )
        .unwrap();
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(partition, MessageOffset(8))]))
        );
    }

    #[test]
    fn a_short_accepted_completion_settles_nothing() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);
        let mut runs = 0;

        apply_completion(&mut in_flight, &completion(1, 0, &[0, 1], 1), |_, _, _| {
            runs += 1;
            Ok(())
        })
        .unwrap();

        assert_eq!(runs, 0, "the ledger must not commit past a dropped message");
        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 1);
    }

    #[test]
    fn apply_completion_spanning_two_polls_credits_each() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 4));

        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 2);
        assert_eq!(in_flight[1].covered, 2);
        assert_eq!(in_flight[1].accepted, 2);
    }

    #[test]
    fn apply_completion_under_report_shorts_the_tail_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 3));

        assert_eq!(in_flight[0].accepted, 2, "leading offsets are accepted");
        assert_eq!(
            in_flight[1].accepted, 1,
            "the tail poll fails its accepted check"
        );
        assert_eq!(in_flight[1].covered, 2);
    }

    #[test]
    fn a_complete_poll_with_a_charged_offset_no_completion_covered_is_not_committable() {
        let mut in_flight = VecDeque::from([poll(1, 0, 10, 12, 3)]);

        credit(&mut in_flight, completion(1, 0, &[10, 12, 12], 3));

        assert!(in_flight[0].is_complete());
        let error = pop_committable(&mut in_flight)
            .err()
            .expect("offset 11 has no completion");
        assert!(error.to_string().contains("offset 11 "), "{error}");
    }

    #[test]
    fn a_poll_whose_deliveries_span_an_offset_gap_commits() {
        let mut gapped = poll(1, 0, 0, 0, 2);
        let deliveries = gapped
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap();
        deliveries.span.last = i64::MAX;
        deliveries
            .charges
            .push((MessageOffset(i64::MAX), Charge::ZERO));
        let mut in_flight = VecDeque::from([gapped]);

        credit(&mut in_flight, completion(1, 0, &[0, i64::MAX], 2));

        assert!(in_flight[0].is_complete());
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_keeps_the_other_partitions_slices() {
        let mut two = poll(1, 0, 0, 1, 4);
        two.partitions.insert(
            TopicPartition::new("test", 1),
            PartitionDeliveries {
                span: OffsetSpan {
                    first: 10,
                    last: 11,
                },
                generation: 0,
                payload_bytes: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: 2,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
            },
        );
        two.partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .delivered = 2;
        let mut in_flight = VecDeque::from([two]);
        credit(&mut in_flight, completion(1, 1, &[10], 1));

        let stripped = strip_revoked_partitions(&mut in_flight, &[TopicPartition::new("test", 1)]);

        assert_eq!(stripped, 2);
        assert_eq!(in_flight[0].message_count, 2);
        assert_eq!(in_flight[0].covered, 0, "the revoked slice's credit goes");
        assert!(!in_flight[0].is_complete());

        credit(&mut in_flight, completion(1, 1, &[11], 1));
        assert_eq!(in_flight[0].covered, 0);
        credit(&mut in_flight, completion(1, 0, &[0, 1], 2));
        assert!(in_flight[0].is_complete());
        assert_eq!(in_flight[0].accepted, 2);
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_removes_an_emptied_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 2, 0, 3, 4)]);

        let stripped = strip_revoked_partitions(&mut in_flight, &[TopicPartition::new("test", 0)]);

        assert_eq!(stripped, 4);
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight[0].message_count, 4);
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        credit(&mut in_flight, completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 4);
    }

    fn capped(max_in_flight_polls: usize) -> Harness<CappedPolling> {
        Harness::new(|parts| CappedPolling::new(parts, max_in_flight_polls))
    }

    #[test]
    fn the_capped_strategy_stops_reading_at_its_cap_until_the_oldest_poll_is_covered() {
        let mut harness = capped(1);
        assert!(harness.poller.reading());

        harness.receive(0, &[0, 1]);
        assert!(harness.step().is_none(), "the poll is still collecting");
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(!harness.poller.reading());

        harness.complete(0, &[0, 1]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert!(harness.poller.reading());
    }
}
