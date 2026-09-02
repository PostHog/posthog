//! Producer for the `cohort_reconcile_markers` topic.
//!
//! A dedicated producer rather than a second topic on [`crate::producer::KafkaMembershipSink`]: the
//! membership output has to move to its own cluster, while markers stay alongside the seed topic on
//! ingestion, and one shared producer would force them to move together.
//!
//! One topic property the seeder's watcher depends on, recorded here because the topic is
//! provisioned in another repo and would fail silently: a stable partition count. The watcher
//! captures a start offset per partition at dispatch and is assigned exactly those, so a partition
//! added mid-run is never read. Added before that run's observation ends are captured, it holds the
//! run open until a re-dispatch; added after them, it is not even consulted, and the run settles
//! short on the markers that landed where nothing was watching.
//!
//! The key ([`reconcile_complete_key`]) carries the body partition, so a run's 64 certificates are
//! 64 distinct keys rather than one — what stops a compacting topic from keeping whichever arrived
//! last and recording a completed backfill as short.

use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use rdkafka::producer::FutureProducer;

use crate::producer::kafka::AlwaysHealthy;
use crate::producer::merge::Capture;
use crate::producer::ReconcileCompleteMarker;

#[async_trait]
pub trait ReconcileMarkerSink: Send + Sync {
    async fn produce(
        &self,
        markers: Vec<ReconcileCompleteMarker>,
    ) -> Vec<Result<(), KafkaProduceError>>;
}

pub struct KafkaReconcileMarkerSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaReconcileMarkerSink {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_reconcile_markers producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl ReconcileMarkerSink for KafkaReconcileMarkerSink {
    async fn produce(
        &self,
        markers: Vec<ReconcileCompleteMarker>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            reconcile_complete_key,
            |_| None,
            markers,
        )
        .await
    }
}

/// Inert sink for when the reconcile gate is off: satisfies the [`ReconcileMarkerSink`] slot without
/// a Kafka producer. Nothing should reach it — a reconcile job is only ever admitted from a seed tile
/// and `ReconcileDeps::enabled` gates that admission — so a produce here is a coding error, and it
/// fails rather than acking. Acking would be the worse half of the trade: the job would complete and
/// commit its seed offset while the seeder waited for a certificate that was never produced.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoopReconcileMarkerSink;

#[async_trait]
impl ReconcileMarkerSink for NoopReconcileMarkerSink {
    async fn produce(
        &self,
        markers: Vec<ReconcileCompleteMarker>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        markers
            .into_iter()
            .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
            .collect()
    }
}

#[derive(Debug, Default, Clone)]
pub struct CaptureReconcileMarkerSink(Capture<ReconcileCompleteMarker>);

impl CaptureReconcileMarkerSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing_first(n: usize) -> Self {
        Self(Capture::failing_first(n))
    }

    pub fn markers(&self) -> Vec<ReconcileCompleteMarker> {
        self.0.recorded()
    }
}

#[async_trait]
impl ReconcileMarkerSink for CaptureReconcileMarkerSink {
    async fn produce(
        &self,
        markers: Vec<ReconcileCompleteMarker>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        self.0.produce(markers)
    }
}

/// Unique per marker, not per run: the partition is what makes 64 distinct keys out of one dispatch,
/// so no cleanup policy can collapse them. Nothing downstream reads the key and the ledger's fold is
/// order-independent, so the grouping carries no meaning beyond that.
fn reconcile_complete_key(marker: &ReconcileCompleteMarker) -> Option<String> {
    Some(format!(
        "{}:{}:{}:{}",
        marker.team_id().0,
        marker.cohort_id().0,
        marker.run_id().0,
        marker.partition(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::{CohortId, TeamId};
    use cohort_core::seed::RunId;
    use uuid::Uuid;

    const TS: &str = "2026-05-26 12:34:56.789123";

    fn marker(partition: u16) -> ReconcileCompleteMarker {
        ReconcileCompleteMarker::new(
            TeamId(42),
            CohortId(91204),
            partition,
            RunId(Uuid::nil()),
            TS.to_string(),
        )
    }

    #[test]
    fn reconcile_complete_key_is_unique_per_partition_marker() {
        assert_eq!(
            reconcile_complete_key(&marker(63)),
            Some("42:91204:00000000-0000-0000-0000-000000000000:63".to_string())
        );
        assert_ne!(
            reconcile_complete_key(&marker(63)),
            reconcile_complete_key(&marker(0)),
            "a shared key would let a compacting topic erase all but one marker of a run",
        );
    }

    #[tokio::test]
    async fn capture_marker_sink_retries_a_failed_produce_without_recording_the_attempt() {
        let sink = CaptureReconcileMarkerSink::failing_first(1);

        let first = sink.produce(vec![marker(7)]).await;
        assert!(first.iter().all(Result::is_err), "first flush fails");
        assert!(sink.markers().is_empty(), "a failed flush records nothing");

        let second = sink.produce(vec![marker(7)]).await;
        assert!(second.iter().all(Result::is_ok), "retry succeeds");
        assert_eq!(sink.markers(), vec![marker(7)]);
    }
}
