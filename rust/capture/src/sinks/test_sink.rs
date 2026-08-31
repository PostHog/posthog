//! Shared `MockSink` test helper for pipeline-level tests across the capture
//! crate.

use crate::api::CaptureError;
use crate::outputs::{OutputRegistry, PublishEvents};
use crate::v0_request::ProcessedEvent;
use async_trait::async_trait;
use std::sync::{Arc, Mutex};

#[derive(Clone, Default)]
pub(crate) struct MockSink {
    pub events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

impl MockSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get_events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().unwrap().clone()
    }

    /// The degenerate output table over this mock. The clone shares the
    /// capture buffer, so the caller keeps reading events back off the
    /// handle it already holds.
    pub fn table(&self) -> Arc<OutputRegistry> {
        Arc::new(OutputRegistry::single(self.clone()))
    }
}

#[async_trait]
impl PublishEvents for MockSink {
    async fn publish_events(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend(events);
        Ok(())
    }
}
