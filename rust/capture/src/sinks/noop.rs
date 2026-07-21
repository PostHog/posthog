use async_trait::async_trait;
use metrics::{counter, histogram};

use crate::api::CaptureError;
use crate::sinks::sink::{fold_results, passthrough_record, PreparedRecord, Sink, SinkResult};
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

/// A sink that silently drops every event (counting it). Real work lives in the
/// [`Sink`] impl; [`Event`] is a thin shim that prepares then publishes.
#[async_trait]
impl Sink for NoOpSink {
    async fn prepare(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedRecord>, CaptureError> {
        // Silent drop: no serialization, just carry each uuid for correlation.
        Ok(events
            .into_iter()
            .map(|event| passthrough_record(&event, Vec::new()))
            .collect())
    }

    async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|record| SinkResult::ok(record.uuid))
            .collect()
    }
}

#[async_trait]
impl Event for NoOpSink {
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
