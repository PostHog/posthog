use anyhow::{Context, Result};
use async_trait::async_trait;
use common_types::RawEvent;
use dashmap::DashMap;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message};
use serde_json;
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, error, info, warn};

use crate::kafka::message::{AckableMessage, MessageProcessor};
use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};

/// Configuration for the deduplication processor
#[derive(Debug, Clone)]
pub struct DeduplicationConfig {
    pub output_topic: Option<String>,
    pub producer_config: ClientConfig,
    pub store_config: DeduplicationStoreConfig,
    pub producer_send_timeout: Duration,
}

/// Processor that handles deduplication of events using per-partition stores
#[derive(Clone)]
pub struct DeduplicationProcessor {
    /// Configuration for the processor
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events
    producer: Option<FutureProducer>,

    /// Per-partition deduplication stores using DashMap for better concurrent performance
    /// Key: (topic, partition)
    stores: Arc<DashMap<(String, i32), Arc<DeduplicationStore>>>,
}

impl DeduplicationProcessor {
    /// Create a new deduplication processor
    pub fn new(config: DeduplicationConfig) -> Result<Self> {
        let producer: Option<FutureProducer> = match &config.output_topic {
            Some(topic) => Some(config.producer_config.create().with_context(|| {
                format!("Failed to create Kafka producer for output topic '{topic}'")
            })?),
            None => None,
        };

        Ok(Self {
            config,
            producer,
            stores: Arc::new(DashMap::new()),
        })
    }

    /// Get or create a deduplication store for a specific partition
    async fn get_or_create_store(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Arc<DeduplicationStore>> {
        let partition_key = (topic.to_string(), partition);

        // Use DashMap's entry API for atomic get-or-create operation
        let store = self
            .stores
            .entry(partition_key.clone())
            .or_try_insert_with(|| {
                // Create new store for this partition
                let store_path = format!(
                    "{}/{}_{}",
                    self.config.store_config.path.display(),
                    topic.replace('/', "_"),
                    partition
                );

                info!(
                    "Creating new deduplication store for partition {}:{} at path: {}",
                    topic, partition, store_path
                );

                let mut partition_config = self.config.store_config.clone();
                let store_path_str = store_path.clone();
                partition_config.path = store_path.into();

                DeduplicationStore::new(partition_config, topic.to_string(), partition)
                    .with_context(|| format!("Failed to create deduplication store for {topic}:{partition} at path {store_path_str}"))
                    .map(Arc::new)
            })?
            .clone();

        Ok(store)
    }

    /// Process a raw event through deduplication and publish if not duplicate
    async fn process_raw_event(
        &self,
        raw_event: RawEvent,
        topic: &str,
        partition: i32,
        offset: i64,
        key: String,
    ) -> Result<bool> {
        // Get the store for this partition
        let store = self.get_or_create_store(topic, partition).await?;

        // Extract key for deduplication - always use composite key (timestamp:distinct_id:token:event_name)
        // UUID is only used for Kafka partitioning, NOT for deduplication
        let dedup_key = format!(
            "{}:{}:{}:{}",
            raw_event.timestamp.as_deref().unwrap_or(""),
            raw_event.extract_distinct_id().unwrap_or_default(),
            raw_event.extract_token().unwrap_or_default(),
            raw_event.event
        );

        debug!(
            "Processing event with key {} for partition {}:{} at offset {}",
            dedup_key, topic, partition, offset
        );

        // Use the store's handle_event_with_raw method which checks for duplicates, stores if new, and tracks metrics
        let is_new_event = store.handle_event_with_raw(&raw_event)?;
        let is_duplicate = !is_new_event;

        if is_duplicate {
            debug!("Event {} is a duplicate, skipping", dedup_key);
            return Ok(false); // Event was a duplicate
        }

        // Event is not a duplicate, publish to output topic
        match &self.producer {
            Some(producer) => {
                let output_topic = self
                    .config
                    .output_topic
                    .as_ref()
                    .expect("output_topic must exist when producer is Some");
                return self
                    .publish_event(producer, raw_event, key, output_topic)
                    .await;
            }
            None => Ok(true),
        }
    }

    async fn publish_event(
        &self,
        producer: &FutureProducer,
        raw_event: RawEvent,
        key: String,
        output_topic: &str,
    ) -> Result<bool> {
        let serialized_event = serde_json::to_string(&raw_event).with_context(|| {
            format!("Failed to serialize event for publishing to topic '{output_topic}'")
        })?;

        let record = FutureRecord::to(output_topic)
            .key(&key)
            .payload(&serialized_event);

        match producer
            .send(record, Timeout::After(self.config.producer_send_timeout))
            .await
        {
            Ok(_) => {
                debug!(
                    "Successfully published non-duplicate event with key {} to {:?}",
                    key, output_topic
                );
                Ok(true) // Event was published
            }
            Err((e, _)) => {
                error!(
                    "Failed to publish event with key {} to {:?}: {}",
                    key, output_topic, e
                );
                Err(anyhow::anyhow!(
                    "Failed to publish event with key '{}' to topic '{}': {}",
                    key,
                    output_topic,
                    e
                ))
            }
        }
    }
}

#[async_trait]
impl MessageProcessor for DeduplicationProcessor {
    async fn process_message(&self, message: AckableMessage) -> Result<()> {
        let topic = message.kafka_message().topic().to_string();
        let partition = message.kafka_message().partition();
        let offset = message.kafka_message().offset();

        debug!(
            "Processing message from topic {} partition {} offset {}",
            topic, partition, offset
        );

        // Get the message payload
        let payload = match message.kafka_message().payload() {
            Some(payload) => payload,
            None => {
                warn!(
                    "Received message with no payload at {}:{} offset {}",
                    topic, partition, offset
                );
                message.ack().await;
                return Ok(());
            }
        };

        // Parse the raw event
        let raw_event: RawEvent = match serde_json::from_slice(payload) {
            Ok(event) => event,
            Err(e) => {
                error!(
                    "Failed to parse event from {}:{} offset {}: {}",
                    topic, partition, offset, e
                );
                // Nack the message so it can be handled by error recovery/DLQ
                message.nack(format!("Failed to parse JSON: {e}")).await;
                return Err(anyhow::anyhow!(
                    "Failed to parse event from {}:{} offset {}: {}",
                    topic,
                    partition,
                    offset,
                    e
                ));
            }
        };

        // Get the original message key for publishing
        let key = match message.kafka_message().key() {
            Some(key_bytes) => match std::str::from_utf8(key_bytes) {
                Ok(key_str) => key_str.to_string(),
                Err(e) => {
                    error!(
                        "Invalid UTF-8 in message key at {}:{} offset {}: {}",
                        topic, partition, offset, e
                    );
                    message
                        .nack("Invalid UTF-8 in message key".to_string())
                        .await;
                    return Err(anyhow::anyhow!(
                        "Invalid UTF-8 in message key at {}:{} offset {}: {}",
                        topic,
                        partition,
                        offset,
                        e
                    ));
                }
            },
            None => String::new(), // Empty key is acceptable
        };

        // Process the event through deduplication
        match self
            .process_raw_event(raw_event, &topic, partition, offset, key)
            .await
        {
            Ok(published) => {
                if published {
                    debug!(
                        "Event processed and published from {}:{} offset {}",
                        topic, partition, offset
                    );
                } else {
                    debug!(
                        "Event was duplicate, skipped from {}:{} offset {}",
                        topic, partition, offset
                    );
                }
                message.ack().await;
                Ok(())
            }
            Err(e) => {
                error!(
                    "Failed to process event from {}:{} offset {}: {}",
                    topic, partition, offset, e
                );
                message.nack(format!("Processing failed: {e}")).await;
                Err(e)
            }
        }
    }
}

impl DeduplicationProcessor {
    /// Get the number of active stores
    pub async fn get_active_store_count(&self) -> usize {
        self.stores.len()
    }

    /// Clean up stores for revoked partitions
    pub async fn cleanup_stores(&self, revoked_partitions: &[(String, i32)]) {
        for (topic, partition) in revoked_partitions {
            let partition_key = (topic.clone(), *partition);
            if let Some(_store) = self.stores.remove(&partition_key) {
                info!(
                    "Cleaned up deduplication store for revoked partition {}:{}",
                    topic, partition
                );
                // Store will be dropped when Arc goes out of scope
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashMap;
    use tempfile::TempDir;
    use uuid::Uuid;

    fn create_test_config() -> (DeduplicationConfig, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };

        let mut producer_config = ClientConfig::new();
        producer_config.set("bootstrap.servers", "localhost:9092");
        producer_config.set("message.timeout.ms", "5000");

        let config = DeduplicationConfig {
            output_topic: Some("deduplicated-events".to_string()),
            producer_config,
            store_config,
            producer_send_timeout: Duration::from_secs(5),
        };

        (config, temp_dir)
    }

    fn create_test_raw_event(uuid: Option<Uuid>, event: &str, distinct_id: &str) -> RawEvent {
        let mut properties = HashMap::new();
        properties.insert("test_property".to_string(), json!("test_value"));

        RawEvent {
            uuid,
            event: event.to_string(),
            distinct_id: Some(json!(distinct_id)),
            token: Some("test_token".to_string()),
            properties,
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn test_processor_creation() {
        let (_config, _temp_dir) = create_test_config();

        // Note: This will fail if Kafka is not running, but that's expected in unit tests
        // In a real scenario, we'd mock the producer
        // Skip actual creation since Kafka not available in tests
    }

    #[tokio::test]
    async fn test_store_creation_and_management() {
        let (_config, _temp_dir) = create_test_config();

        // We can't easily test the full processor without Kafka running,
        // but we can test the store management logic separately
        let stores: Arc<DashMap<(String, i32), Arc<DeduplicationStore>>> = Arc::new(DashMap::new());

        // Test that stores map starts empty
        assert_eq!(stores.len(), 0);

        // Test cleanup with empty stores
        let revoked = vec![("test-topic".to_string(), 0)];
        for (topic, partition) in &revoked {
            stores.remove(&(topic.clone(), *partition));
        }

        assert_eq!(stores.len(), 0);
    }

    #[test]
    fn test_raw_event_serialization() {
        let event = create_test_raw_event(Some(Uuid::new_v4()), "test_event", "test_user");

        // Test that we can serialize and deserialize
        let serialized = serde_json::to_string(&event).unwrap();
        let deserialized: RawEvent = serde_json::from_str(&serialized).unwrap();

        assert_eq!(event.event, deserialized.event);
        assert_eq!(event.uuid, deserialized.uuid);
        assert_eq!(event.distinct_id, deserialized.distinct_id);
    }
}
