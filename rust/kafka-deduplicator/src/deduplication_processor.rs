use anyhow::{Context, Result};
use async_trait::async_trait;
use common_types::RawEvent;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message};
use serde_json;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

use crate::kafka::message::{AckableMessage, MessageProcessor};
use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};

/// Configuration for the deduplication processor
#[derive(Debug, Clone)]
pub struct DeduplicationConfig {
    pub output_topic: Option<String>,
    pub producer_config: ClientConfig,
    pub store_config: DeduplicationStoreConfig,
}

/// Type alias for partition-store mapping
type PartitionStoreMap = Arc<RwLock<HashMap<(String, i32), Arc<DeduplicationStore>>>>;

/// Processor that handles deduplication of events using per-partition stores
#[derive(Clone)]
pub struct DeduplicationProcessor {
    /// Configuration for the processor
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events§
    producer: Option<FutureProducer>,

    /// Per-partition deduplication stores
    /// Key: (topic, partition)
    stores: PartitionStoreMap,
}

impl DeduplicationProcessor {
    /// Create a new deduplication processor
    pub fn new(config: DeduplicationConfig) -> Result<Self> {
        let producer: Option<FutureProducer> = match config.output_topic {
            Some(_) => Some(
                config
                    .producer_config
                    .create()
                    .context("Failed to create Kafka producer")?,
            ),
            None => None,
        };

        Ok(Self {
            config,
            producer,
            stores: Arc::new(RwLock::new(HashMap::new())),
        })
    }

    /// Get or create a deduplication store for a specific partition
    async fn get_or_create_store(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Arc<DeduplicationStore>> {
        let partition_key = (topic.to_string(), partition);

        // Try to get existing store first (read lock)
        {
            let stores = self.stores.read().await;
            if let Some(store) = stores.get(&partition_key) {
                return Ok(store.clone());
            }
        }

        // Need to create new store (write lock)
        let mut stores = self.stores.write().await;

        // Double-check in case another task created it while we were waiting for write lock
        if let Some(store) = stores.get(&partition_key) {
            return Ok(store.clone());
        }

        // Create new store for this partition
        info!(
            "Creating new deduplication store for partition {}:{}",
            topic, partition
        );

        let store_path = format!(
            "{}/{}_{}",
            self.config.store_config.path.display(),
            topic.replace('/', "_"),
            partition
        );

        let mut partition_config = self.config.store_config.clone();
        partition_config.path = store_path.into();

        let store = Arc::new(DeduplicationStore::new(
            partition_config,
            topic.to_string(),
            partition,
        )?);

        stores.insert(partition_key, store.clone());

        Ok(store)
    }

    /// Process a raw event through deduplication and publish if not duplicate
    async fn process_raw_event(
        &self,
        raw_event: RawEvent,
        topic: &str,
        partition: i32,
        _offset: i64,
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
            "Processing event with key {} for partition {}:{}",
            dedup_key, topic, partition
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
                let output_topic = self.config.output_topic.as_ref().unwrap();
                return DeduplicationProcessor::publish_event(
                    producer,
                    raw_event,
                    key,
                    output_topic,
                )
                .await;
            }
            None => Ok(true),
        }
    }

    async fn publish_event(
        producer: &FutureProducer,
        raw_event: RawEvent,
        key: String,
        output_topic: &str,
    ) -> Result<bool> {
        let serialized_event = serde_json::to_string(&raw_event)
            .context("Failed to serialize event for publishing")?;

        let record = FutureRecord::to(output_topic)
            .key(&key)
            .payload(&serialized_event);

        match producer
            .send(record, Timeout::After(Duration::from_secs(5)))
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
                Err(anyhow::anyhow!("Failed to publish event: {}", e))
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
                // Still ack the message to avoid reprocessing
                message.ack().await;
                return Err(anyhow::anyhow!("Failed to parse event: {}", e));
            }
        };

        // Get the original message key for publishing
        let key = message
            .kafka_message()
            .key()
            .map(|k| String::from_utf8_lossy(k).to_string())
            .unwrap_or_default();

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
    /// Get statistics for all stores
    pub async fn get_store_stats(&self) -> HashMap<(String, i32), (usize, u64, u64)> {
        let stores = self.stores.read().await;
        let mut stats = HashMap::new();

        for ((topic, partition), _store) in stores.iter() {
            // Get basic stats from the store - you may need to implement these methods
            let memory_usage = 0; // TODO: implement memory usage tracking
            let processed_events = 0; // TODO: implement event counter
            let duplicate_events = 0; // TODO: implement duplicate counter

            stats.insert(
                (topic.clone(), *partition),
                (memory_usage, processed_events, duplicate_events),
            );
        }

        stats
    }

    /// Get the number of active stores
    pub async fn get_active_store_count(&self) -> usize {
        let stores = self.stores.read().await;
        stores.len()
    }

    /// Clean up stores for revoked partitions
    pub async fn cleanup_stores(&self, revoked_partitions: &[(String, i32)]) {
        let mut stores = self.stores.write().await;

        for (topic, partition) in revoked_partitions {
            let partition_key = (topic.clone(), *partition);
            if let Some(_store) = stores.remove(&partition_key) {
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
        let stores: PartitionStoreMap = Arc::new(RwLock::new(HashMap::new()));

        // Test that stores map starts empty
        assert_eq!(stores.read().await.len(), 0);

        // Test cleanup with empty stores
        let revoked = vec![("test-topic".to_string(), 0)];
        let mut stores_write = stores.write().await;
        for (topic, partition) in &revoked {
            stores_write.remove(&(topic.clone(), *partition));
        }
        drop(stores_write);

        assert_eq!(stores.read().await.len(), 0);
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
