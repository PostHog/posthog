use async_trait::async_trait;

use crate::{api::CaptureError, v0_request::ProcessedEvent};

pub mod fallback;
pub mod kafka;
pub mod print;
pub mod s3;
#[async_trait]
pub trait Event {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

#[async_trait]
impl<T: Event + ?Sized + Send + Sync> Event for Box<T> {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        (**self).send(event).await
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        (**self).send_batch(events).await
    }
}

pub use fallback::FallbackSink;
