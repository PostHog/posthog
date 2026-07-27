//! Shared `MockSink` test helper for pipeline-level tests across the capture
//! crate. Captures every [`PreparedPayload`] published through it in an
//! `Arc<Mutex<Vec<_>>>` so tests can assert on the wire outcome the pipeline
//! produced: topic, partition key, headers, and the payload bytes
//! (deserializable back to the [`CapturedEvent`] via [`MockSink::captured_events`]).
//! Wrap it in an output for pipeline-level tests:
//! `OutputTable::new(Output::single(Arc::new(mock), spec))`.

use crate::api::CaptureError;
use crate::sinks::sink::{PreparedPayload, Sink, SinkResult};
use async_trait::async_trait;
use common_types::CapturedEvent;
use std::sync::{Arc, Mutex};

#[derive(Clone, Default)]
pub(crate) struct MockSink {
    pub payloads: Arc<Mutex<Vec<PreparedPayload>>>,
}

impl MockSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get_payloads(&self) -> Vec<PreparedPayload> {
        self.payloads.lock().unwrap().clone()
    }

    /// The captured payloads deserialized back into events, for content
    /// assertions. Assumes uncompressed json payloads (no lz4 envelope) —
    /// which is what the shared test prep specs produce.
    pub fn captured_events(&self) -> Vec<CapturedEvent> {
        self.get_payloads()
            .iter()
            .map(|p| {
                serde_json::from_slice(&p.record.payload)
                    .expect("captured payload must be json-deserializable")
            })
            .collect()
    }
}

#[async_trait]
impl Sink for MockSink {
    async fn publish(&self, prepared: Vec<PreparedPayload>) -> Vec<SinkResult> {
        let results = prepared.iter().map(|p| SinkResult::ok(p.uuid)).collect();
        self.payloads.lock().unwrap().extend(prepared);
        results
    }
}

/// A sink whose publish always fails with the configured error.
#[derive(Clone)]
pub(crate) struct FailSink(pub CaptureError);

#[async_trait]
impl Sink for FailSink {
    async fn publish(&self, prepared: Vec<PreparedPayload>) -> Vec<SinkResult> {
        prepared
            .into_iter()
            .map(|p| SinkResult::err(p.uuid, self.0.clone()))
            .collect()
    }
}
