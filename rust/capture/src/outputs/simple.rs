//! Trivial outputs: print (local development) and noop (load testing).
//!
//! Both run the full prep dance — lane resolution, serialization, headers —
//! so a malformed event fails exactly as it would on a producing deployment;
//! only the transport is absent.

use async_trait::async_trait;
use metrics::counter;
use tracing::log::info;

use crate::outputs::{prepare_batch, Outputs, PrepSpec};
use crate::sinks::SinkResult;
use crate::v0_request::ProcessedEvent;

/// Prints each prepared payload; local development only.
pub struct PrintOutputs {
    prep: PrepSpec,
}

impl PrintOutputs {
    pub fn new(prep: PrepSpec) -> Self {
        Self { prep }
    }
}

#[async_trait]
impl Outputs for PrintOutputs {
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
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        for payload in prepared {
            info!(
                "event payload: {}",
                String::from_utf8_lossy(&payload.payload)
            );
        }
        uuids.into_iter().map(SinkResult::ok).collect()
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

/// Silently drops every event after prep; load testing only.
pub struct NoopOutputs {
    prep: PrepSpec,
}

impl NoopOutputs {
    pub fn new(prep: PrepSpec) -> Self {
        Self { prep }
    }
}

#[async_trait]
impl Outputs for NoopOutputs {
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
        counter!("capture_events_ingested_total").increment(prepared.len() as u64);
        uuids.into_iter().map(SinkResult::ok).collect()
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}
