use async_trait::async_trait;

use metrics::counter;
use tracing::log::info;

use crate::api::CaptureError;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

#[async_trait]
impl crate::sinks::sink::Prepare for PrintSink {
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
