use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;
use lifecycle::Handle as LifecycleHandle;
use std::time::Duration;
use tokio::task;
use tokio::time::sleep;

use async_trait::async_trait;
use metrics::{counter, gauge};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tracing::instrument;
use tracing::log::{error, warn};

pub struct FallbackSink {
    primary: Arc<Box<dyn Event + Send + Sync + 'static>>,
    fallback: Arc<Box<dyn Event + Send + Sync + 'static>>,
    primary_is_healthy: Arc<AtomicBool>,
}

/// Attempts to send events to the primary sink, falling back to the secondary
/// when the primary is unhealthy or returns a retryable error.
impl FallbackSink {
    pub fn new<P, F>(primary: P, fallback: F) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
            primary_is_healthy: Arc::new(AtomicBool::new(true)),
        }
    }

    pub fn new_with_health<P, F>(primary: P, fallback: F, primary_handle: LifecycleHandle) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        let primary_is_healthy = Arc::new(AtomicBool::new(true));
        let thread_healthy = primary_is_healthy.clone();
        gauge!("capture_primary_sink_health").set(1.0);

        task::spawn(async move {
            loop {
                tokio::select! {
                    _ = sleep(Duration::from_millis(10000)) => {
                        let is_healthy = !primary_handle.is_shutting_down();
                        let was_healthy = thread_healthy.load(Ordering::Relaxed);
                        if was_healthy && !is_healthy {
                            error!("primary sink has become unhealthy");
                            gauge!("capture_primary_sink_health").set(0.0);
                        } else if !was_healthy && is_healthy {
                            warn!("primary sink has recovered");
                            gauge!("capture_primary_sink_health").set(1.0);
                        }
                        thread_healthy.store(is_healthy, Ordering::Relaxed);
                    }
                    _ = primary_handle.shutdown_recv() => {
                        break;
                    }
                }
            }
        });

        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
            primary_is_healthy,
        }
    }
}

#[async_trait]
impl Event for FallbackSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        if self.primary_is_healthy.load(Ordering::Relaxed) {
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
        if self.primary_is_healthy.load(Ordering::Relaxed) {
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::print::PrintSink;
    use crate::utils::uuid_v7;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;

    #[derive(Clone)]
    pub struct FailSink {}

    // sink that always fails for testing fallback
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
}
