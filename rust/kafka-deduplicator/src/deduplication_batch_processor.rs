use std::{collections::HashMap, sync::Arc, time::Duration};

use anyhow::{Context, Result};
use axum::async_trait;
use common_kafka::kafka_producer::KafkaContext;
use common_types::{CapturedEvent, RawEvent};
use futures::future::join_all;
use itertools::Itertools;
use rayon::prelude::*;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use tracing::{debug, error};

use crate::kafka::types::Partition;
use crate::{
    duplicate_event::DuplicateEvent,
    kafka::batch_consumer::BatchConsumerProcessor,
    kafka::batch_message::KafkaMessage,
    metrics::MetricsHelper,
    metrics_const::{
        DEDUPLICATION_RESULT_COUNTER, DUPLICATE_EVENTS_PUBLISHED_COUNTER,
        DUPLICATE_EVENTS_TOTAL_COUNTER, TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM,
        TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM, TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER,
        TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM,
        TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM, UNIQUE_EVENTS_TOTAL_COUNTER,
        UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM, UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM,
        UUID_DEDUP_FIELD_DIFFERENCES_COUNTER, UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM,
        UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM,
    },
    rocksdb::dedup_metadata::DedupFieldName,
    store::deduplication_store::{
        DeduplicationResult, DeduplicationResultReason, DeduplicationType, TimestampBatchEntry,
        UuidBatchEntry,
    },
    store::keys::{TimestampKey, UuidKey},
    store::metadata::{TimestampMetadata, UuidMetadata},
    store::DeduplicationStoreConfig,
    store_manager::StoreManager,
    utils::timestamp,
};

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
        let payload =
            serde_json::to_vec(&duplicate_event).context("Failed to serialize duplicate event")?;

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
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &self.topic)
                    .with_label("status", "success")
                    .increment(1);
                Ok(())
            }
            Err((e, _)) => {
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &self.topic)
                    .with_label("status", "failure")
                    .increment(1);

                error!(
                    "Failed to publish duplicate event to topic {}: {}",
                    self.topic, e
                );
                Ok(())
            }
        }
    }
}

/// Enriched event with deduplication keys
struct EnrichedEvent<'a> {
    raw_event: &'a RawEvent,
    uuid_key: Option<UuidKey>,
    timestamp_key_bytes: Vec<u8>,
    uuid_key_bytes: Option<Vec<u8>>,
    parsed_timestamp: u64,
}

pub struct BatchDeduplicationProcessor {
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events
    producer: Option<Arc<FutureProducer<KafkaContext>>>,

    /// Kafka producer for publishing duplicate detection results
    duplicate_producer: Option<DuplicateEventProducerWrapper>,

    /// Store manager that handles concurrent store creation and access
    store_manager: Arc<StoreManager>,
}

#[async_trait]
impl BatchConsumerProcessor<CapturedEvent> for BatchDeduplicationProcessor {
    async fn process_batch(&self, messages: Vec<KafkaMessage<CapturedEvent>>) -> Result<()> {
        // Organize messages by partition
        let messages_by_partition = messages
            .iter()
            .map(|message| (message.get_topic_partition(), message))
            .into_group_map();

        // Process partitions concurrently using async tasks
        // Each partition has its own RocksDB store, so concurrent processing is safe
        // Note: Within each partition, we use rayon for CPU-bound JSON parsing

        let mut promises = vec![];
        for (partition, messages) in messages_by_partition {
            promises.push(self.process_partition_batch(partition, messages));
        }

        let results = join_all(promises).await;

        // Check for any errors
        for result in results {
            result?;
        }

        Ok(())
    }
}

impl BatchDeduplicationProcessor {
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

    async fn process_partition_batch(
        &self,
        partition: Partition,
        messages: Vec<&KafkaMessage<CapturedEvent>>,
    ) -> Result<()> {
        // Parse events in parallel (CPU-bound work - good use of rayon)
        // Use block_in_place to avoid blocking the async runtime thread pool
        let parsed_events: Vec<Result<RawEvent>> = tokio::task::block_in_place(|| {
            messages.par_iter().map(Self::parse_raw_event).collect()
        });

        // Collect successful parses and extract metadata sequentially
        // This avoids cloning the entire message - we just copy the small pieces we need
        let successful_count = parsed_events.iter().filter(|r| r.is_ok()).count();
        let mut events = Vec::with_capacity(successful_count);
        let mut payloads = Vec::with_capacity(successful_count);
        let mut headers_vec = Vec::with_capacity(successful_count);
        let mut keys = Vec::with_capacity(successful_count);

        for (idx, msg) in messages.iter().enumerate() {
            if let Ok(event) = &parsed_events[idx] {
                events.push(event);

                // Extract original contents (both borrow, no cloning!)
                let (payload_ref, headers_ref) = msg.to_original_contents();

                // Copy only what we need for publishing
                payloads.push(payload_ref.to_vec());
                headers_vec.push(headers_ref.cloned());

                // Extract key (small string copy)
                let key = msg
                    .key_as_str()
                    .and_then(|r| r.ok())
                    .unwrap_or("")
                    .to_string();
                keys.push(key);
            } else if let Err(e) = &parsed_events[idx] {
                error!("Failed to parse event: {}", e);
            }
        }

        if events.is_empty() {
            return Ok(());
        }

        // Deduplicate the batch for this partition
        let dedup_results = self
            .deduplicate_batch(partition.topic(), partition.partition_number(), events)
            .await?;

        // Process results: emit metrics and publish events
        for (idx, result) in dedup_results.iter().enumerate() {
            let payload = &payloads[idx];
            let headers = &headers_vec[idx];
            let key = &keys[idx];

            // Emit deduplication result metrics
            self.emit_deduplication_result_metrics(
                partition.topic(),
                partition.partition_number(),
                result,
            );

            // Publish duplicate event if configured
            if let Some(ref duplicate_producer) = self.duplicate_producer {
                if self.should_publish_duplicate_event(result) {
                    if let Some(original_event) = result.get_original_event() {
                        let metrics = MetricsHelper::with_partition(
                            partition.topic(),
                            partition.partition_number(),
                        )
                        .with_label("service", "kafka-deduplicator");

                        if let Err(e) = self
                            .publish_duplicate_event(
                                duplicate_producer,
                                original_event,
                                result,
                                key,
                                &metrics,
                            )
                            .await
                        {
                            error!("Failed to publish duplicate event: {}", e);
                        }
                    }
                }
            }

            // Publish non-duplicate events to output topic
            if !result.is_duplicate() {
                if let Some(ref producer) = self.producer {
                    if let Some(ref output_topic) = self.config.output_topic {
                        if let Err(e) = self
                            .publish_event(
                                producer,
                                payload,
                                headers.as_ref(),
                                key.to_string(),
                                output_topic,
                            )
                            .await
                        {
                            error!("Failed to publish non-duplicate event: {}", e);
                            return Err(e);
                        }
                    }
                }
            }
        }

        Ok(())
    }

    async fn deduplicate_batch(
        &self,
        topic: &str,
        partition: i32,
        events: Vec<&RawEvent>,
    ) -> Result<Vec<DeduplicationResult>> {
        // Get the store for this partition
        let store = self.store_manager.get_or_create(topic, partition).await?;

        // Create metrics helper for this partition
        let metrics = MetricsHelper::with_partition(topic, partition)
            .with_label("service", "kafka-deduplicator");

        // Step 1: Prepare all keys and enrich events with parsed data
        let enriched_events: Vec<EnrichedEvent> = events
            .into_iter()
            .map(|raw_event| {
                let timestamp_key = TimestampKey::from(raw_event);
                let timestamp_key_bytes: Vec<u8> = (&timestamp_key).into();

                let (uuid_key, uuid_key_bytes, parsed_timestamp) = if raw_event.uuid.is_some() {
                    let uuid_key = UuidKey::from(raw_event);
                    let uuid_key_bytes: Vec<u8> = (&uuid_key).into();
                    let parsed_timestamp = raw_event
                        .timestamp
                        .as_ref()
                        .and_then(|t| timestamp::parse_timestamp(t))
                        .unwrap_or_else(|| chrono::Utc::now().timestamp_millis() as u64);
                    (Some(uuid_key), Some(uuid_key_bytes), parsed_timestamp)
                } else {
                    (None, None, 0)
                };

                EnrichedEvent {
                    raw_event,
                    uuid_key,
                    timestamp_key_bytes,
                    uuid_key_bytes,
                    parsed_timestamp,
                }
            })
            .collect();

        // Step 2: Batch read for timestamp-based deduplication
        let timestamp_keys_refs: Vec<&[u8]> = enriched_events
            .iter()
            .map(|e| e.timestamp_key_bytes.as_slice())
            .collect();

        let timestamp_results = store.multi_get_timestamp_records(timestamp_keys_refs)?;

        // Step 3: Batch read for UUID-based deduplication (only for events with UUIDs that pass timestamp check)
        let uuid_keys_to_check: Vec<(usize, &[u8])> = enriched_events
            .iter()
            .enumerate()
            .filter_map(|(idx, e)| {
                // Only check UUID if:
                // 1. Event has a UUID
                // 2. Timestamp check passed (new or not found)
                if e.uuid_key_bytes.is_some() && timestamp_results[idx].is_none() {
                    Some((idx, e.uuid_key_bytes.as_ref().unwrap().as_slice()))
                } else {
                    None
                }
            })
            .collect();

        let uuid_keys_refs: Vec<&[u8]> = uuid_keys_to_check.iter().map(|(_, key)| *key).collect();

        let uuid_results = if !uuid_keys_refs.is_empty() {
            store.multi_get_uuid_records(uuid_keys_refs)?
        } else {
            vec![]
        };

        // Create a map of UUID results by original index
        let uuid_results_map: HashMap<usize, Option<Vec<u8>>> = uuid_keys_to_check
            .iter()
            .zip(uuid_results.into_iter())
            .map(|((idx, _), result)| (*idx, result))
            .collect();

        // Step 4: Process deduplication results and prepare batch writes
        // Track keys we've seen in this batch to detect within-batch duplicates
        let event_count = enriched_events.len();
        let mut batch_timestamp_cache: HashMap<Vec<u8>, Vec<u8>> =
            HashMap::with_capacity(event_count);
        let mut batch_uuid_cache: HashMap<Vec<u8>, Vec<u8>> = HashMap::with_capacity(event_count);

        let mut timestamp_writes: Vec<(Vec<u8>, Vec<u8>)> = Vec::with_capacity(event_count);
        let mut uuid_writes: Vec<(Vec<u8>, Vec<u8>, u64)> = Vec::with_capacity(event_count);
        let mut dedup_results: Vec<DeduplicationResult> = Vec::with_capacity(event_count);

        for (idx, enriched) in enriched_events.iter().enumerate() {
            let raw_event = &enriched.raw_event;

            // Check timestamp-based deduplication
            // First check RocksDB results, then check within-batch cache
            let timestamp_source: Option<&[u8]> = timestamp_results[idx].as_deref().or_else(|| {
                batch_timestamp_cache
                    .get(&enriched.timestamp_key_bytes)
                    .map(|v| v.as_slice())
            });

            let timestamp_result =
                match Self::check_timestamp_duplicate_from_bytes(timestamp_source, raw_event) {
                    Ok((result, metadata)) => {
                        if let Some(metadata) = metadata {
                            // Update metadata and prepare for write
                            let value = bincode::serde::encode_to_vec(
                                &metadata,
                                bincode::config::standard(),
                            )?;
                            timestamp_writes
                                .push((enriched.timestamp_key_bytes.clone(), value.clone()));

                            // Update batch cache for within-batch duplicate detection
                            batch_timestamp_cache
                                .insert(enriched.timestamp_key_bytes.clone(), value);
                        }

                        // Emit metrics for timestamp deduplication
                        Self::emit_timestamp_metrics(&result, raw_event, &metrics);

                        result
                    }
                    Err(e) => {
                        error!("Failed to check timestamp duplicate: {}", e);
                        DeduplicationResult::Skipped
                    }
                };

            // If timestamp check found a duplicate, we're done
            if timestamp_result.is_duplicate() {
                dedup_results.push(timestamp_result);
                continue;
            }

            // Check UUID-based deduplication if applicable
            if enriched.uuid_key.is_some() {
                let uuid_key_bytes = enriched.uuid_key_bytes.as_ref().unwrap();

                // First check RocksDB results, then check within-batch cache
                let uuid_source: Option<&[u8]> = uuid_results_map
                    .get(&idx)
                    .and_then(|r| r.as_deref())
                    .or_else(|| batch_uuid_cache.get(uuid_key_bytes).map(|v| v.as_slice()));

                let uuid_result =
                    match Self::check_uuid_duplicate_from_bytes(uuid_source, raw_event) {
                        Ok((result, metadata)) => {
                            if let Some(metadata) = metadata {
                                // Update metadata and prepare for write
                                let value = bincode::serde::encode_to_vec(
                                    &metadata,
                                    bincode::config::standard(),
                                )?;
                                uuid_writes.push((
                                    uuid_key_bytes.clone(),
                                    value.clone(),
                                    enriched.parsed_timestamp,
                                ));

                                // Update batch cache for within-batch duplicate detection
                                batch_uuid_cache.insert(uuid_key_bytes.clone(), value);
                            }

                            // Emit metrics for UUID deduplication
                            Self::emit_uuid_metrics(&result, raw_event, &metrics);

                            result
                        }
                        Err(e) => {
                            error!("Failed to check UUID duplicate: {}", e);
                            DeduplicationResult::Skipped
                        }
                    };

                dedup_results.push(uuid_result);
            } else {
                // No UUID, just use timestamp result
                dedup_results.push(timestamp_result);
            }
        }

        // Step 5: Batch write all updates
        if !timestamp_writes.is_empty() {
            let entries: Vec<TimestampBatchEntry> = timestamp_writes
                .iter()
                .map(|(key, value)| TimestampBatchEntry {
                    key: key.as_slice(),
                    value: value.as_slice(),
                })
                .collect();
            store.put_timestamp_records_batch(entries)?;
        }

        // UUID writes need to also update the timestamp index
        if !uuid_writes.is_empty() {
            let entries: Vec<UuidBatchEntry> = uuid_writes
                .iter()
                .map(|(key, value, timestamp)| UuidBatchEntry {
                    key: key.as_slice(),
                    value: value.as_slice(),
                    timestamp: *timestamp,
                })
                .collect();
            store.put_uuid_records_batch(entries)?;
        }

        Ok(dedup_results)
    }

    /// Determine if an event should be published to the duplicate events topic
    fn should_publish_duplicate_event(&self, result: &DeduplicationResult) -> bool {
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

    /// Publish event to output topic
    async fn publish_event(
        &self,
        producer: &FutureProducer<KafkaContext>,
        payload: &[u8],
        headers: Option<&rdkafka::message::OwnedHeaders>,
        key: String,
        output_topic: &str,
    ) -> Result<()> {
        let mut record = FutureRecord::to(output_topic).key(&key).payload(payload);

        if let Some(h) = headers {
            record = record.headers(h.clone());
        }

        match producer
            .send(record, Timeout::After(self.config.producer_send_timeout))
            .await
        {
            Ok(_) => {
                debug!(
                    "Successfully published non-duplicate event with key {} to {}",
                    key, output_topic
                );
                Ok(())
            }
            Err((e, _)) => {
                error!(
                    "Failed to publish event with key {} to {}: {}",
                    key, output_topic, e
                );
                Err(anyhow::anyhow!(
                    "Failed to publish event with key '{key}' to topic '{output_topic}': {e}"
                ))
            }
        }
    }

    /// Check timestamp-based duplicate from raw bytes
    fn check_timestamp_duplicate_from_bytes(
        existing_bytes: Option<&[u8]>,
        raw_event: &RawEvent,
    ) -> Result<(DeduplicationResult, Option<TimestampMetadata>)> {
        match existing_bytes {
            Some(bytes) => {
                // Deserialize existing metadata
                let mut metadata: TimestampMetadata =
                    bincode::serde::decode_from_slice(bytes, bincode::config::standard())
                        .map(|(m, _)| m)?;

                // Calculate similarity and get original event
                let similarity = metadata.calculate_similarity(raw_event)?;
                let original_event = metadata.get_original_event()?;

                // Update metadata to track this duplicate
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

                Ok((dedup_result, Some(metadata)))
            }
            None => {
                // New event - create metadata
                let metadata = TimestampMetadata::new(raw_event);
                Ok((DeduplicationResult::New, Some(metadata)))
            }
        }
    }

    /// Check UUID-based duplicate from raw bytes
    fn check_uuid_duplicate_from_bytes(
        existing_bytes: Option<&[u8]>,
        raw_event: &RawEvent,
    ) -> Result<(DeduplicationResult, Option<UuidMetadata>)> {
        match existing_bytes {
            Some(bytes) => {
                // Deserialize existing metadata
                let mut metadata: UuidMetadata =
                    bincode::serde::decode_from_slice(bytes, bincode::config::standard())
                        .map(|(m, _)| m)?;

                // Calculate similarity and get original event
                let similarity = metadata.calculate_similarity(raw_event)?;
                let original_event = metadata.get_original_event()?;

                // Update metadata to track this duplicate
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

                Ok((dedup_result, Some(metadata)))
            }
            None => {
                // New event - create metadata
                let metadata = UuidMetadata::new(raw_event);
                Ok((DeduplicationResult::New, Some(metadata)))
            }
        }
    }

    /// Emit metrics for timestamp deduplication
    fn emit_timestamp_metrics(
        result: &DeduplicationResult,
        raw_event: &RawEvent,
        metrics: &MetricsHelper,
    ) {
        if let Some(similarity) = result.get_similarity() {
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "timestamp")
                    .increment(1);

                metrics
                    .histogram(TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.overall_score);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.different_field_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.different_property_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.properties_similarity);

                for (field_name, _, _) in &similarity.different_fields {
                    metrics
                        .counter(TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER)
                        .with_label("lib", &lib_info.name)
                        .with_label("field", &field_name.to_string())
                        .increment(1);
                }
            }
        } else if matches!(result, DeduplicationResult::New) {
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "timestamp")
                    .increment(1);
            }
        }
    }

    /// Emit metrics for UUID deduplication
    fn emit_uuid_metrics(
        result: &DeduplicationResult,
        raw_event: &RawEvent,
        metrics: &MetricsHelper,
    ) {
        if let Some(similarity) = result.get_similarity() {
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "uuid")
                    .increment(1);

                metrics
                    .histogram(UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.overall_score);

                metrics
                    .histogram(UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.different_field_count as f64);

                metrics
                    .histogram(UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.different_property_count as f64);

                metrics
                    .histogram(UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(similarity.properties_similarity);

                for (field_name, _, _) in &similarity.different_fields {
                    metrics
                        .counter(UUID_DEDUP_FIELD_DIFFERENCES_COUNTER)
                        .with_label("lib", &lib_info.name)
                        .with_label("field", &field_name.to_string())
                        .increment(1);
                }
            }
        } else if matches!(result, DeduplicationResult::New) {
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
                    .with_label("lib", &lib_info.name)
                    .with_label("dedup_type", "uuid")
                    .increment(1);
            }
        }
    }

    fn parse_raw_event(message: &&KafkaMessage<CapturedEvent>) -> Result<RawEvent> {
        // Parse the captured event and extract the raw event from it
        let captured_event = match message.get_message() {
            Some(captured_event) => captured_event,
            None => {
                // This should never fail since batch consumer catches errors
                // of this sort upstream when unpacking the batch. As with stateful
                // consumer, let's report but not fail on this if it does happen
                error!(
                    "Failed to extract CapturedEvent from KafkaMessage at {}:{} offset {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset()
                );

                return Err(anyhow::anyhow!(
                    "Failed to extract CapturedEvent from KafkaMessage at {}:{} offset {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                ));
            }
        };

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
                            message.get_topic_partition().topic(), message.get_topic_partition().partition_number(), message.get_offset()
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
                    raw_event.distinct_id = Some(serde_json::Value::String(extracted_distinct_id));
                }
                if raw_event.token.is_none() && !extracted_token.is_empty() {
                    raw_event.token = Some(extracted_token);
                }

                Ok(raw_event)
            }
            Err(e) => {
                error!(
                    "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                    e
                );
                Err(anyhow::anyhow!(
                    "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                    e
                ))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::DeduplicationStoreConfig;
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

        let mut producer_config = rdkafka::ClientConfig::new();
        producer_config.set("bootstrap.servers", "localhost:9092");
        producer_config.set("message.timeout.ms", "5000");

        let config = DeduplicationConfig {
            output_topic: Some("deduplicated-events".to_string()),
            duplicate_events_topic: None,
            producer_config,
            store_config,
            producer_send_timeout: std::time::Duration::from_secs(5),
            flush_interval: std::time::Duration::from_secs(120),
        };

        (config, temp_dir)
    }

    fn create_test_raw_event(
        uuid: Option<Uuid>,
        event: &str,
        distinct_id: &str,
        timestamp: &str,
    ) -> RawEvent {
        let mut properties = HashMap::new();
        properties.insert("test_property".to_string(), json!("test_value"));

        RawEvent {
            uuid,
            event: event.to_string(),
            distinct_id: Some(json!(distinct_id)),
            token: Some("test_token".to_string()),
            timestamp: Some(timestamp.to_string()),
            properties,
            ..Default::default()
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_all_new_events() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        // Create a batch of new events
        let events = vec![
            create_test_raw_event(
                Some(Uuid::new_v4()),
                "event1",
                "user1",
                "2024-01-01T00:00:00Z",
            ),
            create_test_raw_event(
                Some(Uuid::new_v4()),
                "event2",
                "user2",
                "2024-01-01T00:00:01Z",
            ),
            create_test_raw_event(
                Some(Uuid::new_v4()),
                "event3",
                "user3",
                "2024-01-01T00:00:02Z",
            ),
        ];

        let event_refs: Vec<&RawEvent> = events.iter().collect();
        let results = processor
            .deduplicate_batch("test-topic", 0, event_refs)
            .await
            .unwrap();

        // All events should be new
        assert_eq!(results.len(), 3);
        for result in results {
            assert!(matches!(result, DeduplicationResult::New));
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_with_timestamp_duplicates() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        // First batch - all new
        let batch1 = vec![
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let results1 = processor
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert_eq!(results1.len(), 2);
        assert!(matches!(results1[0], DeduplicationResult::New));
        assert!(matches!(results1[1], DeduplicationResult::New));

        // Second batch - same events (timestamp duplicates)
        let batch2 = vec![
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let refs2: Vec<&RawEvent> = batch2.iter().collect();
        let results2 = processor
            .deduplicate_batch("test-topic", 0, refs2)
            .await
            .unwrap();
        assert_eq!(results2.len(), 2);
        assert!(results2[0].is_duplicate());
        assert!(results2[1].is_duplicate());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_with_uuid_duplicates() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        let uuid = Uuid::new_v4();

        // First batch - new event
        let batch1 = vec![create_test_raw_event(
            Some(uuid),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results1 = processor
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert!(matches!(results1[0], DeduplicationResult::New));

        // Second batch - same UUID, different timestamp (UUID duplicate)
        let batch2 = vec![create_test_raw_event(
            Some(uuid),
            "event1",
            "user1",
            "2024-01-01T00:00:01Z",
        )];

        let results2 = processor
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();
        assert!(matches!(
            results2[0],
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::UUID,
                DeduplicationResultReason::OnlyTimestampDifferent,
                _,
                _
            )
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_mixed_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        // First batch - establish baseline
        let batch1 = vec![create_test_raw_event(
            Some(uuid1),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results1 = processor
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert!(matches!(results1[0], DeduplicationResult::New));

        // Second batch - mix of new and duplicate
        let batch2 = vec![
            // Exact duplicate (timestamp)
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            // New event
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
            // UUID duplicate with different timestamp
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:02Z"),
        ];

        let results2 = processor
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();

        assert_eq!(results2.len(), 3);
        assert!(results2[0].is_duplicate()); // Timestamp duplicate
        assert!(matches!(results2[1], DeduplicationResult::New)); // New event
        assert!(matches!(
            results2[2],
            DeduplicationResult::ConfirmedDuplicate(DeduplicationType::UUID, _, _, _)
        )); // UUID duplicate
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_events_without_uuid() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        // First batch - events without UUIDs
        let batch1 = vec![
            create_test_raw_event(None, "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(None, "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let results1 = processor
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert_eq!(results1.len(), 2);
        assert!(matches!(results1[0], DeduplicationResult::New));
        assert!(matches!(results1[1], DeduplicationResult::New));

        // Second batch - duplicate events (only timestamp-based dedup)
        let batch2 = vec![create_test_raw_event(
            None,
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results2 = processor
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();
        assert!(results2[0].is_duplicate());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_large_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        // Create a large batch of unique events
        let batch_size = 100;
        let events: Vec<RawEvent> = (0..batch_size)
            .map(|i| {
                create_test_raw_event(
                    Some(Uuid::new_v4()),
                    &format!("event{i}"),
                    &format!("user{i}"),
                    &format!("2024-01-01T00:{:02}:00Z", i % 60),
                )
            })
            .collect();

        let results = processor
            .deduplicate_batch("test-topic", 0, events.iter().collect())
            .await
            .unwrap();

        // All should be new
        assert_eq!(results.len(), batch_size);
        for result in &results {
            assert!(matches!(result, DeduplicationResult::New));
        }

        // Process the same batch again - all should be duplicates
        let events2: Vec<RawEvent> = (0..batch_size)
            .map(|i| {
                create_test_raw_event(
                    Some(Uuid::new_v4()),
                    &format!("event{i}"),
                    &format!("user{i}"),
                    &format!("2024-01-01T00:{:02}:00Z", i % 60),
                )
            })
            .collect();

        let results2 = processor
            .deduplicate_batch("test-topic", 0, events2.iter().collect())
            .await
            .unwrap();

        // All should be duplicates
        assert_eq!(results2.len(), batch_size);
        for result in &results2 {
            assert!(result.is_duplicate());
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_only_uuid_different() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        let uuid1 = Uuid::new_v4();

        // First event
        let batch1 = vec![create_test_raw_event(
            Some(uuid1),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        processor
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();

        // Same event with different UUID
        let uuid2 = Uuid::new_v4();
        let batch2 = vec![create_test_raw_event(
            Some(uuid2),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results2 = processor
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();

        // Should be detected as timestamp duplicate with only UUID different
        assert!(matches!(
            results2[0],
            DeduplicationResult::ConfirmedDuplicate(
                DeduplicationType::Timestamp,
                DeduplicationResultReason::OnlyUuidDifferent,
                _,
                _
            )
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_within_same_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(config.store_config.clone()));
        let processor = BatchDeduplicationProcessor {
            config,
            producer: None,
            duplicate_producer: None,
            store_manager,
        };

        let uuid = Uuid::new_v4();

        // Batch with duplicate events within the same batch
        let batch = vec![
            create_test_raw_event(Some(uuid), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid), "event1", "user1", "2024-01-01T00:00:00Z"),
        ];

        let results = processor
            .deduplicate_batch("test-topic", 0, batch.iter().collect())
            .await
            .unwrap();

        assert_eq!(results.len(), 2);
        // First should be new
        assert!(matches!(results[0], DeduplicationResult::New));
        // Second should be duplicate
        assert!(results[1].is_duplicate());
    }
}
