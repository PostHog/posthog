use anyhow::Result;
use async_trait::async_trait;

use crate::event::ProcessedEvent;

#[async_trait]
pub trait EventSink {
    async fn send(&self, event: ProcessedEvent) -> Result<()>;
    async fn send_batch(&self, events: &[ProcessedEvent]) -> Result<()>;
}

pub struct PrintSink {}

#[async_trait]
impl EventSink for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<()> {
        tracing::info!("single event: {:?}", event);

        Ok(())
    }
    async fn send_batch(&self, events: &[ProcessedEvent]) -> Result<()> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        for event in events {
            tracing::info!("event: {:?}", event);
        }

        Ok(())
    }
}
