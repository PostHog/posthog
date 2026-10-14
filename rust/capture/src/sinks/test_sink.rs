//! Shared `MockSink` test helper for pipeline-level tests across the capture
//! crate.

use crate::api::CaptureError;
use crate::kind::EventKind;
use crate::outputs::{PreparedEvent, PublishEvents, PublishPrepared};
use crate::sinks::sink::SinkResult;
use crate::v0_request::ProcessedEvent;
use async_trait::async_trait;
use std::sync::{Arc, Mutex};

#[derive(Clone)]
pub(crate) struct MockSink<K> {
    pub events: Arc<Mutex<Vec<ProcessedEvent<K>>>>,
}

impl<K> Default for MockSink<K> {
    fn default() -> Self {
        Self {
            events: Arc::default(),
        }
    }
}

impl<K: Clone> MockSink<K> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get_events(&self) -> Vec<ProcessedEvent<K>> {
        self.events.lock().unwrap().clone()
    }
}

#[async_trait]
impl<K: EventKind> PublishEvents<K> for MockSink<K> {
    async fn publish_events(&self, events: Vec<ProcessedEvent<K>>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend(events);
        Ok(())
    }
}

#[async_trait]
impl<K: EventKind> PublishPrepared for MockSink<K> {
    async fn publish_prepared(&self, _events: Vec<PreparedEvent>) -> Vec<SinkResult> {
        unreachable!("v0 endpoints publish events")
    }
}
