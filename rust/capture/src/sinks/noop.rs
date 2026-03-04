use async_trait::async_trait;

use metrics::{counter, histogram};

use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

pub struct NoOpSink {}

#[async_trait]
impl Event for NoOpSink {
    async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
        counter!("capture_events_ingested_total").increment(1);
        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        Ok(())
    }
}
