use async_trait::async_trait;

use metrics::counter;
use tracing::log::info;

use crate::api::CaptureError;
use crate::outputs::PublishEvents;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

#[async_trait]
impl PublishEvents for PrintSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        counter!("capture_events_ingested_total").increment(events.len() as u64);
        for event in events {
            info!("event: {event:?}");
        }

        Ok(())
    }
}
