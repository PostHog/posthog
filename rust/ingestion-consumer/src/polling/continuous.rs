use std::collections::{HashMap, VecDeque};
use std::sync::Arc;

use common_kafka_consumer::{Charge, GroupCompletion, Partition, TopicPartition};
use metrics::{counter, gauge};
use rdkafka::message::Message;
use tokio::time::Instant;

use super::poll::InFlightPoll;
use super::{report_revoked, Collector, Parts, PollingStrategy, Step};
use crate::charge_limit::ChargeLimit;
use crate::settlement::{Commit, Settlement};

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
        self.settlement
            .settle_run(topic_partition, completion.generation, &completion.offsets)?;
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
