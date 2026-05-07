use async_trait::async_trait;

use crate::v1::context::Context;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::types::SinkResult;
use crate::v1::sinks::SinkName;

/// Backend-agnostic publishing interface for a single sink target.
#[async_trait]
pub trait Sink: Send + Sync {
    /// Identity of this sink (used for metrics and logging).
    fn name(&self) -> SinkName;

    /// Publish a batch of events. Returns one result per published event --
    /// skipped events (should_publish false / Destination::Drop) produce no result.
    async fn publish_batch(
        &self,
        ctx: &Context,
        events: &[&(dyn Event + Send + Sync)],
    ) -> Vec<Box<dyn SinkResult>>;

    /// Flush the underlying producer for graceful shutdown.
    async fn flush(&self) -> anyhow::Result<()>;
}
