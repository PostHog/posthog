use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;
use health::HealthRegistry;
use std::time::Duration;
use tokio::sync::oneshot;
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
    shutdown_tx: Option<oneshot::Sender<()>>,
}

// FallbackSink attempts to send events to the primary sink, and if it fails, it will send events to the fallback sink.
// Optionally pass in a health registry to stop attempting to send events to the primary sink if it becomes unhealthy.
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
            shutdown_tx: None,
        }
    }
    pub fn new_with_health<P, F>(
        primary: P,
        fallback: F,
        health_registry: HealthRegistry,
        primary_component_name: String,
    ) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        if !health_registry
            .get_status()
            .components
            .contains_key(&primary_component_name)
        {
            panic!("health registry does not contain primary component {primary_component_name}")
        }

        let (shutdown_tx, mut shutdown_rx) = oneshot::channel();
        let primary_is_healthy = Arc::new(AtomicBool::new(true));
        let thread_healthy = primary_is_healthy.clone();
        gauge!("capture_primary_sink_health").set(1.0);

        // Asynchronously update primary health status every 10 seconds
        // this means if the primary starts failing we'll stop trying to send to it until it recovers.
        task::spawn(async move {
            loop {
                tokio::select! {
                    _ = sleep(Duration::from_millis(10000)) => {
                        let is_healthy = health_registry
                            .get_status()
                            .components
                            .get(&primary_component_name)
                            .map(|c| c.is_healthy())
                            .unwrap_or(false);
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
                    _ = &mut shutdown_rx => {
                        break;
                    }
                }
            }
        });

        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
            primary_is_healthy,
            shutdown_tx: Some(shutdown_tx),
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

impl Drop for FallbackSink {
    fn drop(&mut self) {
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            drop(shutdown_tx);
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
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                is_cookieless_mode: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
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
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                is_cookieless_mode: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
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
