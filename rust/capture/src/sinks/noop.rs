use std::sync::atomic::{AtomicU64, Ordering};

use async_trait::async_trait;
use health::HealthHandle;
use metrics::{counter, histogram};

use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::ProcessedEvent;

const HEALTH_REPORT_INTERVAL: u64 = 100_000;

pub struct NoOpSink {
    health: HealthHandle,
    counter: AtomicU64,
}

impl NoOpSink {
    pub async fn new(health: HealthHandle) -> Self {
        health.report_healthy().await;
        Self {
            health,
            counter: AtomicU64::new(0),
        }
    }
}

#[async_trait]
impl Event for NoOpSink {
    async fn send(&self, _event: ProcessedEvent) -> Result<(), CaptureError> {
        let count = self.counter.fetch_add(1, Ordering::Relaxed);
        if count.is_multiple_of(HEALTH_REPORT_INTERVAL) {
            self.health.report_healthy().await;
        }
        counter!("capture_events_ingested_total").increment(1);
        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let count = self.counter.fetch_add(1, Ordering::Relaxed);
        if count.is_multiple_of(HEALTH_REPORT_INTERVAL) {
            self.health.report_healthy().await;
        }
        histogram!("capture_event_batch_size").record(events.len() as f64);
        counter!("capture_events_ingested_total").increment(events.len() as u64);
        Ok(())
    }
}
