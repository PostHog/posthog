//! Kafka producer for `cohort_membership_changed_shadow` (TDD §4.7, §6.1 PR 1.8).
//!
//! Near-verbatim from `cohort-event-shuffler/src/producer.rs`: a [`FutureProducer`] built via
//! [`create_kafka_producer`] (which pings broker metadata for fail-fast startup), producing each
//! [`CohortMembershipChange`] keyed by `person_id` so the shadow topic co-partitions by person the
//! same way the legacy producer does. The `murmur2_random` partitioner is pinned in
//! [`crate::config`].

use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use common_liveness::SyncLivenessReporter;
use rdkafka::producer::FutureProducer;

use crate::producer::{CohortMembershipChange, MembershipSink};

/// No-op liveness reporter for the producer's rdkafka client context.
///
/// The producer is driven entirely by the consumer loop; if it stalls, the worker's
/// `produce().await` blocks and the *consumer* — which owns the liveness deadline — stops
/// heartbeating, tripping the stall detector. Feeding the producer's background stats callback into
/// the consumer's health instead would mask exactly that stall, so the producer gets its own
/// always-healthy sink (mirrors the shuffler's producer).
#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

/// The production [`MembershipSink`]: produces membership changes to
/// `cohort_membership_changed_shadow`.
pub struct KafkaMembershipSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaMembershipSink {
    /// Build the producer and verify broker connectivity (`create_kafka_producer` pings for
    /// metadata before returning, giving fail-fast startup).
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_membership_changed_shadow producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl MembershipSink for KafkaMembershipSink {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            membership_key,
            |_| None,
            changes,
        )
        .await
    }
}

/// Partition key for a membership change: its `person_id`, so a person's changes co-partition by
/// person — matching the legacy producer keying. Extracted (not an inline closure) so the contract
/// is unit-testable without a broker.
fn membership_key(change: &CohortMembershipChange) -> Option<String> {
    Some(change.person_id.clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::producer::MembershipStatus;

    #[test]
    fn membership_key_is_the_person_id() {
        let change = CohortMembershipChange {
            team_id: 42,
            cohort_id: 91204,
            person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            last_updated: "2026-05-26 12:34:56.789123".to_string(),
            status: MembershipStatus::Entered,
        };
        assert_eq!(membership_key(&change), Some(change.person_id.clone()));
    }
}
