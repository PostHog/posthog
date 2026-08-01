//! Producer for the `cohort_reconcile_markers` topic.
//!
//! A dedicated producer rather than a second topic on [`crate::producer::KafkaMembershipSink`]: the
//! membership output has to move to its own cluster, while markers stay alongside the seed topic on
//! ingestion, and one shared producer would force them to move together.
//!
//! Two topic properties the seeder's watcher depends on, recorded here because the topic is
//! provisioned in another repo and either would fail silently:
//!
//! - `cleanup.policy=delete`. Every partition marker of a run shares one key (see
//!   [`reconcile_complete_key`]), so compaction would retain one of the 64 and erase the rest.
//! - A stable partition count. The watcher captures a start offset per partition at dispatch and is
//!   assigned exactly those, so a partition added mid-run is never read and holds the run open.

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

/// No-op marker sink for when the reconcile gate is off: satisfies the [`ReconcileMarkerSink`] slot
/// without a Kafka producer. Nothing can produce through it, because a reconcile job is only ever
/// admitted from a seed tile and `ReconcileDeps::enabled` gates that admission. Pairing this sink
/// with `enabled: true` would break that: it acks every marker without producing one, so the jobs
/// would complete and commit their seed offsets while the seeder saw no certificate at all.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoopReconcileMarkerSink;

#[async_trait]
impl ReconcileMarkerSink for NoopReconcileMarkerSink {
    async fn produce(
        &self,
        markers: Vec<ReconcileCompleteMarker>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        markers.iter().map(|_| Ok(())).collect()
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

fn reconcile_complete_key(marker: &ReconcileCompleteMarker) -> Option<String> {
    Some(format!(
        "{}:{}:{}",
        marker.team_id().0,
        marker.cohort_id().0,
        marker.run_id().0
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
    fn reconcile_complete_key_identifies_the_run_without_the_partition() {
        assert_eq!(
            reconcile_complete_key(&marker(63)),
            Some("42:91204:00000000-0000-0000-0000-000000000000".to_string())
        );
        assert_eq!(
            reconcile_complete_key(&marker(63)),
            reconcile_complete_key(&marker(0)),
            "all partition markers for one run share the same Kafka key",
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
