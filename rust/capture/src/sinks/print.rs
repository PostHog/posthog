use async_trait::async_trait;

use metrics::counter;
use tracing::log::info;

use crate::api::CaptureError;
use crate::kind::EventKind;
use crate::outputs::{PreparedEvent, PublishEvents, PublishPrepared};
use crate::pipeline::Lane;
use crate::sinks::sink::SinkResult;
use crate::v0_request::ProcessedEvent;

pub struct PrintSink {}

#[async_trait]
impl<K: EventKind> PublishEvents<K> for PrintSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent<K>>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        counter!("capture_events_ingested_total").increment(events.len() as u64);
        for event in events {
            info!("event: {event:?}");
        }

        Ok(())
    }
}

#[async_trait]
impl<L: Lane> PublishPrepared<L> for PrintSink {
    async fn publish_prepared(&self, events: Vec<PreparedEvent<L>>) -> Vec<SinkResult> {
        let span = tracing::span!(tracing::Level::INFO, "batch of prepared events");
        let _enter = span.enter();

        counter!("capture_events_ingested_total").increment(events.len() as u64);
        events
            .into_iter()
            .map(|event| {
                info!("prepared event: {event:?}");
                SinkResult::published(event.uuid)
            })
            .collect()
    }
}
