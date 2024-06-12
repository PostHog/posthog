use async_trait::async_trait;

use crate::api::{CaptureError, ProcessedEvent};

pub mod kafka;
pub mod print;

#[async_trait]
pub trait Event {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}
