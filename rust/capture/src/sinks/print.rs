use async_trait::async_trait;

use metrics::counter;
use tracing::log::info;

pub struct PrintSink {}

#[async_trait]
impl crate::sinks::sink::Sink for PrintSink {
    async fn publish(
        &self,
        prepared: Vec<crate::sinks::sink::PreparedPayload>,
    ) -> Vec<crate::sinks::sink::SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|p| {
                info!(
                    "event payload: {}",
                    String::from_utf8_lossy(&p.record.payload)
                );
                crate::sinks::sink::SinkResult::ok(p.uuid)
            })
            .collect()
    }
}
