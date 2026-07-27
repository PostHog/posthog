//! S3 outputs: the fallback buffer as a produce surface.
//!
//! Preps events with its own spec and hands serialized payload bytes to the
//! S3 buffer sink. Address realization is trivial: every address lands in
//! the buffer, whose S3 path is buffer configuration (bucket/prefix wired at
//! boot) — recovery replays the buffered payloads into their real
//! destinations, which is why the payload bytes are target-agnostic.

use async_trait::async_trait;

use crate::api::CaptureError;
use crate::outputs::{prepare_batch, Outputs, PrepSpec};
use crate::sinks::fold_results;
use crate::sinks::s3::S3Sink;
use crate::v0_request::ProcessedEvent;

pub struct S3Outputs {
    prep: PrepSpec,
    sink: S3Sink,
}

impl S3Outputs {
    pub fn new(prep: PrepSpec, sink: S3Sink) -> Self {
        Self { prep, sink }
    }
}

#[async_trait]
impl Outputs for S3Outputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let prepared = prepare_batch(&self.prep, events).await?;
        let payloads = prepared.into_iter().map(|p| (p.uuid, p.payload)).collect();
        fold_results(self.sink.publish(payloads).await)
    }

    /// The buffer flushes on its own timer/size loop (and the failover
    /// policy flushes its primary); nothing to force here — matching the old
    /// S3 sink's no-op trait flush.
    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}
