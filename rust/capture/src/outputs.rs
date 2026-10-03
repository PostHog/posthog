//! The outputs layer: the produce surface above the sinks.
//!
//! An [`Output`] is a published-to destination: either a single backend
//! leaf, or a policy composing two child outputs. Today the one policy is
//! failover (health-gated Kafka primary with an S3 secondary). Policies
//! operate on *events*, before any payload prep, so each target resolves
//! topics and serializes for itself.

use async_trait::async_trait;
use metrics::{counter, gauge};
use tracing::instrument;
use tracing::log::error;

use crate::api::CaptureError;
use crate::v0_request::ProcessedEvent;

/// The leaf produce contract: run prep, publish, and fold internally and
/// report the v0 whole-request result, so no caller sees a two-phase
/// protocol.
///
/// `pub` rather than `pub(crate)` because the integration suites in
/// `tests/` stand their own capturing sinks in as output leaves; there is
/// no other reason to implement it outside this crate.
#[async_trait]
pub trait PublishEvents: Send + Sync {
    /// One method for any batch size: a backend that serves a one-event
    /// batch more cheaply specializes inside its own impl.
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;

    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

pub struct Output {
    inner: Inner,
}

enum Inner {
    Single(Box<dyn PublishEvents>),
    Failover(Failover),
}

impl Output {
    pub fn single<L: PublishEvents + 'static>(leaf: L) -> Self {
        Self {
            inner: Inner::Single(Box::new(leaf)),
        }
    }

    /// Health-gated failover over two outputs. While the advisory handle
    /// reports unhealthy the primary is skipped entirely; without a handle
    /// the primary is always tried first. A retriable primary failure
    /// re-publishes the batch on the fallback. Any other error is final:
    /// a non-retryable error is a property of the event, not the backend,
    /// so the fallback would reject it too.
    pub(crate) fn failover(
        primary: Output,
        fallback: Output,
        advisory_handle: Option<lifecycle::Handle>,
    ) -> Self {
        if advisory_handle.is_some() {
            gauge!("capture_primary_sink_health").set(1.0);
        }
        Self {
            inner: Inner::Failover(Failover {
                primary: Box::new(primary),
                fallback: Box::new(fallback),
                advisory_handle,
            }),
        }
    }
}

// `async_trait` boxes these futures, which is what lets the failover arm
// recurse into its child outputs without building an infinitely-sized
// future type.
#[async_trait]
impl PublishEvents for Output {
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        match &self.inner {
            Inner::Single(leaf) => leaf.publish_events(events).await,
            Inner::Failover(failover) => failover.publish_events(events).await,
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        match &self.inner {
            Inner::Single(leaf) => leaf.flush(),
            Inner::Failover(failover) => failover.flush(),
        }
    }
}

struct Failover {
    primary: Box<Output>,
    fallback: Box<Output>,
    advisory_handle: Option<lifecycle::Handle>,
}

impl Failover {
    fn primary_is_healthy(&self) -> bool {
        self.advisory_handle
            .as_ref()
            .map(|h| h.is_healthy())
            .unwrap_or(true)
    }

    #[instrument(skip_all)]
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if healthy {
            match self.primary.publish_events(events.clone()).await {
                Ok(()) => Ok(()),
                Err(CaptureError::RetryableSinkError) => {
                    error!("Primary output failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.fallback.publish_events(events).await
                }
                Err(e) => Err(e),
            }
        } else {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.publish_events(events).await
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()
    }
}

/// The (pipeline, lane) → output map the deployment state holds.
/// Degenerate today: one deployment-wide output serves every address, and
/// per-lane topics resolve during prep via the [`TopicTable`].
///
/// [`TopicTable`]: crate::sinks::registry::TopicTable
pub struct OutputRegistry {
    output: Output,
}

impl OutputRegistry {
    pub fn new(output: Output) -> Self {
        Self { output }
    }

    pub fn single<L: PublishEvents + 'static>(leaf: L) -> Self {
        Self::new(Output::single(leaf))
    }

    /// Per-event failures collapse to a whole-request `CaptureError`.
    ///
    /// Callers record `capture_event_batch_size` themselves: batch size is a
    /// property of the request, not of the output it lands on.
    pub async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.output.publish_events(events).await
    }

    pub fn flush(&self) -> Result<(), anyhow::Error> {
        self.output.flush()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::test_sink::MockSink;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::time::Duration;

    struct FailLeaf(CaptureError);

    #[async_trait]
    impl PublishEvents for FailLeaf {
        async fn publish_events(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            Err(self.0.clone())
        }
    }

    fn test_event() -> ProcessedEvent {
        let timestamp = chrono::DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "test_id".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                skip_heatmap_processing: false,
                overflow_reason: None,
                distinct_id_truncated_from: None,
            },
        }
    }

    #[tokio::test]
    async fn failover_republishes_on_retriable_primary_failure() {
        let fallback = MockSink::new();
        let output = Output::failover(
            Output::single(FailLeaf(CaptureError::RetryableSinkError)),
            Output::single(fallback.clone()),
            None,
        );

        output
            .publish_events(vec![test_event(), test_event()])
            .await
            .expect("Failed to publish batch");

        assert_eq!(fallback.get_events().len(), 2);
    }

    #[tokio::test]
    async fn failover_reports_the_error_when_both_targets_fail() {
        let output = Output::failover(
            Output::single(FailLeaf(CaptureError::RetryableSinkError)),
            Output::single(FailLeaf(CaptureError::RetryableSinkError)),
            None,
        );

        assert!(matches!(
            output
                .publish_events(vec![test_event(), test_event()])
                .await,
            Err(CaptureError::RetryableSinkError)
        ));
    }

    #[tokio::test]
    async fn fatal_primary_error_does_not_fail_over() {
        let fallback = MockSink::new();
        let output = Output::failover(
            Output::single(FailLeaf(CaptureError::NonRetryableSinkError)),
            Output::single(fallback.clone()),
            None,
        );

        assert!(matches!(
            output.publish_events(vec![test_event()]).await,
            Err(CaptureError::NonRetryableSinkError)
        ));

        assert!(
            fallback.get_events().is_empty(),
            "a fatal primary error must not reach the fallback"
        );
    }

    #[tokio::test]
    async fn advisory_handle_controls_primary_health() {
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_health_poll_interval(Duration::from_millis(50))
            .build();

        let kafka_handle = manager.register(
            "kafka-advisory",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(Duration::from_millis(200))
                .is_advisory(true),
        );
        let _s3_handle = manager.register(
            "s3-sink",
            lifecycle::ComponentOptions::new().with_liveness_deadline(Duration::from_millis(200)),
        );

        let _monitor = manager.monitor_background();

        let primary = MockSink::new();
        let fallback = MockSink::new();
        let output = Output::failover(
            Output::single(primary.clone()),
            Output::single(fallback.clone()),
            Some(kafka_handle.clone()),
        );

        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish_events(vec![test_event()]).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (1, 0),
            "primary should serve while the kafka advisory reports healthy"
        );

        // Let the advisory handle's deadline expire without calling report_healthy
        tokio::time::sleep(Duration::from_millis(400)).await;
        output.publish_events(vec![test_event()]).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (1, 1),
            "fallback should serve when the kafka advisory deadline expires"
        );

        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish_events(vec![test_event()]).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (2, 1),
            "primary should recover when the kafka advisory reports healthy again"
        );
    }

    #[tokio::test]
    async fn registry_publishes_to_its_output() {
        let leaf = MockSink::new();
        let registry = OutputRegistry::single(leaf.clone());

        registry.publish(vec![test_event()]).await.unwrap();
        registry
            .publish(vec![test_event(), test_event()])
            .await
            .unwrap();

        assert_eq!(leaf.get_events().len(), 3);
        registry.flush().unwrap();
    }
}
