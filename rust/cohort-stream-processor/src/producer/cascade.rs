//! Producer for the internal `cohort_cascade_events` topic.
//!
//! [`cascade_key`] keys on `(team, person)` over the same `murmur2_random` partitioner as the
//! shuffler, so a flip co-partitions with `cohort_stream_events` and lands on the worker that owns
//! that person's `cf_stage1`/`cf_stage2`.

use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use rdkafka::producer::FutureProducer;
use uuid::Uuid;

use crate::cascade::CascadeMessage;
use crate::filters::TeamId;
use crate::partitions::partitioner::merge_partition_key;
use crate::producer::kafka::AlwaysHealthy;
use crate::producer::merge::Capture;

#[async_trait]
pub trait CascadeSink: Send + Sync {
    async fn produce(&self, messages: Vec<CascadeMessage>) -> Vec<Result<(), KafkaProduceError>>;
}

pub struct KafkaCascadeSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaCascadeSink {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_cascade_events producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl CascadeSink for KafkaCascadeSink {
    async fn produce(&self, messages: Vec<CascadeMessage>) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            cascade_key,
            |_| None,
            messages,
        )
        .await
    }
}

/// Key on `(team, person)` using the same partitioner as the shuffler. Non-UUID persons fall back
/// to the raw `team:person` string.
fn cascade_key(message: &CascadeMessage) -> Option<String> {
    let change = &message.change;
    match Uuid::parse_str(&change.person_id) {
        Ok(person) => Some(merge_partition_key(TeamId(change.team_id), &person)),
        Err(_) => Some(format!("{}:{}", change.team_id, change.person_id)),
    }
}

/// No-op cascade sink for when the cascade gate is off: satisfies the `CascadeSink` slot without a
/// Kafka producer. The worker gate prevents produces from reaching this.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoopCascadeSink;

#[async_trait]
impl CascadeSink for NoopCascadeSink {
    async fn produce(&self, messages: Vec<CascadeMessage>) -> Vec<Result<(), KafkaProduceError>> {
        messages.iter().map(|_| Ok(())).collect()
    }
}

#[derive(Debug, Default, Clone)]
pub struct CaptureCascadeSink(Capture<CascadeMessage>);

impl CaptureCascadeSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing_first(n: usize) -> Self {
        Self(Capture::failing_first(n))
    }

    pub fn failing_always() -> Self {
        Self(Capture::failing_always())
    }

    pub fn messages(&self) -> Vec<CascadeMessage> {
        self.0.recorded()
    }
}

#[async_trait]
impl CascadeSink for CaptureCascadeSink {
    async fn produce(&self, messages: Vec<CascadeMessage>) -> Vec<Result<(), KafkaProduceError>> {
        self.0.produce(messages)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cascade::first_cascade;
    use crate::partitions::partitioner::{partition_for, COHORT_PARTITION_COUNT};
    use crate::producer::{CohortMembershipChange, MembershipStatus};

    const TS: &str = "2026-05-26 12:34:56.789123";

    fn message(team_id: i32, person: Uuid) -> CascadeMessage {
        first_cascade(
            CohortMembershipChange {
                team_id,
                cohort_id: 91204,
                person_id: person.to_string(),
                last_updated: TS.to_string(),
                status: MembershipStatus::Entered,
            },
            777,
        )
    }

    #[test]
    fn cascade_key_is_the_merge_partition_key_of_the_person() {
        let person = Uuid::from_u128(0x0192_8ccc);
        assert_eq!(
            cascade_key(&message(42, person)),
            Some(merge_partition_key(TeamId(42), &person)),
            "the cascade key must co-partition with cohort_stream_events",
        );
    }

    #[test]
    fn cascade_key_routes_to_the_same_partition_as_the_event_key() {
        // The cascade producer's partition for (team, person) must equal the shuffler's so the
        // message lands on the owning worker.
        let person = Uuid::from_u128(0x0192_8ddd);
        let key = cascade_key(&message(7, person)).unwrap();
        let event_key = merge_partition_key(TeamId(7), &person);
        assert_eq!(
            partition_for(&key, COHORT_PARTITION_COUNT),
            partition_for(&event_key, COHORT_PARTITION_COUNT),
        );
    }

    #[test]
    fn cascade_key_falls_back_to_raw_string_for_a_non_uuid_person() {
        let mut msg = message(42, Uuid::nil());
        msg.change.person_id = "not-a-uuid".to_string();
        assert_eq!(cascade_key(&msg), Some("42:not-a-uuid".to_string()));
    }

    #[tokio::test]
    async fn capture_cascade_sink_records_and_acks_in_order() {
        let sink = CaptureCascadeSink::new();
        let m = message(7, Uuid::from_u128(2));
        let acks = sink.produce(vec![m.clone(), m.clone()]).await;
        assert_eq!(acks.len(), 2);
        assert!(acks.iter().all(Result::is_ok));
        assert_eq!(sink.messages(), vec![m.clone(), m]);
    }

    #[tokio::test]
    async fn capture_cascade_sink_failing_first_records_nothing_on_failure() {
        let sink = CaptureCascadeSink::failing_first(1);
        let m = message(7, Uuid::from_u128(2));

        let first = sink.produce(vec![m.clone()]).await;
        assert!(first.iter().all(Result::is_err), "first flush fails");
        assert!(sink.messages().is_empty(), "a failed flush records nothing");

        let second = sink.produce(vec![m.clone()]).await;
        assert!(second.iter().all(Result::is_ok), "second flush succeeds");
        assert_eq!(sink.messages(), vec![m]);
    }

    #[tokio::test]
    async fn noop_cascade_sink_acks_without_recording() {
        let sink = NoopCascadeSink;
        let acks = sink.produce(vec![message(1, Uuid::from_u128(1))]).await;
        assert_eq!(acks.len(), 1);
        assert!(acks.iter().all(Result::is_ok));
    }
}
