use async_trait::async_trait;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::ClientConfig;
use std::sync::Arc;
use std::time::Duration;

use crate::error::{AppError, Result};
use crate::types::AgentEvent;

#[async_trait]
pub trait EventPublisher: Send + Sync {
    async fn publish(&self, event: &AgentEvent) -> Result<()>;
}

pub struct KafkaEventPublisher {
    producer: FutureProducer,
    topic: String,
}

impl KafkaEventPublisher {
    pub fn new(brokers: &str, topic: &str) -> Result<Arc<Self>> {
        let producer: FutureProducer = ClientConfig::new()
            .set("bootstrap.servers", brokers)
            .set("message.timeout.ms", "5000")
            .set("compression.type", "snappy")
            .create()
            .map_err(|e| AppError::Kafka(e.to_string()))?;

        Ok(Arc::new(Self {
            producer,
            topic: topic.to_string(),
        }))
    }

    fn make_key(event: &AgentEvent) -> String {
        format!("{}:{}", event.task_id, event.run_id)
    }
}

#[async_trait]
impl EventPublisher for KafkaEventPublisher {
    async fn publish(&self, event: &AgentEvent) -> Result<()> {
        let key = Self::make_key(event);
        let payload = serde_json::to_string(event)?;

        let record = FutureRecord::to(&self.topic)
            .key(&key)
            .payload(&payload);

        self.producer
            .send(record, Duration::from_secs(5))
            .await
            .map_err(|(e, _)| AppError::Kafka(e.to_string()))?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use uuid::Uuid;

    #[test]
    fn test_make_key() {
        let event = AgentEvent {
            team_id: 1,
            task_id: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            run_id: Uuid::parse_str("6ba7b810-9dad-11d1-80b4-00c04fd430c8").unwrap(),
            sequence: 1,
            timestamp: Utc::now(),
            entry_type: "test".to_string(),
            entry: serde_json::json!({}),
        };

        let key = KafkaEventPublisher::make_key(&event);
        assert_eq!(
            key,
            "550e8400-e29b-41d4-a716-446655440000:6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        );
    }
}
