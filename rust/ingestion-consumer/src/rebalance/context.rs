//! The consumer's rdkafka context: rebalance callbacks into [`RebalanceState`], plus rebalance counters and client statistics.

use std::sync::{Mutex, MutexGuard};
use std::time::Duration;

use common_kafka_consumer::TopicPartition;
use metrics::counter;
use rdkafka::consumer::{BaseConsumer, Consumer, ConsumerContext, RebalanceProtocol};
use rdkafka::error::{KafkaResult, RDKafkaErrorCode};
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientContext, Statistics, TopicPartitionList};
use tokio::sync::Notify;
use tokio::time::Instant;
use tracing::{error, info, warn};

use super::state::{Drain, Event, RebalanceState, Unassign};
use crate::batcher::RevokeId;

#[derive(Default)]
pub struct RebalanceContext {
    rebalance_state: Mutex<RebalanceState>,
    rebalanced: Notify,
}

impl RebalanceContext {
    pub fn new() -> Self {
        Self::default()
    }

    pub(crate) fn on_started(&self, drain_timeout: Option<Duration>) {
        self.rebalance_state().on_started(drain_timeout);
    }

    pub(crate) fn on_stopped(&self) -> Option<Drain> {
        self.rebalance_state().on_stopped()
    }

    pub(crate) fn on_dropped(&self) -> Vec<Unassign> {
        self.rebalance_state().on_dropped()
    }

    pub(crate) fn on_drained(&self, revoke: RevokeId) -> Option<Drain> {
        self.rebalance_state().on_drained(revoke)
    }

    pub(crate) fn on_drain_timed_out(&self, now: Instant) -> Option<Drain> {
        self.rebalance_state().on_drain_timed_out(now)
    }

    pub(crate) fn take_events(&self) -> Vec<Event> {
        self.rebalance_state().take_events()
    }

    pub(crate) fn drain_deadline(&self) -> Option<Instant> {
        self.rebalance_state().drain_deadline()
    }

    pub(crate) async fn wait_for_rebalance(&self) {
        self.rebalanced.notified().await;
    }

    fn rebalance_state(&self) -> MutexGuard<'_, RebalanceState> {
        self.rebalance_state.lock().unwrap()
    }

    fn on_assigned(&self, consumer: &BaseConsumer<Self>, tpl: &TopicPartitionList) {
        counter!("ingestion_consumer_rebalances_total", "event" => "assign").increment(1);
        let partitions = topic_partitions(tpl);
        info!(
            partitions = partitions.len(),
            topic_partitions = ?partition_names(&partitions),
            "Rebalance: partitions assigned"
        );
        let assigned = if cooperative(consumer) {
            consumer.incremental_assign(tpl)
        } else {
            consumer.assign(tpl)
        };
        if let Err(err) = assigned {
            error!(error = %err, "Could not assign the partitions");
        }
        // librdkafka keeps a partition's pause across a revoke and a
        // reassignment, and the consumer forgets the budget that paused it.
        if let Err(err) = consumer.resume(tpl).and_then(|()| partition_error(tpl)) {
            error!(error = %err, "Could not resume the assigned partitions");
        }
        self.rebalance_state().on_assigned(partitions);
    }

    fn on_revoked(&self, consumer: &BaseConsumer<Self>, tpl: &TopicPartitionList) {
        counter!("ingestion_consumer_rebalances_total", "event" => "revoke").increment(1);
        let partitions = topic_partitions(tpl);
        let names = partition_names(&partitions);
        info!(
            partitions = names.len(),
            topic_partitions = ?names,
            "Rebalance: partitions revoked"
        );
        let unassign = self.rebalance_state().on_revoked(
            partitions,
            Unassign::new(tpl.clone(), cooperative(consumer)),
            consumer.assignment_lost(),
            Instant::now(),
        );
        if let Some(unassign) = unassign {
            if let Err(err) = unassign.apply(consumer) {
                error!(error = %err, "Could not unassign the revoked partitions");
            }
        }
    }
}

fn cooperative<C: ConsumerContext>(consumer: &BaseConsumer<C>) -> bool {
    matches!(
        consumer.rebalance_protocol(),
        RebalanceProtocol::Cooperative
    )
}

fn topic_partitions(tpl: &TopicPartitionList) -> Vec<TopicPartition> {
    let mut partitions: Vec<TopicPartition> = tpl
        .elements()
        .iter()
        .map(|element| TopicPartition::new(element.topic(), element.partition()))
        .collect();
    partitions.sort_unstable_by(|a, b| (&a.topic, a.partition).cmp(&(&b.topic, b.partition)));
    partitions
}

/// librdkafka's pause and resume return success when they cannot change a
/// partition. They set the error on that partition's list element.
pub(crate) fn partition_error(tpl: &TopicPartitionList) -> KafkaResult<()> {
    tpl.elements()
        .iter()
        .try_for_each(|element| element.error())
}

pub(crate) fn partition_names(partitions: &[TopicPartition]) -> Vec<String> {
    partitions
        .iter()
        .map(|tp| format!("{}:{}", tp.topic, tp.partition))
        .collect()
}

impl ClientContext for RebalanceContext {
    /// Fired on a librdkafka thread every `statistics.interval.ms`; disabled
    /// when that is 0.
    fn stats(&self, stats: Statistics) {
        crate::kafka_stats::export(&stats);
    }
}

impl ConsumerContext for RebalanceContext {
    fn rebalance(
        &self,
        consumer: &BaseConsumer<Self>,
        err: RDKafkaRespErr,
        tpl: &mut TopicPartitionList,
    ) {
        match err {
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS => self.on_assigned(consumer, tpl),
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS => self.on_revoked(consumer, tpl),
            _ => {
                counter!("ingestion_consumer_rebalances_total", "event" => "error").increment(1);
                warn!(error = %RDKafkaErrorCode::from(err), "Rebalance error");
                if let Err(err) = Unassign::new(tpl.clone(), cooperative(consumer)).apply(consumer)
                {
                    error!(error = %err, "Could not unassign after a rebalance error");
                }
            }
        }
        self.rebalanced.notify_one();
    }

    // NOTE: `ConsumerContext::commit_callback` is deliberately not implemented.
    // librdkafka only propagates a commit result to the application when a
    // conf-level `offset_commit_cb` is registered (rust-rdkafka never does) or
    // when the commit is synchronous (a replyq is attached); manual async
    // commits silently drop their result (`rd_kafka_cgrp_propagate_commit_result`).
}

#[cfg(test)]
mod tests {
    use rdkafka::config::ClientConfig;
    use rdkafka::consumer::Consumer;

    use super::*;

    #[test]
    fn partitions_sort_by_topic_then_partition_number() {
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("overflow", 2);
        tpl.add_partition("events", 10);
        tpl.add_partition("events", 9);

        assert_eq!(
            partition_names(&topic_partitions(&tpl)),
            vec!["events:9", "events:10", "overflow:2"]
        );
    }

    struct CallbackCase {
        loop_running: bool,
        revoke_queued: bool,
        still_assigned: usize,
    }

    #[rstest::rstest]
    #[case::loop_running(CallbackCase { loop_running: true, revoke_queued: true, still_assigned: 2 })]
    #[case::no_loop(CallbackCase { loop_running: false, revoke_queued: false, still_assigned: 0 })]
    fn the_loop_applies_the_unassign_while_it_runs(#[case] case: CallbackCase) {
        let consumer: BaseConsumer<RebalanceContext> = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .set("group.id", "test")
            .create_with_context(RebalanceContext::new())
            .expect("a client needs no broker to be built");
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("events", 1);
        tpl.add_partition("events", 0);
        let context = consumer.context();
        if case.loop_running {
            context.on_started(None);
        }

        context.rebalance(
            &consumer,
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS,
            &mut tpl,
        );
        context.rebalance(
            &consumer,
            RDKafkaRespErr::RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS,
            &mut tpl,
        );

        let partitions = vec![
            TopicPartition::new("events", 0),
            TopicPartition::new("events", 1),
        ];
        let mut expected = vec![Event::Assigned(partitions.clone())];
        if case.revoke_queued {
            expected.push(Event::Revoked {
                revoke: RevokeId(1),
                partitions,
                unassign: Unassign::new(tpl.clone(), false),
            });
        }
        assert_eq!(context.take_events(), expected);
        assert_eq!(consumer.assignment().unwrap().count(), case.still_assigned);
    }

    #[test]
    fn pausing_an_unassigned_partition_is_an_error() {
        let consumer: BaseConsumer = ClientConfig::new()
            .set("bootstrap.servers", "127.0.0.1:1")
            .set("group.id", "test")
            .create()
            .expect("a client needs no broker to be built");
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("events", 0);

        assert!(consumer.pause(&tpl).is_ok());
        assert!(partition_error(&tpl).is_err());
    }
}
