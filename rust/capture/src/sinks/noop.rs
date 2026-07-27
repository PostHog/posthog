use async_trait::async_trait;
use metrics::counter;

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl crate::sinks::sink::Sink for NoOpSink {
    async fn publish(
        &self,
        prepared: Vec<crate::sinks::sink::PreparedPayload>,
    ) -> Vec<crate::sinks::sink::SinkResult> {
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        prepared
            .into_iter()
            .map(|p| crate::sinks::sink::SinkResult::ok(p.uuid))
            .collect()
    }
}
