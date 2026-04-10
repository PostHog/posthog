use async_trait::async_trait;

use crate::{api::CaptureError, v0_request::ProcessedEvent};

pub mod fallback;
pub mod kafka;
pub mod noop;
pub mod print;
pub mod producer;
pub mod s3;
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
