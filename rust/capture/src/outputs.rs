//! The outputs layer: the produce surface above the sinks.
//!
//! An [`Output`] is a published-to destination: either a single backend
//! sink, or a policy composing two child outputs. Today the one policy is
//! failover (health-gated Kafka primary with an S3 secondary).
//!
//! Outputs take two routes. The v0 event route ([`PublishEvents`]) hands over
//! events before any payload prep, so each target resolves topics and
//! serializes for itself. The prepared route ([`PublishPrepared`]) hands over
//! [`PreparedEvent`]s, already serialized and addressed, and reports one
//! result per event. Every sink and every policy serves both.

use async_trait::async_trait;
use common_types::CapturedEventHeaders;
use metrics::{counter, gauge};
use tracing::instrument;
use tracing::log::error;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::ordering::OrderingGuarantee;
use crate::pipeline::Address;
use crate::sinks::sink::{Outcome, SinkResult};
use crate::v0_request::ProcessedEvent;

/// The sink produce contract: run prep, publish, and fold internally and
/// report the v0 whole-request result, so no caller sees a two-phase
/// protocol.
///
/// `pub` rather than `pub(crate)` because the integration suites in
/// `tests/` stand their own capturing sinks in as outputs; there is
/// no other reason to implement it outside this crate.
#[async_trait]
pub trait PublishEvents: Send + Sync {
    /// One method for any batch size: a backend that serves a one-event
    /// batch more cheaply specializes inside its own impl.
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

#[derive(Debug, Clone)]
pub struct PreparedEvent {
    pub uuid: Uuid,
    pub address: Address,
    pub partition_key: String,
    pub ordering: OrderingGuarantee,
    pub payload: bytes::Bytes,
    pub headers: CapturedEventHeaders,
}

/// Returns one [`SinkResult`] per input event, in input order. A failure is
/// reported in that event's result and does not affect the other events.
#[async_trait]
pub trait PublishPrepared: Send + Sync {
    async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult>;
}

pub trait Sink: PublishEvents + PublishPrepared {}

impl<T: PublishEvents + PublishPrepared> Sink for T {}

pub struct Output {
    inner: Inner,
}

enum Inner {
    Single(Box<dyn Sink>),
    Failover(Failover),
}

impl Output {
    pub fn single<S: Sink + 'static>(sink: S) -> Self {
        Self {
            inner: Inner::Single(Box::new(sink)),
        }
    }

    /// Health-gated failover over two outputs. While the advisory handle
    /// reports unhealthy the primary is skipped entirely; without a handle
    /// the primary is always tried first. A retriable primary failure
    /// re-publishes the batch on the fallback, or on the prepared route only
    /// the events that failed. Any other error is final:
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
            Inner::Single(sink) => sink.publish_events(events).await,
            Inner::Failover(failover) => failover.publish_events(events).await,
        }
    }
}

#[async_trait]
impl PublishPrepared for Output {
    async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult> {
        match &self.inner {
            Inner::Single(sink) => sink.publish_prepared(events).await,
            Inner::Failover(failover) => failover.publish_prepared(events).await,
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

    #[instrument(skip_all)]
    async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if !healthy {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            return self.fallback.publish_prepared(events).await;
        }

        let mut results = self.primary.publish_prepared(events.clone()).await;
        debug_assert_eq!(results.len(), events.len());
        // Retry by position, not uuid: v0 accepts client-supplied uuids
        // unchecked, so a batch can repeat one.
        let retry: Vec<usize> = results
            .iter()
            .enumerate()
            .filter(|(_, result)| {
                matches!(
                    result.outcome,
                    Outcome::Failed(CaptureError::RetryableSinkError)
                )
            })
            .map(|(idx, _)| idx)
            .collect();
        if retry.is_empty() {
            return results;
        }

        error!("Primary output failed, falling back");
        counter!("capture_fallback_sink_failovers_total").increment(1);
        let mut events: Vec<Option<PreparedEvent>> = events.into_iter().map(Some).collect();
        let retry_events = retry.iter().filter_map(|&idx| events[idx].take()).collect();
        let fallback_results = self.fallback.publish_prepared(retry_events).await;
        for (idx, result) in retry.into_iter().zip(fallback_results) {
            results[idx] = result;
        }
        results
    }
}

/// The (pipeline, lane) → output map the deployment state holds. One
/// deployment-wide output serves every address; the Kafka sink resolves
/// per-lane topics through its [`OutputTable`] at enqueue.
///
/// [`OutputTable`]: crate::sinks::registry::OutputTable
pub struct OutputRegistry {
    output: Output,
}

impl OutputRegistry {
    pub fn new(output: Output) -> Self {
        Self { output }
    }

    pub fn single<S: Sink + 'static>(sink: S) -> Self {
        Self::new(Output::single(sink))
    }

    /// Per-event failures collapse to a whole-request `CaptureError`.
    ///
    /// Callers record `capture_event_batch_size` themselves: batch size is a
    /// property of the request, not of the output it lands on.
    pub async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.output.publish_events(events).await
    }

    pub async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult> {
        self.output.publish_prepared(events).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::{AnalyticsLane, PipelineLane};
    use crate::sinks::test_sink::MockSink;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    struct FailSink(CaptureError);

    #[async_trait]
    impl PublishEvents for FailSink {
        async fn publish_events(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            Err(self.0.clone())
        }
    }

    #[async_trait]
    impl PublishPrepared for FailSink {
        async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult> {
            events
                .iter()
                .map(|event| SinkResult::failed(event.uuid, self.0.clone()))
                .collect()
        }
    }

    #[derive(Clone, Default)]
    struct PreparedSink {
        failures: Arc<HashMap<Uuid, CaptureError>>,
        seen: Arc<Mutex<Vec<Uuid>>>,
    }

    impl PreparedSink {
        fn failing(failures: impl IntoIterator<Item = (Uuid, CaptureError)>) -> Self {
            Self {
                failures: Arc::new(failures.into_iter().collect()),
                ..Self::default()
            }
        }

        fn seen(&self) -> Vec<Uuid> {
            self.seen.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl PublishEvents for PreparedSink {
        async fn publish_events(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            unreachable!("prepared-route tests publish prepared events")
        }
    }

    #[async_trait]
    impl PublishPrepared for PreparedSink {
        async fn publish_prepared(&self, events: Vec<PreparedEvent>) -> Vec<SinkResult> {
            self.seen
                .lock()
                .unwrap()
                .extend(events.iter().map(|event| event.uuid));
            events
                .iter()
                .map(|event| match self.failures.get(&event.uuid) {
                    Some(err) => SinkResult::failed(event.uuid, err.clone()),
                    None => SinkResult::published(event.uuid),
                })
                .collect()
        }
    }

    fn prepared_event() -> PreparedEvent {
        let event = test_event().event;
        PreparedEvent {
            uuid: Uuid::now_v7(),
            address: Address::Lane(PipelineLane::Analytics(AnalyticsLane::Main)),
            partition_key: event.key(),
            ordering: OrderingGuarantee::PerDistinctId,
            payload: bytes::Bytes::from_static(b"{}"),
            headers: event.to_headers(),
        }
    }

    fn outcomes(results: Vec<SinkResult>) -> Vec<(Uuid, Option<String>)> {
        results
            .into_iter()
            .map(|result| match result.outcome {
                Outcome::Published => (result.uuid, None),
                Outcome::Failed(err) => (result.uuid, Some(format!("{err:?}"))),
            })
            .collect()
    }

    fn failed(err: CaptureError) -> Option<String> {
        Some(format!("{err:?}"))
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
            Output::single(FailSink(CaptureError::RetryableSinkError)),
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
            Output::single(FailSink(CaptureError::RetryableSinkError)),
            Output::single(FailSink(CaptureError::RetryableSinkError)),
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
            Output::single(FailSink(CaptureError::NonRetryableSinkError)),
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
        let sink = MockSink::new();
        let registry = OutputRegistry::single(sink.clone());

        registry.publish(vec![test_event()]).await.unwrap();
        registry
            .publish(vec![test_event(), test_event()])
            .await
            .unwrap();

        assert_eq!(sink.get_events().len(), 3);
    }

    #[tokio::test]
    async fn prepared_route_reports_one_result_per_event_in_order() {
        let events = vec![prepared_event(), prepared_event(), prepared_event()];
        let uuids: Vec<Uuid> = events.iter().map(|event| event.uuid).collect();
        let sink = PreparedSink::failing([(uuids[1], CaptureError::NonRetryableSinkError)]);
        let registry = OutputRegistry::single(sink.clone());

        let results = outcomes(registry.publish_prepared(events).await);

        assert_eq!(
            results,
            vec![
                (uuids[0], None),
                (uuids[1], failed(CaptureError::NonRetryableSinkError)),
                (uuids[2], None),
            ]
        );
        assert_eq!(sink.seen(), uuids);
    }

    #[tokio::test]
    async fn prepared_failover_republishes_only_retriable_events() {
        let events = vec![prepared_event(), prepared_event(), prepared_event()];
        let uuids: Vec<Uuid> = events.iter().map(|event| event.uuid).collect();
        let primary = PreparedSink::failing([
            (uuids[1], CaptureError::RetryableSinkError),
            (uuids[2], CaptureError::NonRetryableSinkError),
        ]);
        let fallback = PreparedSink::default();
        let output = Output::failover(
            Output::single(primary.clone()),
            Output::single(fallback.clone()),
            None,
        );

        let results = outcomes(output.publish_prepared(events).await);

        assert_eq!(
            results,
            vec![
                (uuids[0], None),
                (uuids[1], None),
                (uuids[2], failed(CaptureError::NonRetryableSinkError)),
            ],
            "a fatal primary failure is final; a retriable one takes the fallback's result"
        );
        assert_eq!(primary.seen(), uuids);
        assert_eq!(fallback.seen(), vec![uuids[1]]);
    }

    #[tokio::test]
    async fn prepared_failover_leaves_the_fallback_idle_when_the_primary_succeeds() {
        let fallback = PreparedSink::default();
        let output = Output::failover(
            Output::single(PreparedSink::default()),
            Output::single(fallback.clone()),
            None,
        );

        let results = outcomes(
            output
                .publish_prepared(vec![prepared_event(), prepared_event()])
                .await,
        );

        assert!(results.iter().all(|(_, err)| err.is_none()));
        assert!(fallback.seen().is_empty());
    }

    #[tokio::test]
    async fn prepared_failover_reports_the_fallback_failure() {
        let output = Output::failover(
            Output::single(FailSink(CaptureError::RetryableSinkError)),
            Output::single(FailSink(CaptureError::RetryableSinkError)),
            None,
        );

        let results = outcomes(output.publish_prepared(vec![prepared_event()]).await);

        assert_eq!(results[0].1, failed(CaptureError::RetryableSinkError));
    }

    #[tokio::test]
    async fn prepared_failover_skips_an_unhealthy_primary() {
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
        let _monitor = manager.monitor_background();

        let primary = PreparedSink::default();
        let fallback = PreparedSink::default();
        let output = Output::failover(
            Output::single(primary.clone()),
            Output::single(fallback.clone()),
            Some(kafka_handle.clone()),
        );

        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(400)).await;
        let event = prepared_event();
        let uuid = event.uuid;
        output.publish_prepared(vec![event]).await;

        assert!(primary.seen().is_empty());
        assert_eq!(fallback.seen(), vec![uuid]);
    }
}
