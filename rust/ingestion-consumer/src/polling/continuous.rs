use std::collections::{HashMap, VecDeque};
use std::sync::Arc;

use common_kafka_consumer::{Charge, GroupCompletion, Partition, TopicPartition};
use metrics::{counter, gauge};
use rdkafka::message::Message;
use tokio::time::Instant;

use super::poll::InFlightPoll;
use super::{report_revoked, Collector, Parts, PollingStrategy, Step};
use crate::charge_limit::ChargeLimit;
use crate::settlement::{Commit, RunOutcome, Settlement};

/// Nothing waits on a submitted poll: the partition budget and the in-flight
/// limit bound admission.
pub(crate) struct ContinuousPolling {
    collector: Collector,
    settlement: Arc<dyn Settlement>,
    uncommitted: UncommittedCharges,
    processed: ProcessedTimestamps,
    limits: ChargeLimit,
    at_limit: bool,
    accepting_new_batches: bool,
    commit_due: bool,
}

impl ContinuousPolling {
    pub(crate) fn new(parts: Parts, limits: ChargeLimit) -> Self {
        Self {
            collector: Collector::new(parts.limits),
            settlement: parts.settlement,
            uncommitted: UncommittedCharges::default(),
            processed: ProcessedTimestamps::new(parts.group_id),
            limits,
            at_limit: false,
            accepting_new_batches: true,
            commit_due: false,
        }
    }
}

impl PollingStrategy for ContinuousPolling {
    /// The poll in progress is not counted, so the uncommitted charge can
    /// pass the limit by one poll.
    fn reading(&mut self) -> bool {
        let at_limit = self.limits.reached(self.uncommitted.total());
        if at_limit && !self.at_limit {
            counter!("ingestion_consumer_in_flight_limit_reached_total").increment(1);
        }
        self.at_limit = at_limit;
        self.accepting_new_batches && !at_limit
    }

    fn deadline(&self) -> Option<Instant> {
        self.collector.deadline()
    }

    fn received<M: Message>(&mut self, message: &M, now: Instant) {
        self.collector.add(message, now);
    }

    fn completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()> {
        if (completion.accepted as usize) < completion.offsets.len() {
            anyhow::bail!(
                "accepted {}/{} messages — not committing offsets",
                completion.accepted,
                completion.offsets.len()
            );
        }
        let Some(topic_partition) = self.uncommitted.topic_partition(completion.partition) else {
            return Ok(());
        };
        let outcome = self.settlement.settle_run(
            topic_partition,
            completion.generation,
            &completion.offsets,
        )?;
        if outcome == RunOutcome::Stale {
            return Ok(());
        }
        counter!("ingestion_consumer_messages_processed_total")
            .increment(completion.offsets.len() as u64);
        self.commit_due = true;
        Ok(())
    }

    fn ticked(&mut self) {
        self.commit_due = true;
    }

    fn revoked(&mut self, topic_partitions: &[TopicPartition]) {
        let building = self.collector.remove_partitions(topic_partitions) as u64;
        self.uncommitted.revoked(topic_partitions);
        self.processed.revoked(topic_partitions);
        report_revoked(building);
    }

    fn shutdown(&mut self) {
        self.accepting_new_batches = false;
        self.commit_due = true;
        self.collector.discard();
    }

    fn submitted(&mut self, poll: InFlightPoll) {
        self.uncommitted.charged(&poll);
        self.processed.submitted(&poll);
    }

    fn next_step(&mut self, now: Instant) -> Option<Step> {
        if std::mem::take(&mut self.commit_due) {
            let commit = if self.accepting_new_batches {
                self.settlement.take_due(now.into_std())
            } else {
                self.settlement.take_all()
            };
            if let Some(commit) = commit {
                self.uncommitted.committed(&commit);
                self.processed.committed(&commit);
                return Some(Step::Commit(commit));
            }
        }
        if let Some(collected) = self.collector.take_ready(now) {
            return Some(Step::Submit(collected));
        }
        (!self.accepting_new_batches && self.uncommitted.is_empty()).then_some(Step::Stop)
    }
}

struct ProcessedTimestamps {
    group_id: String,
    partitions: HashMap<TopicPartition, VecDeque<SubmittedSlice>>,
}

struct SubmittedSlice {
    last_offset: i64,
    latest_kafka_ts: i64,
}

impl ProcessedTimestamps {
    fn new(group_id: String) -> Self {
        Self {
            group_id,
            partitions: HashMap::new(),
        }
    }

    fn submitted(&mut self, poll: &InFlightPoll) {
        for (topic_partition, deliveries) in &poll.partitions {
            self.partitions
                .entry(topic_partition.clone())
                .or_default()
                .push_back(SubmittedSlice {
                    last_offset: deliveries.span.last,
                    latest_kafka_ts: deliveries.latest_kafka_ts,
                });
        }
    }

    fn committed(&mut self, commit: &Commit) {
        for (topic_partition, next_to_read) in &commit.offsets {
            let Some(polls) = self.partitions.get_mut(topic_partition) else {
                continue;
            };
            let mut latest = None;
            while polls
                .front()
                .is_some_and(|slice| slice.last_offset < next_to_read.0)
            {
                let slice = polls.pop_front().expect("checked above");
                latest = latest.max(Some(slice.latest_kafka_ts));
            }
            if let Some(latest) = latest {
                // Same name as the Node.js consumer's gauge, so one dashboard reads both.
                gauge!(
                    "latest_processed_timestamp_ms",
                    "topic" => topic_partition.topic.clone(),
                    "partition" => topic_partition.partition.to_string(),
                    "groupId" => self.group_id.clone()
                )
                .set(latest as f64);
            }
        }
    }

    fn revoked(&mut self, revoked: &[TopicPartition]) {
        for topic_partition in revoked {
            self.partitions.remove(topic_partition);
        }
    }
}

/// Keyed by partition number, because a completion carries no topic.
#[derive(Default)]
struct UncommittedCharges {
    partitions: HashMap<Partition, (TopicPartition, Charge)>,
    total: Charge,
}

impl UncommittedCharges {
    fn total(&self) -> Charge {
        self.total
    }

    fn is_empty(&self) -> bool {
        self.total == Charge::ZERO
    }

    /// `None` once the partition is revoked, until its next charge.
    fn topic_partition(&self, partition: Partition) -> Option<&TopicPartition> {
        self.partitions
            .get(&partition)
            .map(|(topic_partition, _)| topic_partition)
    }

    fn charged(&mut self, poll: &InFlightPoll) {
        for (topic_partition, &charge) in &poll.uncommitted {
            let previous = self.partitions.insert(
                Partition(topic_partition.partition),
                (topic_partition.clone(), charge),
            );
            self.replace(previous.map(|(_, charge)| charge), charge);
        }
    }

    fn committed(&mut self, commit: &Commit) {
        for (topic_partition, &charge) in &commit.uncommitted {
            if let Some((_, partition)) = self
                .partitions
                .get_mut(&Partition(topic_partition.partition))
            {
                let previous = std::mem::replace(partition, charge);
                self.replace(Some(previous), charge);
            }
        }
    }

    fn revoked(&mut self, revoked: &[TopicPartition]) {
        for topic_partition in revoked {
            let previous = self
                .partitions
                .remove(&Partition(topic_partition.partition));
            self.replace(previous.map(|(_, charge)| charge), Charge::ZERO);
        }
    }

    fn replace(&mut self, previous: Option<Charge>, charge: Charge) {
        self.total = self.total - previous.unwrap_or(Charge::ZERO) + charge;
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::num::NonZeroU64;

    use common_kafka_consumer::Offset;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};

    use super::super::harness::{completion, p, Harness};
    use super::*;

    fn continuous(in_flight_events: u64) -> Harness<ContinuousPolling> {
        Harness::new(|parts| {
            ContinuousPolling::new(
                parts,
                ChargeLimit::new(NonZeroU64::new(in_flight_events), None),
            )
        })
    }

    #[test]
    fn the_continuous_strategy_stops_reading_one_poll_past_its_limit_until_a_commit() {
        let mut harness = continuous(1);

        harness.receive(0, &[0, 1]);
        assert!(
            harness.poller.reading(),
            "the poll in progress is not counted"
        );
        harness.after_the_batch_timeout();
        assert_eq!(harness.submit(), HashMap::from([(p(0), (0, 1))]));
        assert!(!harness.poller.reading());

        harness.complete(0, &[0, 1]);
        assert!(
            !harness.poller.reading(),
            "a completion frees no room before its commit"
        );
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert!(harness.poller.reading());
    }

    #[test]
    fn a_revoke_removes_the_partitions_messages_received_before_it() {
        let mut harness = continuous(1_000);
        harness.receive(0, &[10, 11]);
        harness.receive(1, &[20]);

        harness.poller.revoked(&[p(0)]);
        harness.receive(0, &[10]);
        harness.after_the_batch_timeout();

        assert_eq!(
            harness.submit(),
            HashMap::from([(p(0), (10, 10)), (p(1), (20, 20))]),
            "the redelivery after the revoke stays"
        );
    }

    #[test]
    fn a_completion_from_before_a_revoke_settles_nothing_in_the_next_assignment() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let processed = || {
            snapshotter
                .snapshot()
                .into_vec()
                .into_iter()
                .find_map(|(key, _, _, value)| match value {
                    DebugValue::Counter(count)
                        if key.key().name() == "ingestion_consumer_messages_processed_total" =>
                    {
                        Some(count)
                    }
                    _ => None,
                })
                .unwrap_or_default()
        };
        let mut harness = continuous(1_000);
        harness.receive(0, &[0, 1]);
        harness.after_the_batch_timeout();
        harness.submit();
        let before = harness.ledger.generation(&p(0));

        harness.revoke(0);
        harness.receive(0, &[0, 1]);
        harness.after_the_batch_timeout();
        harness.submit();

        harness.complete_under(before, 0, &[0, 1]);
        harness.poller.ticked();
        assert!(
            harness.step().is_none(),
            "the old assignment's completion is stale"
        );
        assert_eq!(processed(), 0, "a stale completion processed nothing");
        harness.complete(0, &[0, 1]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert_eq!(processed(), 2);
    }

    #[test]
    fn a_revoke_frees_the_partitions_charge() {
        let mut harness = continuous(3);
        harness.receive(0, &[0, 1, 2]);
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(!harness.poller.reading());

        harness.revoke(0);
        assert!(
            harness.poller.reading(),
            "a revoked partition holds no charge"
        );

        harness.receive(0, &[0, 1, 2]);
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(
            !harness.poller.reading(),
            "the new assignment's charge counts in full"
        );
    }

    #[test]
    fn the_limit_sums_each_partitions_uncommitted_charge() {
        let mut harness = continuous(5);
        harness.receive(0, &[0, 1]);
        harness.after_the_batch_timeout();
        harness.submit();
        harness.receive(0, &[2, 3]);
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(
            harness.poller.reading(),
            "a second submit replaces the partition's charge"
        );

        harness.receive(1, &[0]);
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(
            !harness.poller.reading(),
            "the partitions' charges add up to the limit"
        );

        harness.complete(0, &[0, 1]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert!(
            harness.poller.reading(),
            "a commit frees only the offsets it passed"
        );
    }

    #[test]
    fn a_completion_a_worker_did_not_accept_in_full_fails() {
        let mut harness = continuous(1_000);
        harness.receive(0, &[0, 1]);
        harness.after_the_batch_timeout();
        harness.submit();
        let mut short = completion(harness.ledger.generation(&p(0)), 0, &[0, 1]);
        short.accepted = 1;

        let error = harness
            .poller
            .completed(&short)
            .expect_err("a dropped message must not commit");
        assert!(error.to_string().contains("accepted 1/2"), "{error}");
    }

    #[test]
    fn a_commit_reports_the_newest_kafka_timestamp_it_passed() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let latest_processed = || {
            snapshotter
                .snapshot()
                .into_vec()
                .into_iter()
                .find_map(|(key, _, _, value)| match value {
                    DebugValue::Gauge(ts)
                        if key.key().name() == "latest_processed_timestamp_ms" =>
                    {
                        Some(ts.into_inner())
                    }
                    _ => None,
                })
        };
        let mut harness = continuous(1_000);
        harness.receive(0, &[0, 1]);
        harness.after_the_batch_timeout();
        harness.submit();
        assert_eq!(latest_processed(), None);

        harness.complete(0, &[0, 1]);
        harness.commit();

        assert_eq!(latest_processed(), Some(1_000.0));
    }

    #[test]
    fn shutdown_drops_the_poll_in_progress_and_stops_once_in_flight_work_drains() {
        let mut harness = continuous(1_000);
        harness.receive(0, &[0]);
        harness.after_the_batch_timeout();
        harness.submit();
        harness.receive(0, &[1]);

        harness.poller.shutdown();
        assert!(!harness.poller.reading());
        assert_eq!(harness.poller.deadline(), None);
        assert!(harness.step().is_none(), "offset 0 is still in flight");

        harness.complete(0, &[0]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(1))]));
        assert!(matches!(harness.step(), Some(Step::Stop)));
    }
}
