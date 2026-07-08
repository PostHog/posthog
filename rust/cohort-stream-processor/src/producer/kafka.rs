//! Kafka producer for `cohort_membership_changed_shadow`.

use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use common_liveness::SyncLivenessReporter;
use rdkafka::producer::FutureProducer;

use crate::producer::{CohortMembershipChange, MembershipSink};

/// No-op liveness reporter — producer stalls are surfaced by the consumer's liveness deadline.
#[derive(Clone, Copy)]
pub(crate) struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

pub struct KafkaMembershipSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaMembershipSink {
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
