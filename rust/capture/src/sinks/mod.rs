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

pub use fallback::FallbackSink;
