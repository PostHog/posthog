use async_trait::async_trait;
use metrics::counter;

use crate::api::CaptureError;
use crate::kind::EventKind;
use crate::outputs::{PreparedEvent, PublishEvents, PublishPrepared};
use crate::pipeline::Lane;
use crate::sinks::sink::SinkResult;
use crate::v0_request::ProcessedEvent;

#[derive(Default)]
pub struct NoOpSink;

impl NoOpSink {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl<K: EventKind> PublishEvents<K> for NoOpSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent<K>>) -> Result<(), CaptureError> {
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        Ok(())
    }
}

#[async_trait]
impl<L: Lane> PublishPrepared<L> for NoOpSink {
    async fn publish_prepared(&self, events: Vec<PreparedEvent<L>>) -> Vec<SinkResult> {
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        events
            .into_iter()
            .map(|event| SinkResult::published(event.uuid))
            .collect()
    }
}
