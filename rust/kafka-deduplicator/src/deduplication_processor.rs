use anyhow::{Context, Result};
use async_trait::async_trait;
use common_types::{CapturedEvent, RawEvent};
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message};
use serde_json;
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, error, warn};

use crate::kafka::message::{AckableMessage, MessageProcessor};
use crate::store::{DeduplicationStore, DeduplicationStoreConfig};
use crate::store_manager::StoreManager;
use crate::utils::timestamp;

/// Context for a Kafka message being processed
struct MessageContext<'a> {
    topic: &'a str,
    partition: i32,
    offset: i64,
    key: String,
}

/// Configuration for the deduplication processor
#[derive(Debug, Clone)]
pub struct DeduplicationConfig {
    pub output_topic: Option<String>,
    pub producer_config: ClientConfig,
    pub store_config: DeduplicationStoreConfig,
    pub producer_send_timeout: Duration,
    pub flush_interval: Duration,
}

/// Processor that handles deduplication of events using per-partition stores
#[derive(Clone)]
pub struct DeduplicationProcessor {
    /// Configuration for the processor
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events
    producer: Option<Arc<FutureProducer>>,

    /// Store manager that handles concurrent store creation and access
    store_manager: Arc<StoreManager>,
}

impl DeduplicationProcessor {
    /// Create a new deduplication processor with a store manager
    pub fn new(config: DeduplicationConfig, store_manager: Arc<StoreManager>) -> Result<Self> {
        let producer: Option<Arc<FutureProducer>> = match &config.output_topic {
            Some(topic) => Some(Arc::new(config.producer_config.create().with_context(
                || format!("Failed to create Kafka producer for output topic '{topic}'"),
            )?)),
            None => None,
        };

        Ok(Self {
            config,
            producer,
            store_manager,
        })
    }

    /// Get or create a deduplication store for a specific partition
    async fn get_or_create_store(&self, topic: &str, partition: i32) -> Result<DeduplicationStore> {
        self.store_manager.get_or_create(topic, partition).await
    }

    /// Process a raw event through deduplication and publish if not duplicate
    async fn process_raw_event(
        &self,
        raw_event: RawEvent,
        original_payload: &[u8],
        original_headers: Option<&OwnedHeaders>,
        ctx: MessageContext<'_>,
    ) -> Result<bool> {
        // Get the store for this partition
        let store = self.get_or_create_store(ctx.topic, ctx.partition).await?;

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
            dedup_key, ctx.topic, ctx.partition, ctx.offset
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
                    .publish_event(
                        producer,
                        original_payload,
                        original_headers,
                        ctx.key,
                        output_topic,
                    )
                    .await;
            }
            None => Ok(true),
        }
    }

    async fn publish_event(
        &self,
        producer: &FutureProducer,
        original_payload: &[u8],
        original_headers: Option<&OwnedHeaders>,
        key: String,
        output_topic: &str,
    ) -> Result<bool> {
        // Create a new record with the original payload and key
        let mut record = FutureRecord::to(output_topic)
            .key(&key)
            .payload(original_payload);

        if let Some(headers) = original_headers {
            record = record.headers(headers.clone());
        }

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

        // Parse the captured event and extract the raw event from it
        let raw_event = match serde_json::from_slice::<CapturedEvent>(payload) {
            Ok(captured_event) => {
                // extract well-validated values from the CapturedEvent that
                // may or may not be present in the wrapped RawEvent
                let now = captured_event.now.clone();
                let extracted_distinct_id = captured_event.distinct_id.clone();
                let extracted_token = captured_event.token.clone();
                let extracted_uuid = captured_event.uuid;

                // The RawEvent is serialized in the data field
                match serde_json::from_str::<RawEvent>(&captured_event.data) {
                    Ok(mut raw_event) => {
                        // Validate timestamp: if it's None or unparseable, use CapturedEvent.now
                        // This ensures we always have a valid timestamp for deduplication
                        match raw_event.timestamp {
                            None => {
                                debug!("No timestamp in RawEvent, using CapturedEvent.now");
                                raw_event.timestamp = Some(now);
                            }
                            Some(ref ts) if !timestamp::is_valid_timestamp(ts) => {
                                // Don't log the invalid timestamp directly as it may contain
                                // non-ASCII characters that could cause issues with logging
                                debug!(
                                    "Invalid timestamp detected at {}:{} offset {}, replacing with CapturedEvent.now",
                                    topic, partition, offset
                                );
                                raw_event.timestamp = Some(now);
                            }
                            _ => {
                                // Timestamp exists and is valid, keep it
                            }
                        }

                        // if RawEvent is missing any of the core values
                        // extracted by capture into the CapturedEvent
                        // wrapper, use those values for downstream analysis
                        if raw_event.uuid.is_none() {
                            raw_event.uuid = Some(extracted_uuid);
                        }
                        if raw_event.distinct_id.is_none() && !extracted_distinct_id.is_empty() {
                            raw_event.distinct_id =
                                Some(serde_json::Value::String(extracted_distinct_id));
                        }
                        if raw_event.token.is_none() && !extracted_token.is_empty() {
                            raw_event.token = Some(extracted_token);
                        }

                        raw_event
                    }
                    Err(e) => {
                        error!(
                            "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                            topic, partition, offset, e
                        );
                        message
                            .nack(format!("Failed to parse RawEvent from data field: {e}"))
                            .await;
                        return Err(anyhow::anyhow!(
                            "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                            topic,
                            partition,
                            offset,
                            e
                        ));
                    }
                }
            }
            Err(e) => {
                // TODO: When DLQ is implemented, send unparseable messages there
                // For now, we just log and skip messages we can't parse (e.g., those with null ip field)
                warn!(
                    "Failed to parse CapturedEvent from {}:{} offset {}: {}. Skipping message.",
                    topic, partition, offset, e
                );
                // Ack the message to continue processing
                message.ack().await;
                return Ok(());

                // Original error handling - keeping for reference when DLQ is implemented:
                // error!(
                //     "Failed to parse CapturedEvent from {}:{} offset {}: {}",
                //     topic, partition, offset, e
                // );
                // // Nack the message so it can be handled by error recovery/DLQ
                // message
                //     .nack(format!("Failed to parse CapturedEvent JSON: {e}"))
                //     .await;
                // return Err(anyhow::anyhow!(
                //     "Failed to parse CapturedEvent from {}:{} offset {}: {}",
                //     topic,
                //     partition,
                //     offset,
                //     e
                // ));
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

        // Get the original headers to preserve them when publishing
        let headers = message.kafka_message().headers();

        // Create message context
        let ctx = MessageContext {
            topic: &topic,
            partition,
            offset,
            key,
        };

        // Process the event through deduplication, passing the original payload and headers for publishing
        match self
            .process_raw_event(raw_event, payload, headers, ctx)
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
        self.store_manager.get_active_store_count()
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
            flush_interval: Duration::from_secs(120),
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
        use crate::kafka::types::Partition;
        use dashmap::DashMap;

        let stores: Arc<DashMap<Partition, DeduplicationStore>> = Arc::new(DashMap::new());

        // Test that stores map starts empty
        assert_eq!(stores.len(), 0);

        // Test cleanup with empty stores
        let revoked = vec![Partition::new("test-topic".to_string(), 0)];
        for partition in &revoked {
            stores.remove(partition);
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
