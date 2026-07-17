use async_trait::async_trait;

use crate::v1::context::RequestContext;
use crate::v1::sinks::types::{PreparedEvent, SinkResult};
use crate::v1::sinks::SinkName;

/// Backend-agnostic publishing interface for a single sink target.
#[async_trait]
pub trait Sink: Send + Sync {
    /// Identity of this sink (used for metrics and logging).
    fn name(&self) -> SinkName;

    /// Publish a batch of already-serialized events. Returns one result per
    /// event the sink attempted; events the sink itself drops (e.g. a
    /// destination with no configured topic) produce no result.
    async fn publish_batch(
        &self,
        ctx: &RequestContext,
        events: &[PreparedEvent],
    ) -> Vec<Box<dyn SinkResult>>;

    /// Flush the underlying producer for graceful shutdown.
    async fn flush(&self) -> anyhow::Result<()>;
}
