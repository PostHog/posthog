//! Shared `MockSink` test helper for pipeline-level tests across the capture
//! crate. Captures every `ProcessedEvent` sent through `send` / `send_batch`
//! in an `Arc<Mutex<Vec<_>>>` so tests can assert on the exact stamped
//! metadata the pipeline produced.
//!
//! Supports both construction patterns used across existing tests:
//! - `Arc::new(MockSink::new())` + `sink.get_events()` (analytics tests)
//! - `Arc::new(MockSink { events: events_captured.clone() })` + manual
//!   `events_captured.lock()` (recordings tests that share the handle with
//!   the sink before wrapping in `Arc<dyn Event>`)

use crate::api::CaptureError;
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
