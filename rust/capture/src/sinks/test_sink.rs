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

/// Build an inert prepared payload for a mock: real uuid + headers, empty
/// routing. Lets test sinks ride the prep → publish path without a broker.
pub(crate) fn passthrough_payload(event: &ProcessedEvent) -> crate::sinks::sink::PreparedPayload {
    crate::sinks::sink::PreparedPayload {
        uuid: event.event.uuid,
        record: crate::sinks::producer::ProduceRecord {
            topic: String::new(),
            key: None,
            payload: Vec::new(),
            headers: event.event.to_headers(),
        },
    }
}

#[async_trait]
impl crate::sinks::sink::Prepare for MockSink {
    /// Captures at prep — the outputs layer preps through the target that will
    /// publish, so this observes exactly what that target was handed.
    async fn prepare_batch(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<crate::sinks::sink::PreparedPayload>, CaptureError> {
        let payloads = events.iter().map(passthrough_payload).collect();
        self.events.lock().unwrap().extend(events);
        Ok(payloads)
    }
}

#[async_trait]
impl crate::sinks::sink::Sink for MockSink {
    async fn publish(
        &self,
        prepared: Vec<crate::sinks::sink::PreparedPayload>,
    ) -> Vec<crate::sinks::sink::SinkResult> {
        prepared
            .into_iter()
            .map(|p| crate::sinks::sink::SinkResult::ok(p.uuid))
            .collect()
    }
}

/// A sink whose publish always fails with the configured error; prep succeeds.
#[derive(Clone)]
pub(crate) struct FailSink(pub CaptureError);

#[async_trait]
impl crate::sinks::sink::Prepare for FailSink {
    async fn prepare_batch(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<crate::sinks::sink::PreparedPayload>, CaptureError> {
        Ok(events.iter().map(passthrough_payload).collect())
    }
}

#[async_trait]
impl crate::sinks::sink::Sink for FailSink {
    async fn publish(
        &self,
        prepared: Vec<crate::sinks::sink::PreparedPayload>,
    ) -> Vec<crate::sinks::sink::SinkResult> {
        prepared
            .into_iter()
            .map(|p| crate::sinks::sink::SinkResult::err(p.uuid, self.0.clone()))
            .collect()
    }
}
