use async_trait::async_trait;

use crate::api::{CaptureError, ProcessedEvent};

pub mod kafka;
pub mod print;

#[async_trait]
pub trait Event {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

pub struct SleepSink;

#[async_trait]
impl Event for SleepSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        drop(event);
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        drop(events);
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        Ok(())
    }
}
