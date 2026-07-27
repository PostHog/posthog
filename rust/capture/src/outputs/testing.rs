//! Test support for the outputs layer — public so integration tests build
//! capturing produce surfaces against the crate's real prep path. Not part
//! of the production surface.
//!
//! [`MockOutputs`] runs the real prep path (lane resolution, serialization,
//! headers) and captures the resulting [`AddressedPayload`]s, so tests
//! assert on the wire outcome the pipeline produced — address, partition
//! key, headers, payload bytes — through the public publish surface.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use common_types::CapturedEvent;

use crate::api::CaptureError;
use crate::config::EnvelopeCompression;
use crate::outputs::{prepare_batch, AddressedPayload, Outputs, PrepSpec};
use crate::sinks::SinkResult;
use crate::v0_request::ProcessedEvent;

#[derive(Clone)]
pub struct MockOutputs {
    prep: PrepSpec,
    pub payloads: Arc<Mutex<Vec<AddressedPayload>>>,
}

impl Default for MockOutputs {
    fn default() -> Self {
        Self {
            prep: PrepSpec::new(EnvelopeCompression::None),
            payloads: Arc::default(),
        }
    }
}

impl MockOutputs {
    pub fn new() -> Self {
        Self::default()
    }

    /// A capturing surface with a specific prep spec (e.g. an lz4 replay
    /// envelope) when the default json/no-envelope spec isn't the contract
    /// under test.
    pub fn with_prep(prep: PrepSpec) -> Self {
        Self {
            prep,
            payloads: Arc::default(),
        }
    }

    pub fn get_payloads(&self) -> Vec<AddressedPayload> {
        self.payloads.lock().unwrap().clone()
    }

    /// The captured payloads deserialized back into events, for content
    /// assertions. Assumes uncompressed json payloads (no lz4 envelope) —
    /// which is what the default prep spec produces.
    pub fn captured_events(&self) -> Vec<CapturedEvent> {
        self.get_payloads()
            .iter()
            .map(|p| {
                serde_json::from_slice(&p.payload)
                    .expect("captured payload must be json-deserializable")
            })
            .collect()
    }
}

#[async_trait]
impl Outputs for MockOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Vec<SinkResult> {
        let uuids: Vec<uuid::Uuid> = events.iter().map(|e| e.event.uuid).collect();
        let prepared = match prepare_batch(&self.prep, events).await {
            Ok(prepared) => prepared,
            Err(err) => {
                return uuids
                    .into_iter()
                    .map(|uuid| SinkResult::err(uuid, err.clone()))
                    .collect()
            }
        };
        self.payloads.lock().unwrap().extend(prepared);
        uuids.into_iter().map(SinkResult::ok).collect()
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

/// An outputs surface whose publish always fails with the configured error.
#[derive(Clone)]
pub struct FailOutputs(pub CaptureError);

#[async_trait]
impl Outputs for FailOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Vec<SinkResult> {
        crate::outputs::batch_error(&events, self.0.clone())
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}
