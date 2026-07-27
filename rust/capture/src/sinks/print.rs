use async_trait::async_trait;

use metrics::{counter, histogram};
use tracing::log::info;

use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

#[async_trait]
impl Event for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        info!("single event: {:?}", event);
        counter!("capture_events_ingested_total").increment(1);

        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        histogram!("capture_event_batch_size").record(events.len() as f64);
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        for event in events {
            info!("event: {event:?}");
        }

        Ok(())
    }
}

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
