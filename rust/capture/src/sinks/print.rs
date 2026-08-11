use async_trait::async_trait;

use metrics::{counter, histogram};
use tracing::log::info;

use crate::api::CaptureError;
use crate::outputs::Prepare;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

/// No `capture_event_batch_size` here: the outputs facade records it for
/// every backend uniformly, where the retiring `Event` impl records it
/// itself.
#[async_trait]
impl Prepare for PrintSink {
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        info!("single event: {:?}", event);
        counter!("capture_events_ingested_total").increment(1);

        Ok(())
    }

    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        counter!("capture_events_ingested_total").increment(events.len() as u64);
        for event in events {
            info!("event: {event:?}");
        }

        Ok(())
    }
}

#[async_trait]
impl Event for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        Prepare::publish_one(self, event).await
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        Prepare::publish_batch(self, events).await
    }
}
