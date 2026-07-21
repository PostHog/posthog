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

/// Legacy per-request sink trait. Now a thin shim over [`Sink`]: production
/// impls serialize into a prepared batch, call [`Sink::publish_batch`], and
/// fold the per-event results back into one [`CaptureError`]. Retained so the
/// four call sites stay frozen while the migration is in flight; removed in
/// Step 9 once every call site is on [`Sink`] directly.
#[async_trait]
pub trait Event {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;

    /// Flush any buffered/pending data before shutdown. Default is no-op.
    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

#[async_trait]
impl<T: Event + ?Sized + Send + Sync> Event for Box<T> {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        (**self).send(event).await
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        (**self).send_batch(events).await
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        (**self).flush()
    }
}

pub use fallback::FallbackSink;
