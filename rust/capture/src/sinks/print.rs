use async_trait::async_trait;

use metrics::{counter, histogram};
use tracing::log::info;

use crate::api::CaptureError;
use crate::sinks::sink::{fold_results, passthrough_record, PreparedRecord, Sink, SinkResult};
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

/// A debug sink that logs every event and counts it. Real work lives in the
/// [`Sink`] impl; [`Event`] is a thin shim that prepares then publishes.
#[async_trait]
impl Sink for PrintSink {
    async fn prepare(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedRecord>, CaptureError> {
        events
            .into_iter()
            .map(|event| {
                let payload = serde_json::to_vec(&event.event)?;
                Ok(passthrough_record(&event, payload))
            })
            .collect()
    }

    async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|record| {
                info!("event: {}", String::from_utf8_lossy(&record.record.payload));
                SinkResult::ok(record.uuid)
            })
            .collect()
    }
}

#[async_trait]
impl Event for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let prepared = self.prepare(vec![event]).await?;
        fold_results(self.publish_batch(prepared).await)
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        histogram!("capture_event_batch_size").record(events.len() as f64);
        let prepared = self.prepare(events).await?;
        fold_results(self.publish_batch(prepared).await)
    }
}
