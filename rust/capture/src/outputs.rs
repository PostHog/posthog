//! The outputs layer: the produce surface above the sinks.
//!
//! An [`Output`] is a published-to destination: either a single backend
//! leaf, or a policy composing two child outputs. Today the one policy is
//! failover (health-gated Kafka primary with an S3 secondary). Policies
//! operate on *events*, before any payload prep, so each target resolves
//! topics and serializes for itself, exactly like the per-sink `send_batch`
//! paths the old composites delegated to.
//!
//! Leaves run the prep → publish → fold dance internally via the
//! [`Prepare`] trait, so no caller ever sees a two-phase protocol. The prep
//! hoist (see the plan doc) later moves payload assembly into this layer
//! and retires the trait.
//!
//! [`OutputTable`] is the address table the deployment state holds. It is
//! degenerate today: one deployment-wide output serves every (pipeline,
//! lane) address, and per-lane topics still resolve during prep via the
//! `OutputRegistry`. Call sites keep publishing through the v0 `Event`
//! trait, served by the transitional facade implemented on the table; the
//! call-site migration retires that facade together with the trait.

use async_trait::async_trait;
use metrics::{counter, gauge, histogram};
use tracing::instrument;
use tracing::log::error;

use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

/// The leaf produce contract: run prep, publish, and fold internally and
/// report the v0 whole-request result. Payload assembly stays inside the
/// backend until the prep hoist moves it into this layer, which is also
/// when this trait is deleted.
#[async_trait]
pub(crate) trait Prepare: Send + Sync {
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError>;

    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;

    /// Flush any buffered/pending data before shutdown. Default is no-op.
    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

/// A destination events are published to: a single backend, or a policy
/// over two child outputs. Targets are outputs themselves, so a future
/// policy (a split for the next cluster migration) composes over pairs the
/// way the old sink composites did.
pub struct Output {
    inner: Inner,
}

enum Inner {
    Single(Box<dyn Prepare>),
    Failover(Failover),
}

impl Output {
    /// A single-backend output.
    pub(crate) fn single<L: Prepare + 'static>(leaf: L) -> Self {
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
impl Prepare for Output {
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        match &self.inner {
            Inner::Single(leaf) => leaf.publish_one(event).await,
            Inner::Failover(failover) => failover.publish_one(event).await,
        }
    }

    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        match &self.inner {
            Inner::Single(leaf) => leaf.publish_batch(events).await,
            Inner::Failover(failover) => failover.publish_batch(events).await,
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        match &self.inner {
            Inner::Single(leaf) => leaf.flush(),
            Inner::Failover(failover) => failover.flush(),
        }
    }
}

/// The failover policy node. Skips the primary while the advisory handle
/// reports unhealthy, re-publishes on the fallback after a retriable
/// primary failure, and never fails over a fatal error.
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
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if healthy {
            match self.primary.publish_one(event.clone()).await {
                Ok(()) => Ok(()),
                Err(CaptureError::RetryableSinkError) => {
                    error!("Primary output failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.fallback.publish_one(event).await
                }
                Err(e) => Err(e),
            }
        } else {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.publish_one(event).await
        }
    }

    #[instrument(skip_all)]
    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if healthy {
            match self.primary.publish_batch(events.clone()).await {
                Ok(()) => Ok(()),
                Err(CaptureError::RetryableSinkError) => {
                    error!("Primary output failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.fallback.publish_batch(events).await
                }
                Err(e) => Err(e),
            }
        } else {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.publish_batch(events).await
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()
    }
}

/// The (pipeline, lane) → output table the deployment state holds.
/// Degenerate today: one deployment-wide output serves every address, and
/// per-lane topics resolve during prep via the `OutputRegistry`.
pub struct OutputTable {
    output: Output,
}

impl OutputTable {
    pub fn new(output: Output) -> Self {
        Self { output }
    }
}

/// Transitional facade serving the existing `Event` call sites from the
/// table until they migrate to publishing through it directly. Records
/// `capture_event_batch_size` because the sink impls that used to record
/// it no longer sit on this path. Two deliberate recording deltas against
/// the old composites: the histogram now records when a batch goes to the
/// S3 fallback (it silently didn't), and print/noop single sends record it
/// (they didn't).
#[async_trait]
impl Event for OutputTable {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(1.0);
        self.output.publish_one(event).await
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        self.output.publish_batch(events).await
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
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
    impl Prepare for FailLeaf {
        async fn publish_one(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
            Err(self.0.clone())
        }

        async fn publish_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
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
            .publish_one(test_event())
            .await
            .expect("Failed to send event");

        let batch = vec![test_event(), test_event()];
        output
            .publish_batch(batch)
            .await
            .expect("Failed to send batch");

        assert_eq!(fallback.get_events().len(), 3);
    }

    #[tokio::test]
    async fn failover_reports_the_error_when_both_targets_fail() {
        let output = Output::failover(
            Output::single(FailLeaf(CaptureError::RetryableSinkError)),
            Output::single(FailLeaf(CaptureError::RetryableSinkError)),
            None,
        );

        assert!(matches!(
            output.publish_one(test_event()).await,
            Err(CaptureError::RetryableSinkError)
        ));

        let batch = vec![test_event(), test_event()];
        assert!(matches!(
            output.publish_batch(batch).await,
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
            output.publish_one(test_event()).await,
            Err(CaptureError::NonRetryableSinkError)
        ));
        assert!(matches!(
            output.publish_batch(vec![test_event()]).await,
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

        // Advisory handle starts healthy
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish_one(test_event()).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (1, 0),
            "primary should serve while the kafka advisory reports healthy"
        );

        // Let the advisory handle's deadline expire without calling report_healthy
        tokio::time::sleep(Duration::from_millis(400)).await;
        output.publish_one(test_event()).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (1, 1),
            "fallback should serve when the kafka advisory deadline expires"
        );

        // Recovery: report healthy again
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        output.publish_one(test_event()).await.unwrap();
        assert_eq!(
            (primary.get_events().len(), fallback.get_events().len()),
            (2, 1),
            "primary should recover when the kafka advisory reports healthy again"
        );
    }

    #[tokio::test]
    async fn table_facade_serves_event_call_sites() {
        let leaf = MockSink::new();
        let table = OutputTable::new(Output::single(leaf.clone()));

        table.send(test_event()).await.unwrap();
        table
            .send_batch(vec![test_event(), test_event()])
            .await
            .unwrap();

        assert_eq!(leaf.get_events().len(), 3);
        table.flush().unwrap();
    }
}
