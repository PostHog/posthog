use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

use async_trait::async_trait;
use metrics::{counter, gauge};
use std::sync::Arc;
use tracing::instrument;
use tracing::log::error;

pub struct FallbackSink {
    primary: Arc<Box<dyn Event + Send + Sync + 'static>>,
    fallback: Arc<Box<dyn Event + Send + Sync + 'static>>,
    advisory_handle: Option<lifecycle::Handle>,
}

/// FallbackSink attempts to send events to the primary sink, and if it fails,
/// it will send events to the fallback sink. When an advisory lifecycle handle
/// is provided, it skips the primary entirely while the handle reports unhealthy.
impl FallbackSink {
    pub fn new<P, F>(primary: P, fallback: F) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
            advisory_handle: None,
        }
    }

    pub fn new_with_advisory<P, F>(
        primary: P,
        fallback: F,
        advisory_handle: lifecycle::Handle,
    ) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        gauge!("capture_primary_sink_health").set(1.0);
        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
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
impl Event for FallbackSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if healthy {
            match self.primary.send(event.clone()).await {
                Ok(_) => Ok(()),
                Err(CaptureError::RetryableSinkError) => {
                    error!("Primary sink failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.fallback.send(event).await
                }
                Err(e) => Err(e),
            }
        } else {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.send(event).await
        }
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let healthy = self.primary_is_healthy();
        gauge!("capture_primary_sink_health").set(if healthy { 1.0 } else { 0.0 });

        if healthy {
            match self.primary.send_batch(events.clone()).await {
                Ok(_) => Ok(()),
                Err(CaptureError::RetryableSinkError) => {
                    error!("Primary sink failed, falling back");
                    counter!("capture_fallback_sink_failovers_total").increment(1);
                    self.fallback.send_batch(events).await
                }
                Err(e) => Err(e),
            }
        } else {
            counter!("capture_fallback_sink_failovers_total").increment(1);
            self.fallback.send_batch(events).await
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.primary.flush()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::print::PrintSink;
    use crate::utils::uuid_v7;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use std::time::Duration;

    #[derive(Clone)]
    pub struct FailSink {}

    #[async_trait]
    impl Event for FailSink {
        async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
            Err(CaptureError::RetryableSinkError)
        }
        async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            Err(CaptureError::RetryableSinkError)
        }
    }

    #[tokio::test]
    async fn test_fallback_sink() {
        let fail_sink = FailSink {};
        let print_sink = PrintSink {};

        let fallback_sink = FallbackSink::new(fail_sink, print_sink);

        // Create test event
        let event = ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7(),
                distinct_id: "test_id".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&chrono::Utc),
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
        let event = ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7(),
                distinct_id: "test_id".to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
                    .unwrap()
                    .with_timezone(&chrono::Utc),
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
