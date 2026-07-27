use async_trait::async_trait;
use metrics::counter;

use crate::sinks::sink::{AddressedPayload, Sink, SinkResult};

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl Sink for NoOpSink {
    async fn publish(&self, prepared: Vec<AddressedPayload>) -> Vec<SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|p| SinkResult::ok(p.uuid))
            .collect()
    }
}
