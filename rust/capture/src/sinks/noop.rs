use async_trait::async_trait;
use metrics::counter;

use crate::api::CaptureError;
use crate::outputs::PublishEvents;
use crate::v0_request::ProcessedEvent;

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl PublishEvents for NoOpSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        Ok(())
    }
}
