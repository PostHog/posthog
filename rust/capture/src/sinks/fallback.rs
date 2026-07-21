use crate::api::CaptureError;
use crate::sinks::sink::{fold_results, Outcome, PreparedRecord, Sink, SinkResult};
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

use async_trait::async_trait;
use metrics::{counter, gauge, histogram};
use std::sync::Arc;
use tracing::instrument;
use tracing::log::error;

/// A health-gated failover wrapper over the unified [`Sink`] mechanism: it
/// tries the primary sink and, if that fails retriably (or an advisory
/// lifecycle handle reports the primary unhealthy), publishes the same prepared
/// batch to the fallback sink instead. This is the mechanism primitive the
/// automatic failover / circuit breaker (Step 11) builds on.
///
/// Both inner sinks consume the *same* prepared batch, so preparation happens
/// once (via the primary) and the failover decision lives purely in
/// [`publish_batch`](Sink::publish_batch). [`Event`] is a thin shim over this
/// trait so the current call sites stay frozen until they migrate.
pub struct FallbackSink {
    primary: Arc<dyn Sink>,
    fallback: Arc<dyn Sink>,
    advisory_handle: Option<lifecycle::Handle>,
}

impl FallbackSink {
    pub fn new<P, F>(primary: P, fallback: F) -> Self
    where
        P: Sink + 'static,
        F: Sink + 'static,
    {
        Self {
            primary: Arc::new(primary),
            fallback: Arc::new(fallback),
            advisory_handle: None,
        }
    }

    pub fn new_with_advisory<P, F>(
        primary: P,
        fallback: F,
        advisory_handle: lifecycle::Handle,
    ) -> Self
    where
        P: Sink + 'static,
        F: Sink + 'static,
    {
        gauge!("capture_primary_sink_health").set(1.0);
        Self {
            primary: Arc::new(primary),
            fallback: Arc::new(fallback),
            advisory_handle: Some(advisory_handle),
        }
    }

    fn primary_is_healthy(&self) -> bool {
        self.advisory_handle
            .as_ref()
            .map(|h| h.is_healthy())
            .unwrap_or(true)
    }
}

#[async_trait]
impl Sink for FallbackSink {
    async fn prepare(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedRecord>, CaptureError> {
        // Prepare once, through the primary; both inner sinks publish the same
        // batch, so the failover decision stays purely in `publish_batch`.
        self.primary.prepare(events).await
    }

    #[instrument(skip_all)]
    async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if !healthy {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            return self.fallback.publish_batch(prepared).await;
        }

        let results = self.primary.publish_batch(prepared.clone()).await;
        // Fail over only on a retriable failure, mirroring today's advisory
        // semantics; a fatal (non-retryable) failure is returned as-is. The
        // Kafka mechanism is fail-fast, so at most one result carries the error.
        if results
            .iter()
            .any(|r| matches!(r.outcome(), Outcome::Retriable))
        {
            error!("Primary sink failed, falling back");
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.publish_batch(prepared).await
        } else {
            results
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()
    }
}

#[async_trait]
impl Event for FallbackSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(1.0);
        let prepared = self.prepare(vec![event]).await?;
        fold_results(self.publish_batch(prepared).await)
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        let prepared = self.prepare(events).await?;
        fold_results(self.publish_batch(prepared).await)
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Sink::flush(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::print::PrintSink;
    use crate::sinks::sink::passthrough_record;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::time::Duration;

    #[derive(Clone)]
    pub struct FailSink {}

    // A primary that prepares cleanly but always fails to publish retriably, so
    // the failover path is exercised.
    #[async_trait]
    impl Sink for FailSink {
        async fn prepare(
            &self,
            events: Vec<ProcessedEvent>,
        ) -> Result<Vec<PreparedRecord>, CaptureError> {
            Ok(events
                .into_iter()
                .map(|event| passthrough_record(&event, Vec::new()))
                .collect())
        }

        async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult> {
            prepared
                .into_iter()
                .map(|record| SinkResult::err(record.uuid, CaptureError::RetryableSinkError))
                .collect()
        }
    }

    #[tokio::test]
    async fn test_fallback_sink() {
        let fail_sink = FailSink {};
        let print_sink = PrintSink {};

        let fallback_sink = FallbackSink::new(fail_sink, print_sink);

        // Create test event
        let timestamp = chrono::DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        let event = ProcessedEvent {
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
            },
        };

        // Should fail over to print sink
        fallback_sink
            .send(event.clone())
            .await
            .expect("Failed to send event");

        // Test batch
        let batch = vec![event.clone(), event.clone()];
        fallback_sink
            .send_batch(batch)
            .await
            .expect("Failed to send batch");
    }

    #[tokio::test]
    async fn test_fallback_sink_fail() {
        let fail_sink = FailSink {};
        let fallback_sink = FallbackSink::new(fail_sink.clone(), fail_sink);

        // Create test event
        let timestamp = chrono::DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        let event = ProcessedEvent {
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
            },
        };

        // Should fail over to print sink

        assert!(matches!(
            fallback_sink.send(event.clone()).await,
            Err(CaptureError::RetryableSinkError)
        ));

        // Test batch
        let batch = vec![event.clone(), event.clone()];
        assert!(matches!(
            fallback_sink.send_batch(batch).await,
            Err(CaptureError::RetryableSinkError)
        ));
    }

    #[tokio::test]
    async fn test_advisory_handle_controls_primary_health() {
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

        let sink =
            FallbackSink::new_with_advisory(PrintSink {}, PrintSink {}, kafka_handle.clone());

        // Advisory handle starts healthy
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert!(
            sink.primary_is_healthy(),
            "primary should be healthy when kafka advisory reports healthy"
        );

        // Let the advisory handle's deadline expire without calling report_healthy
        tokio::time::sleep(Duration::from_millis(400)).await;
        assert!(
            !sink.primary_is_healthy(),
            "primary should be unhealthy when kafka advisory deadline expires"
        );

        // Recovery: report healthy again
        kafka_handle.report_healthy();
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert!(
            sink.primary_is_healthy(),
            "primary should recover when kafka advisory reports healthy again"
        );
    }
}
