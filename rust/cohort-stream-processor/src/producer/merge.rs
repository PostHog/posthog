//! Merge-protocol producers for `cohort_merge_state_transfer` and straggler re-keys back into
//! `cohort_stream_events`.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use rdkafka::producer::FutureProducer;
use uuid::Uuid;

use crate::consumers::events::CohortStreamEvent;
use crate::filters::TeamId;
use crate::merge::transfer::MergeStateTransfer;
use crate::partitions::partitioner::merge_partition_key;
use crate::producer::kafka::AlwaysHealthy;

#[async_trait]
pub trait TransferSink: Send + Sync {
    async fn produce(
        &self,
        transfers: Vec<MergeStateTransfer>,
    ) -> Vec<Result<(), KafkaProduceError>>;
}

#[async_trait]
pub trait StreamEventSink: Send + Sync {
    async fn produce(&self, events: Vec<CohortStreamEvent>) -> Vec<Result<(), KafkaProduceError>>;
}

pub struct KafkaTransferSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaTransferSink {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_merge_state_transfer producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl TransferSink for KafkaTransferSink {
    async fn produce(
        &self,
        transfers: Vec<MergeStateTransfer>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            transfer_key,
            |_| None,
            transfers,
        )
        .await
    }
}

pub struct KafkaStreamEventSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaStreamEventSink {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_stream_events re-key producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl StreamEventSink for KafkaStreamEventSink {
    async fn produce(&self, events: Vec<CohortStreamEvent>) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            stream_event_key,
            |_| None,
            events,
        )
        .await
    }
}

fn transfer_key(transfer: &MergeStateTransfer) -> Option<String> {
    Some(merge_partition_key(
        TeamId(transfer.team_id),
        &transfer.new_person_uuid,
    ))
}

fn stream_event_key(event: &CohortStreamEvent) -> Option<String> {
    match Uuid::parse_str(&event.person_id) {
        Ok(person) => Some(merge_partition_key(TeamId(event.team_id), &person)),
        Err(_) => Some(format!("{}:{}", event.team_id, event.person_id)),
    }
}

const FAIL_ALWAYS: usize = usize::MAX;

/// Shared produce recorder for test doubles: records items and can fail the next `n` (or all)
/// produces.
#[derive(Debug)]
pub(crate) struct Capture<T> {
    items: Arc<Mutex<Vec<T>>>,
    fail_remaining: Arc<AtomicUsize>,
}

impl<T> Clone for Capture<T> {
    fn clone(&self) -> Self {
        Self {
            items: self.items.clone(),
            fail_remaining: self.fail_remaining.clone(),
        }
    }
}

impl<T> Default for Capture<T> {
    fn default() -> Self {
        Self {
            items: Arc::default(),
            fail_remaining: Arc::default(),
        }
    }
}

impl<T> Capture<T> {
    pub(crate) fn failing_first(n: usize) -> Self {
        Self {
            items: Arc::default(),
            fail_remaining: Arc::new(AtomicUsize::new(n)),
        }
    }

    pub(crate) fn failing_always() -> Self {
        Self::failing_first(FAIL_ALWAYS)
    }

    pub(crate) fn produce(&self, items: Vec<T>) -> Vec<Result<(), KafkaProduceError>> {
        let should_fail = self
            .fail_remaining
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| match n {
                0 => None,
                FAIL_ALWAYS => Some(FAIL_ALWAYS),
                n => Some(n - 1),
            })
            .is_ok();
        if should_fail {
            return items
                .into_iter()
                .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
                .collect();
        }
        let acks = (0..items.len()).map(|_| Ok(())).collect();
        self.items
            .lock()
            .expect("Capture mutex poisoned")
            .extend(items);
        acks
    }
}

impl<T: Clone> Capture<T> {
    pub(crate) fn recorded(&self) -> Vec<T> {
        self.items.lock().expect("Capture mutex poisoned").clone()
    }
}

#[derive(Debug, Default, Clone)]
pub struct CaptureTransferSink(Capture<MergeStateTransfer>);

impl CaptureTransferSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing_first(n: usize) -> Self {
        Self(Capture::failing_first(n))
    }

    pub fn failing_always() -> Self {
        Self(Capture::failing_always())
    }

    pub fn transfers(&self) -> Vec<MergeStateTransfer> {
        self.0.recorded()
    }
}

#[async_trait]
impl TransferSink for CaptureTransferSink {
    async fn produce(
        &self,
        transfers: Vec<MergeStateTransfer>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        self.0.produce(transfers)
    }
}

#[derive(Debug, Default, Clone)]
pub struct CaptureStreamEventSink(Capture<CohortStreamEvent>);

impl CaptureStreamEventSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing_first(n: usize) -> Self {
        Self(Capture::failing_first(n))
    }

    pub fn failing_always() -> Self {
        Self(Capture::failing_always())
    }

    pub fn events(&self) -> Vec<CohortStreamEvent> {
        self.0.recorded()
    }
}

#[async_trait]
impl StreamEventSink for CaptureStreamEventSink {
    async fn produce(&self, events: Vec<CohortStreamEvent>) -> Vec<Result<(), KafkaProduceError>> {
        self.0.produce(events)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::merge::transfer::TransferLeaf;
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};

    fn transfer(team_id: i32, new_person: Uuid) -> MergeStateTransfer {
        MergeStateTransfer {
            team_id,
            old_person_uuid: Uuid::from_u128(1),
            new_person_uuid: new_person,
            merged_at_ms: 1_716_800_000_000,
            source_partition: 3,
            source_offset: 9,
            leaves: vec![TransferLeaf::new(
                LeafStateKey([0xAB; 16]),
                StatefulRecord::new(
                    Stage1State::BehavioralSingle {
                        has_match: true,
                        last_event_at_ms: 1,
                        earliest_eviction_at_ms: i64::MAX,
                    },
                    AppliedOffsets::default(),
                ),
            )],
            forward_hops: 0,

            person_dedup: None,
        }
    }

    #[test]
    fn transfer_key_is_the_merge_partition_key_of_p_new() {
        let p_new = Uuid::from_u128(0x0192_8bbb);
        assert_eq!(
            transfer_key(&transfer(42, p_new)),
            Some(merge_partition_key(TeamId(42), &p_new)),
        );
    }

    #[test]
    fn stream_event_key_is_the_merge_partition_key_of_the_rewritten_person() {
        let person = Uuid::from_u128(0x0192_8ccc);
        let event = CohortStreamEvent {
            team_id: 42,
            person_id: person.to_string(),
            distinct_id: "d".to_string(),
            uuid: "u".to_string(),
            event: "$pageview".to_string(),
            timestamp: "2026-05-26 12:34:56.789000".to_string(),
            properties: None,
            person_properties: None,
            elements_chain: None,
            source_offset: 0,
            source_partition: 0,
            redirected_from: Some(Uuid::from_u128(1).to_string()),
            redirect_hops: 1,
        };
        assert_eq!(
            stream_event_key(&event),
            Some(merge_partition_key(TeamId(42), &person)),
        );

        let raw = CohortStreamEvent {
            person_id: "not-a-uuid".to_string(),
            ..event
        };
        assert_eq!(stream_event_key(&raw), Some("42:not-a-uuid".to_string()));
    }

    #[tokio::test]
    async fn capture_transfer_sink_records_and_acks_in_order() {
        let sink = CaptureTransferSink::new();
        let t = transfer(7, Uuid::from_u128(2));
        let acks = sink.produce(vec![t.clone(), t.clone()]).await;
        assert_eq!(acks.len(), 2);
        assert!(acks.iter().all(Result::is_ok));
        assert_eq!(sink.transfers(), vec![t.clone(), t]);
    }

    #[tokio::test]
    async fn capture_transfer_sink_failing_first_fails_then_succeeds_recording_nothing_on_failure()
    {
        let sink = CaptureTransferSink::failing_first(1);
        let t = transfer(7, Uuid::from_u128(2));

        let first = sink.produce(vec![t.clone()]).await;
        assert!(first.iter().all(Result::is_err), "first flush fails");
        assert!(
            sink.transfers().is_empty(),
            "a failed flush records nothing"
        );

        let second = sink.produce(vec![t.clone()]).await;
        assert!(second.iter().all(Result::is_ok), "second flush succeeds");
        assert_eq!(sink.transfers(), vec![t]);
    }

    #[tokio::test]
    async fn capture_transfer_sink_failing_always_never_succeeds() {
        let sink = CaptureTransferSink::failing_always();
        let t = transfer(7, Uuid::from_u128(2));
        for _ in 0..10 {
            let acks = sink.produce(vec![t.clone()]).await;
            assert!(acks.iter().all(Result::is_err));
        }
        assert!(sink.transfers().is_empty());
    }
}
