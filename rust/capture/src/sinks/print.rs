use async_trait::async_trait;

use metrics::counter;
use tracing::log::info;

use crate::sinks::sink::{AddressedPayload, Sink, SinkResult};

pub struct PrintSink {}

#[async_trait]
impl Sink for PrintSink {
    async fn publish(&self, prepared: Vec<AddressedPayload>) -> Vec<SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|p| {
                info!("event payload: {}", String::from_utf8_lossy(&p.payload));
                SinkResult::ok(p.uuid)
            })
            .collect()
    }
}
