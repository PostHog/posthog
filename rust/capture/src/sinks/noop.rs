use async_trait::async_trait;
use metrics::counter;

use crate::api::CaptureError;
use crate::v0_request::ProcessedEvent;

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl crate::sinks::sink::Prepare for NoOpSink {
    /// Serialized like any other backend so the payload shape stays uniform —
    /// a noop deployment still exercises the real prep path.
    async fn prepare_batch(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<crate::sinks::sink::PreparedPayload>, CaptureError> {
        let serializer = crate::serialization::Serializer::json();
        events
            .into_iter()
            .map(|event| {
                let payload = serializer.serialize(&event.event)?;
                Ok(crate::sinks::sink::PreparedPayload {
                    uuid: event.event.uuid,
                    record: crate::sinks::producer::ProduceRecord {
                        topic: String::new(),
                        key: None,
                        payload,
                        headers: event.event.to_headers(),
                    },
                })
            })
            .collect()
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
