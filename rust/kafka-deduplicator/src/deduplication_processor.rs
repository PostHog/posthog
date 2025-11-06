use anyhow::{Context, Result};
use async_trait::async_trait;
use common_kafka::kafka_producer::KafkaContext;
use common_types::{CapturedEvent, RawEvent};
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message};
use serde_json;
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, error, info, warn};

use crate::duplicate_event::DuplicateEvent;
use crate::kafka::message::{AckableMessage, MessageProcessor};
use crate::metrics::MetricsHelper;
use crate::metrics_const::{
    DEDUPLICATION_RESULT_COUNTER, DUPLICATE_EVENTS_PUBLISHED_COUNTER,
    DUPLICATE_EVENTS_TOTAL_COUNTER, TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM,
    TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM, TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER,
    TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM, TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM,
    TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM, UNIQUE_EVENTS_TOTAL_COUNTER,
    UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM, UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM,
    UUID_DEDUP_FIELD_DIFFERENCES_COUNTER, UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM,
    UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM, UUID_DEDUP_TIMESTAMP_VARIANCE_HISTOGRAM,
    UUID_DEDUP_UNIQUE_TIMESTAMPS_HISTOGRAM,
};
use crate::rocksdb::dedup_metadata::DedupFieldName;
use crate::store::deduplication_store::{
    DeduplicationResult, DeduplicationResultReason, DeduplicationType,
};
use crate::store::keys::{TimestampKey, UuidKey};
use crate::store::metadata::{TimestampMetadata, UuidMetadata};
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
    pub duplicate_events_topic: Option<String>,
    pub producer_config: ClientConfig,
    pub store_config: DeduplicationStoreConfig,
    pub producer_send_timeout: Duration,
    pub flush_interval: Duration,
}

#[derive(Clone)]
pub struct DuplicateEventProducerWrapper {
    producer: Arc<FutureProducer<KafkaContext>>,
    topic: String,
}

impl DuplicateEventProducerWrapper {
    pub fn new(topic: String, producer: Arc<FutureProducer<KafkaContext>>) -> Result<Self> {
        Ok(Self { producer, topic })
    }

    pub async fn send(
        &self,
        duplicate_event: DuplicateEvent,
        kafka_key: &str,
        timeout: Duration,
        metrics: &MetricsHelper,
    ) -> Result<()> {
        // Serialize and publish
        let payload =
            serde_json::to_vec(&duplicate_event).context("Failed to serialize duplicate event")?;

        // Send and await the result
        let delivery_result = self
            .producer
            .send(
                FutureRecord::to(&self.topic)
                    .key(kafka_key)
                    .payload(&payload),
                Timeout::After(timeout),
            )
            .await;

        match delivery_result {
            Ok(_) => {
                // Track successful publish
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &self.topic)
                    .with_label("status", "success")
                    .increment(1);
                Ok(())
            }
            Err((e, _)) => {
                // Track failed publish
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &self.topic)
                    .with_label("status", "failure")
                    .increment(1);

                // Log error but don't fail the main processing
                error!(
                    "Failed to publish duplicate event to topic {}: {}",
                    self.topic, e
                );
                // We could choose to return the error or just log it
                // For now, let's not fail the main event processing
                Ok(())
            }
        }
    }
}

/// Processor that handles deduplication of events using per-partition stores
#[derive(Clone)]
pub struct DeduplicationProcessor {
    /// Configuration for the processor
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events
    producer: Option<Arc<FutureProducer<KafkaContext>>>,

    /// Kafka producer for publishing duplicate detection results
    duplicate_producer: Option<DuplicateEventProducerWrapper>,

    /// Store manager that handles concurrent store creation and access
    store_manager: Arc<StoreManager>,
}

impl DeduplicationProcessor {
    /// Create a new deduplication processor with a store manager
    pub fn new(
        config: DeduplicationConfig,
        store_manager: Arc<StoreManager>,
        producer: Option<Arc<FutureProducer<KafkaContext>>>,
        duplicate_producer: Option<DuplicateEventProducerWrapper>,
    ) -> Result<Self> {
        Ok(Self {
            config,
            producer,
            duplicate_producer,
            store_manager,
        })
    }

    /// Get or create a deduplication store for a specific partition
    async fn get_or_create_store(&self, topic: &str, partition: i32) -> Result<DeduplicationStore> {
        self.store_manager.get_or_create(topic, partition).await
    }

    /// Main deduplication logic - checks both timestamp and UUID patterns
    async fn deduplicate_event(
        &self,
        raw_event: &RawEvent,
        store: &DeduplicationStore,
        metrics: &MetricsHelper,
    ) -> Result<DeduplicationResult> {
        // Track timestamp-based deduplication
        let deduplication_result = self.check_timestamp_duplicate(raw_event, store, metrics)?;

        if !matches!(deduplication_result, DeduplicationResult::New) {
            return Ok(deduplication_result);
        }

        // Track UUID-based deduplication (only if UUID exists)
        if raw_event.uuid.is_some() {
            let deduplication_result = self.check_uuid_duplicate(raw_event, store, metrics)?;
            return Ok(deduplication_result);
        }

        Ok(deduplication_result)
    }

    /// Check for timestamp-based duplicates
    fn check_timestamp_duplicate(
        &self,
        raw_event: &RawEvent,
        store: &DeduplicationStore,
        metrics: &MetricsHelper,
    ) -> Result<DeduplicationResult> {
        let key = TimestampKey::from(raw_event);

        // Check if this is a duplicate
        let existing_metadata = store.get_timestamp_record(&key)?;

        if let Some(mut metadata) = existing_metadata {
            // Key exists - it's a duplicate

            // Calculate similarity and get original event
            let similarity = metadata.calculate_similarity(raw_event)?;
            let original_event = metadata.get_original_event()?;

            // Always update metadata to track all seen events
            metadata.update_duplicate(raw_event);

            // Determine the deduplication result based on similarity
            let dedup_result = if similarity.overall_score == 1.0 {
                DeduplicationResult::ConfirmedDuplicate(
                    DeduplicationType::Timestamp,
                    DeduplicationResultReason::SameEvent,
                    similarity,
                    original_event,
                )
            } else if similarity.different_fields.len() == 1
                && similarity.different_fields[0].0 == DedupFieldName::Uuid
            {
                DeduplicationResult::ConfirmedDuplicate(
                    DeduplicationType::Timestamp,
                    DeduplicationResultReason::OnlyUuidDifferent,
                    similarity,
                    original_event,
                )
            } else {
                DeduplicationResult::PotentialDuplicate(
                    DeduplicationType::Timestamp,
                    similarity,
                    original_event,
                )
            };

            // Get similarity reference from the result for logging
            let similarity_ref = dedup_result.get_similarity().unwrap();

            // Log the duplicate
            info!(
                "Timestamp duplicate: {} for key {:?}, Similarity: {:.2}",
                metadata.get_metrics_summary(),
                key,
                similarity_ref.overall_score
            );

            // Emit metrics
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "timestamp")
                    .increment(1);

                metrics
                    .histogram(TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(metadata.seen_uuids.len() as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.overall_score);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.different_field_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.different_property_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.properties_similarity);

                // Emit counters for specific fields that differ
                for (field_name, _, _) in &similarity_ref.different_fields {
                    metrics
                        .counter(TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER)
                        .with_label("lib", &lib_info.name)
                        .with_label("field", &field_name.to_string())
                        .increment(1);
                }
            }

            // Store updated metadata
            store.put_timestamp_record(&key, &metadata)?;

            return Ok(dedup_result);
        }

        // Key doesn't exist - store it with initial metadata
        let metadata = TimestampMetadata::new(raw_event);
        store.put_timestamp_record(&key, &metadata)?;

        // Track unique event
        if let Some(lib_info) = raw_event.extract_library_info() {
            metrics
                .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
                .with_label("lib", &lib_info.name)
                .with_label("dedup_type", "timestamp")
                .increment(1);
        }

        Ok(DeduplicationResult::New)
    }

    /// Check for UUID-based duplicates
    fn check_uuid_duplicate(
        &self,
        raw_event: &RawEvent,
        store: &DeduplicationStore,
        metrics: &MetricsHelper,
    ) -> Result<DeduplicationResult> {
        let key = UuidKey::from(raw_event);

        // Extract timestamp for indexing
        let timestamp = raw_event
            .timestamp
            .as_ref()
            .and_then(|t| crate::utils::timestamp::parse_timestamp(t))
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis() as u64);

        // Check if this UUID combination exists
        let existing_metadata = store.get_uuid_record(&key)?;

        if let Some(mut metadata) = existing_metadata {
            // UUID combination exists - it's a duplicate

            // Calculate similarity and get original event
            let similarity = metadata.calculate_similarity(raw_event)?;
            let original_event = metadata.get_original_event()?;

            // Always update metadata to track all seen events
            metadata.update_duplicate(raw_event);

            // Determine the deduplication result based on similarity
            let dedup_result = if similarity.overall_score == 1.0 {
                DeduplicationResult::ConfirmedDuplicate(
                    DeduplicationType::UUID,
                    DeduplicationResultReason::SameEvent,
                    similarity,
                    original_event,
                )
            } else if similarity.different_fields.len() == 1
                && similarity.different_fields[0].0 == DedupFieldName::Timestamp
            {
                DeduplicationResult::ConfirmedDuplicate(
                    DeduplicationType::UUID,
                    DeduplicationResultReason::OnlyTimestampDifferent,
                    similarity,
                    original_event,
                )
            } else {
                DeduplicationResult::PotentialDuplicate(
                    DeduplicationType::UUID,
                    similarity,
                    original_event,
                )
            };

            // Get similarity reference from the result for logging and metrics
            let similarity_ref = dedup_result.get_similarity().unwrap();

            // Log the duplicate
            info!(
                "UUID duplicate: {} for key {:?}",
                metadata.get_metrics_summary(),
                key
            );

            // Emit metrics
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "uuid")
                    .increment(1);

                metrics
                    .histogram(UUID_DEDUP_TIMESTAMP_VARIANCE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(metadata.get_timestamp_variance() as f64);

                metrics
                    .histogram(UUID_DEDUP_UNIQUE_TIMESTAMPS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(metadata.seen_timestamps.len() as f64);

                metrics
                    .histogram(UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.overall_score);

                metrics
                    .histogram(UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.different_field_count as f64);

                metrics
                    .histogram(UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.different_property_count as f64);

                metrics
                    .histogram(UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity_ref.properties_similarity);

                // Emit counters for specific fields that differ
                for (field_name, _, _) in &similarity_ref.different_fields {
                    metrics
                        .counter(UUID_DEDUP_FIELD_DIFFERENCES_COUNTER)
                        .with_label("lib", &lib_info.name)
                        .with_label("field", &field_name.to_string())
                        .increment(1);
                }
            }

            // Store updated metadata
            store.put_uuid_record(&key, &metadata, timestamp)?;

            return Ok(dedup_result);
        }

        // New UUID combination - store it
        let metadata = UuidMetadata::new(raw_event);

        // Store in UUID CF (with timestamp index handled automatically)
        store.put_uuid_record(&key, &metadata, timestamp)?;

        // Track new UUID combination
        if let Some(lib_info) = raw_event.extract_library_info() {
            metrics
                .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
                .with_label("lib", &lib_info.name)
                .with_label("dedup_type", "uuid")
                .increment(1);
        }

        Ok(DeduplicationResult::New)
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

        // Create metrics helper for this partition
        let metrics = MetricsHelper::with_partition(ctx.topic, ctx.partition)
            .with_label("service", "kafka-deduplicator");

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

        // Use the processor's deduplication logic to check for duplicates
        let deduplication_result = self.deduplicate_event(&raw_event, &store, &metrics).await?;

        // Emit metrics for the deduplication result
        self.emit_deduplication_result_metrics(ctx.topic, ctx.partition, &deduplication_result);

        // Publish duplicate event if we have a duplicate producer configured
        if let Some(ref duplicate_producer) = self.duplicate_producer {
            self.publish_duplicate_event(
                duplicate_producer,
                &raw_event,
                &deduplication_result,
                &ctx.key,
                &metrics,
            )
            .await?;
        }

        let is_duplicate = deduplication_result.is_duplicate();

        if is_duplicate {
            debug!(
                "Event {} is a duplicate (result: {:?}), skipping",
                dedup_key, deduplication_result
            );
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
        producer: &FutureProducer<KafkaContext>,
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
                    "Failed to publish event with key '{key}' to topic '{output_topic}': {e}"
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
                            "Failed to parse RawEvent from data field at {topic}:{partition} offset {offset}: {e}"
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
                        "Invalid UTF-8 in message key at {topic}:{partition} offset {offset}: {e}"
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
    /// Determine if an event should be published to the duplicate events topic
    fn should_publish_event(&self, result: &DeduplicationResult) -> bool {
        matches!(
            result,
            DeduplicationResult::ConfirmedDuplicate(_, _, _, _)
                | DeduplicationResult::PotentialDuplicate(_, _, _)
        )
    }

    /// Publish duplicate event to the duplicate events topic
    async fn publish_duplicate_event(
        &self,
        producer_wrapper: &DuplicateEventProducerWrapper,
        source_event: &RawEvent,
        deduplication_result: &DeduplicationResult,
        kafka_key: &str,
        metrics: &MetricsHelper,
    ) -> Result<()> {
        // Only publish for actual duplicates (not New or Skipped)
        if !self.should_publish_event(deduplication_result) {
            return Ok(());
        }

        // Create the duplicate event
        let duplicate_event = match DuplicateEvent::from_result(source_event, deduplication_result)
        {
            Some(event) => event,
            None => return Ok(()), // Couldn't create duplicate event
        };

        // Send using the wrapper's send method
        producer_wrapper
            .send(
                duplicate_event,
                kafka_key,
                self.config.producer_send_timeout,
                metrics,
            )
            .await
    }

    /// Emit metrics for deduplication results
    fn emit_deduplication_result_metrics(
        &self,
        topic: &str,
        partition: i32,
        result: &DeduplicationResult,
    ) {
        let metrics = MetricsHelper::with_partition(topic, partition)
            .with_label("service", "kafka-deduplicator");

        match result {
            DeduplicationResult::New => {
                metrics
                    .counter(DEDUPLICATION_RESULT_COUNTER)
                    .with_label("result_type", "new")
                    .increment(1);
            }
            DeduplicationResult::PotentialDuplicate(dedup_type, _, _) => {
                metrics
                    .counter(DEDUPLICATION_RESULT_COUNTER)
                    .with_label("result_type", "potential_duplicate")
                    .with_label("dedup_type", &dedup_type.to_string().to_lowercase())
                    .increment(1);
            }
            DeduplicationResult::ConfirmedDuplicate(dedup_type, reason, _, _) => {
                metrics
                    .counter(DEDUPLICATION_RESULT_COUNTER)
                    .with_label("result_type", "confirmed_duplicate")
                    .with_label("dedup_type", &dedup_type.to_string().to_lowercase())
                    .with_label("reason", &reason.to_string().to_lowercase())
                    .increment(1);
            }
            DeduplicationResult::Skipped => {
                metrics
                    .counter(DEDUPLICATION_RESULT_COUNTER)
                    .with_label("result_type", "skipped")
                    .increment(1);
            }
        }
    }

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
            duplicate_events_topic: None,
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

    #[tokio::test]
    async fn test_timestamp_deduplication_new_event() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        let result = processor
            .check_timestamp_duplicate(&event, &store, &metrics)
            .unwrap();
        assert_eq!(result, DeduplicationResult::New);
    }

    #[tokio::test]
    async fn test_timestamp_deduplication_exact_duplicate() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // First event should be new
        let result1 = processor
            .check_timestamp_duplicate(&event, &store, &metrics)
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Exact duplicate should be confirmed duplicate
        let result2 = processor
            .check_timestamp_duplicate(&event, &store, &metrics)
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::SameEvent,
                _,
                _
            )
        ));
    }

    #[tokio::test]
    async fn test_timestamp_deduplication_only_uuid_different() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let event1 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // First event should be new
        let result1 = processor
            .check_timestamp_duplicate(&event1, &store, &metrics)
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Same event with different UUID
        let event2 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        let result2 = processor
            .check_timestamp_duplicate(&event2, &store, &metrics)
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::OnlyUuidDifferent,
                _,
                _
            )
        ));
    }

    #[tokio::test]
    async fn test_timestamp_deduplication_potential_duplicate() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let uuid = Uuid::new_v4(); // Use the same UUID for both events
        let mut properties1 = HashMap::new();
        properties1.insert("prop1".to_string(), json!("value1"));

        let event1 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: properties1,
            ..Default::default()
        };

        // First event should be new
        let result1 = processor
            .check_timestamp_duplicate(&event1, &store, &metrics)
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Similar event with different properties but same UUID
        let mut properties2 = HashMap::new();
        properties2.insert("prop1".to_string(), json!("value2"));
        properties2.insert("prop2".to_string(), json!("extra"));

        let event2 = RawEvent {
            uuid: Some(uuid), // Same UUID as event1
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: properties2,
            ..Default::default()
        };

        let result2 = processor
            .check_timestamp_duplicate(&event2, &store, &metrics)
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::PotentialDuplicate(DeduplicationType::Timestamp, _, _)
        ));
    }

    #[tokio::test]
    async fn test_uuid_deduplication_new_event() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        let result = processor
            .check_uuid_duplicate(&event, &store, &metrics)
            .unwrap();
        assert_eq!(result, DeduplicationResult::New);
    }

    #[tokio::test]
    async fn test_uuid_deduplication_only_timestamp_different() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let uuid = Uuid::new_v4();
        let event1 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // First event should be new
        let result1 = processor
            .check_uuid_duplicate(&event1, &store, &metrics)
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Same event with different timestamp
        let event2 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:01Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        let result2 = processor
            .check_uuid_duplicate(&event2, &store, &metrics)
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::UUID,
                DeduplicationResultReason::OnlyTimestampDifferent,
                _,
                _
            )
        ));
    }

    #[tokio::test]
    async fn test_combined_deduplication_flow() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let uuid = Uuid::new_v4();
        let event = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // First check should return new
        let result1 = processor
            .deduplicate_event(&event, &store, &metrics)
            .await
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Second check with same event should detect timestamp duplicate
        let result2 = processor
            .deduplicate_event(&event, &store, &metrics)
            .await
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::SameEvent,
                _,
                _
            )
        ));

        // Event with different timestamp but same UUID should detect timestamp first
        let event3 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:01Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // Since timestamp is different, it passes timestamp check and goes to UUID check
        let result3 = processor
            .deduplicate_event(&event3, &store, &metrics)
            .await
            .unwrap();
        assert!(matches!(
            result3,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::UUID,
                DeduplicationResultReason::OnlyTimestampDifferent,
                _,
                _
            )
        ));
    }

    #[tokio::test]
    async fn test_deduplication_without_uuid() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let event = RawEvent {
            uuid: None,
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // First event without UUID should be new
        let result1 = processor
            .deduplicate_event(&event, &store, &metrics)
            .await
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        // Duplicate event without UUID should be detected by timestamp
        let result2 = processor
            .deduplicate_event(&event, &store, &metrics)
            .await
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::SameEvent,
                _,
                _
            )
        ));
    }

    #[tokio::test]
    async fn test_deduplication_with_library_metrics() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = DeduplicationProcessor::new(config, store_manager, None, None).unwrap();

        let store = processor
            .get_or_create_store("test-topic", 0)
            .await
            .unwrap();
        let metrics = MetricsHelper::with_partition("test-topic", 0)
            .with_label("service", "kafka-deduplicator");

        let mut properties = HashMap::new();
        properties.insert("$lib".to_string(), json!("posthog-js"));
        properties.insert("$lib_version".to_string(), json!("1.0.0"));

        let event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user1")),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            properties,
            ..Default::default()
        };

        // Process event twice to test metrics emission with library info
        let result1 = processor
            .check_timestamp_duplicate(&event, &store, &metrics)
            .unwrap();
        assert_eq!(result1, DeduplicationResult::New);

        let result2 = processor
            .check_timestamp_duplicate(&event, &store, &metrics)
            .unwrap();
        assert!(matches!(
            result2,
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::SameEvent,
                _,
                _
            )
        ));
    }
}
