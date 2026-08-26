//! Shared `MockSink` test helper for pipeline-level tests across the capture
//! crate. Captures every `ProcessedEvent` sent through `send` / `send_batch`
//! in an `Arc<Mutex<Vec<_>>>` so tests can assert on the exact stamped
//! metadata the pipeline produced.
//!
//! Supports both construction patterns used across existing tests:
//! - `MockSink::new()` + `sink.table()` into the pipeline + `sink.get_events()`
//!   (analytics tests)
//! - `OutputRegistry::single(MockSink { events: events_captured.clone() })` +
//!   manual `events_captured.lock()` (recordings tests that keep the capture
//!   handle rather than the mock)

use crate::api::CaptureError;
use crate::outputs::{OutputRegistry, PublishEvents};
use crate::sinks::Event;
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
    /// handle it already holds after publishing through the table.
    pub fn table(&self) -> Arc<OutputRegistry> {
        Arc::new(OutputRegistry::single(self.clone()))
    }
}

#[async_trait]
impl Event for MockSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend(events);
        Ok(())
    }
}

#[async_trait]
impl PublishEvents for MockSink {
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend(events);
        Ok(())
    }
}
