use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::{
    GroupCompletion, Offset, Partition, TopicOffsetLedger, TopicPartition,
};
use tokio::time::Instant;

use super::collector::tests::message;
use super::{CollectedBatch, InFlightPoll, Parts, PollLimits, PollingStrategy, Step};
use crate::debug_recorder::{DebugEventKind, DebugRecorder};
use crate::partition_budget::BudgetLimits;
use crate::settlement::{GroupSettlement, Settlement};

pub(super) const BATCH_TIMEOUT: Duration = Duration::from_millis(500);

pub(super) struct Harness<P> {
    pub(super) poller: P,
    pub(super) settlement: Arc<dyn Settlement>,
    pub(super) ledger: Arc<TopicOffsetLedger>,
    pub(super) recorder: Arc<DebugRecorder>,
    pub(super) now: Instant,
    submitted: usize,
}

impl<P: PollingStrategy> Harness<P> {
    pub(super) fn new(make: impl FnOnce(Parts) -> P) -> Self {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement: Arc<dyn Settlement> = Arc::new(GroupSettlement::new(
            Arc::clone(&ledger),
            Duration::ZERO,
            BudgetLimits::unset(),
        ));
        let recorder = DebugRecorder::new(1_000, Duration::from_secs(3600));
        let poller = make(Parts {
            limits: PollLimits {
                batch_size: 100,
                batch_size_bytes: 0,
                batch_timeout: BATCH_TIMEOUT,
            },
            settlement: Arc::clone(&settlement),
            group_id: "test".to_string(),
            debug_recorder: Some(Arc::clone(&recorder)),
        });
        Self {
            poller,
            settlement,
            ledger,
            recorder,
            now: Instant::now(),
            submitted: 0,
        }
    }

    /// `(poll id, accepted)` in completion order. The n-th submitted poll is `poll-n`.
    pub(super) fn completed_polls(&self) -> Vec<(String, u32)> {
        self.recorder
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

    pub(super) fn receive(&mut self, partition: i32, offsets: &[i64]) {
        for &offset in offsets {
            self.poller
                .received(&message(partition, offset, 10), self.now);
        }
    }

    pub(super) fn after_the_batch_timeout(&mut self) {
        self.now += BATCH_TIMEOUT;
    }

    pub(super) fn step(&mut self) -> Option<Step> {
        self.poller.next_step(self.now)
    }

    pub(super) fn submit(&mut self) -> HashMap<TopicPartition, (i64, i64)> {
        let Some(Step::Submit(collected)) = self.step() else {
            panic!("expected a poll to submit");
        };
        let CollectedBatch {
            accumulator,
            mut partitions,
            ..
        } = collected;
        let mut uncommitted = HashMap::new();
        for (topic_partition, deliveries) in &mut partitions {
            deliveries.generation = self.ledger.generation(topic_partition);
            let charged = self
                .settlement
                .charge(topic_partition, deliveries.generation, &deliveries.charges)
                .expect("the ledger accepts the charge");
            uncommitted.insert(topic_partition.clone(), charged.uncommitted);
        }
        let spans = partitions
            .iter()
            .map(|(topic_partition, deliveries)| {
                (
                    topic_partition.clone(),
                    (deliveries.span.first, deliveries.span.last),
                )
            })
            .collect();
        let poll_id = format!("poll-{}", self.submitted);
        self.submitted += 1;
        self.poller.submitted(InFlightPoll {
            poll_id,
            assignment_epoch: 1,
            partitions,
            uncommitted,
            message_count: accumulator.message_count() as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: std::time::Instant::now(),
        });
        spans
    }

    pub(super) fn complete(&mut self, partition: i32, offsets: &[i64]) {
        let generation = self.ledger.generation(&p(partition));
        self.complete_under(generation, partition, offsets);
    }

    pub(super) fn complete_under(&mut self, generation: u64, partition: i32, offsets: &[i64]) {
        self.poller
            .completed(&completion(generation, partition, offsets))
            .expect("the completion applies");
    }

    pub(super) fn revoke(&mut self, partition: i32) {
        self.settlement.forget_partitions(&[p(partition)]);
        self.poller.revoked(&[p(partition)]);
    }

    pub(super) fn commit(&mut self) -> HashMap<TopicPartition, Offset> {
        match self.step() {
            Some(Step::Commit(commit)) => commit.offsets,
            _ => panic!("expected a commit"),
        }
    }
}

pub(super) fn completion(generation: u64, partition: i32, offsets: &[i64]) -> GroupCompletion {
    GroupCompletion {
        partition: Partition(partition),
        assignment_epoch: 1,
        generation,
        offsets: offsets.iter().map(|&offset| Offset(offset)).collect(),
        accepted: offsets.len() as u32,
    }
}

pub(super) fn p(partition: i32) -> TopicPartition {
    TopicPartition::new("events", partition)
}
