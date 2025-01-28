use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;
use async_trait::async_trait;
use metrics::counter;
use std::sync::Arc;
use tracing::instrument;
use tracing::log::error;

#[derive(Clone)]
pub struct FallbackSink {
    primary: Arc<Box<dyn Event + Send + Sync + 'static>>,
    fallback: Arc<Box<dyn Event + Send + Sync + 'static>>,
}

impl FallbackSink {
    pub fn new<P, F>(primary: P, fallback: F) -> Self
    where
        P: Event + Send + Sync + 'static,
        F: Event + Send + Sync + 'static,
    {
        Self {
            primary: Arc::new(Box::new(primary)),
            fallback: Arc::new(Box::new(fallback)),
        }
    }
}

#[async_trait]
impl Event for FallbackSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        match self.primary.send(event.clone()).await {
            Ok(_) => Ok(()),
            Err(e) => {
                error!("Primary sink failed, falling back: {}", e);
                counter!("capture_fallback_sink_failovers_total").increment(1);
                self.fallback.send(event).await
            }
        }
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        match self.primary.send_batch(events.clone()).await {
            Ok(_) => Ok(()),
            Err(e) => {
                error!("Primary sink failed, falling back: {}", e);
                counter!("capture_fallback_sink_failovers_total").increment(1);
                self.fallback.send_batch(events).await
            }
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
            Err(CaptureError::EventTooBig)
        }
        async fn send_batch(&self, _events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
            Err(CaptureError::EventTooBig)
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
            },
        };

        // Should fail over to print sink

        assert_eq!(
            fallback_sink.send(event.clone()).await,
            Err(CaptureError::EventTooBig)
        );

        // Test batch
        let batch = vec![event.clone(), event.clone()];
        assert_eq!(
            fallback_sink.send_batch(batch).await,
            Err(CaptureError::EventTooBig)
        );
    }
}
