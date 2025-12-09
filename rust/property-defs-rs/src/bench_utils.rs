use async_trait::async_trait;
use common_kafka::kafka_consumer::RecvErr;
use serde_json::json;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use crate::service::{OffsetHandle, PropDefsKafkaConsumer};
use crate::types::Event;

/// Mock consumer for benchmarking that generates synthetic events
pub struct MockConsumer {
    events_generated: Arc<AtomicUsize>,
    team_count: i32,
    event_names: Vec<String>,
    properties_per_event: usize,
    max_events: Option<usize>,
}

impl MockConsumer {
    pub fn new(
        team_count: i32,
        event_names: Vec<String>,
        properties_per_event: usize,
        max_events: Option<usize>,
    ) -> Self {
        Self {
            events_generated: Arc::new(AtomicUsize::new(0)),
            team_count,
            event_names,
            properties_per_event,
            max_events,
        }
    }

    pub fn events_generated(&self) -> usize {
        self.events_generated.load(Ordering::Relaxed)
    }

    fn generate_properties(&self) -> String {
        let mut props = serde_json::Map::new();
        for i in 0..self.properties_per_event {
            props.insert(
                format!("prop_{}", i),
                json!(format!("value_{}", i)),
            );
        }
        serde_json::to_string(&props).unwrap()
    }
}

#[async_trait]
impl PropDefsKafkaConsumer for MockConsumer {
    async fn json_recv(&mut self) -> Result<(Event, OffsetHandle), RecvErr> {
        let count = self.events_generated.fetch_add(1, Ordering::Relaxed);

        // Check if we've reached the max events limit
        if let Some(max) = self.max_events {
            if count >= max {
                // Simulate end of stream
                tokio::time::sleep(tokio::time::Duration::from_secs(3600)).await;
                return Err(RecvErr::Empty);
            }
        }

        // Generate a synthetic event
        let team_id = (count as i32) % self.team_count;
        let event_name = &self.event_names[count % self.event_names.len()];
        let properties = if self.properties_per_event > 0 {
            Some(self.generate_properties())
        } else {
            None
        };

        let event = Event {
            team_id,
            project_id: team_id as i64,
            event: event_name.clone(),
            properties,
        };

        // Small delay to simulate network latency (optional, can be removed for max throughput)
        // tokio::time::sleep(tokio::time::Duration::from_micros(10)).await;

        Ok((event, OffsetHandle::noop()))
    }
}

/// High-throughput mock consumer that generates events as fast as possible
pub struct BurstMockConsumer {
    events_per_burst: usize,
    burst_delay_ms: u64,
    current_burst: usize,
    current_event_in_burst: usize,
    team_count: i32,
    total_events: Arc<AtomicUsize>,
}

impl BurstMockConsumer {
    pub fn new(events_per_burst: usize, burst_delay_ms: u64, team_count: i32) -> Self {
        Self {
            events_per_burst,
            burst_delay_ms,
            current_burst: 0,
            current_event_in_burst: 0,
            team_count,
            total_events: Arc::new(AtomicUsize::new(0)),
        }
    }

    pub fn total_events(&self) -> usize {
        self.total_events.load(Ordering::Relaxed)
    }
}

#[async_trait]
impl PropDefsKafkaConsumer for BurstMockConsumer {
    async fn json_recv(&mut self) -> Result<(Event, OffsetHandle), RecvErr> {
        // If we've finished the current burst, wait before starting the next one
        if self.current_event_in_burst >= self.events_per_burst {
            tokio::time::sleep(tokio::time::Duration::from_millis(self.burst_delay_ms)).await;
            self.current_burst += 1;
            self.current_event_in_burst = 0;
        }

        let event_num = self.total_events.fetch_add(1, Ordering::Relaxed);
        self.current_event_in_burst += 1;

        let team_id = (event_num as i32) % self.team_count;
        let event = Event {
            team_id,
            project_id: team_id as i64,
            event: format!("event_{}", event_num % 10),
            properties: Some(json!({
                "burst": self.current_burst,
                "event_in_burst": self.current_event_in_burst,
                "timestamp": chrono::Utc::now().to_rfc3339(),
            }).to_string()),
        };

        Ok((event, OffsetHandle::noop()))
    }
}