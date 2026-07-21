use async_trait::async_trait;

use crate::{api::CaptureError, v0_request::ProcessedEvent};

pub mod fallback;
pub mod kafka;
pub mod noop;
pub mod print;
pub mod producer;
pub mod registry;
pub mod s3;
pub mod sink;
pub mod split;
#[cfg(test)]
pub(crate) mod test_sink;

pub use sink::{fold_results, Outcome, PreparedRecord, Sink, SinkResult};

/// Legacy per-request sink trait. Now a thin shim over its [`Sink`] supertrait:
/// production impls serialize into a prepared batch, call
/// [`Sink::publish_batch`], and fold the per-event results back into one
/// [`CaptureError`]. Retained so the not-yet-migrated call sites (ai, otel,
/// recordings) stay frozen while the migration is in flight; removed in Step 9
/// once every call site is on [`Sink`] directly.
///
/// The `Sink` supertrait bound is what lets a call site holding an
/// `Arc<dyn Event>` (e.g. `State::sink`) reach the unified `prepare` /
/// `publish_batch` mechanism directly — the analytics path does exactly this —
/// while the same object still serves the legacy `send` / `send_batch` callers.
#[async_trait]
pub trait Event: Sink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;

    /// Flush any buffered/pending data before shutdown. Default is no-op.
    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

pub use fallback::FallbackSink;
