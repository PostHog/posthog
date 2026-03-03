//! Batch processor for ingestion events pipeline.
//!
//! This processor implements timestamp-based deduplication for PostHog
//! ingestion events (CapturedEvent/RawEvent) using the shared `TimestampDeduplicator`.

use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use axum::async_trait;
use common_kafka::kafka_producer::KafkaContext;
use common_types::{CapturedEvent, EventWithLibraryInfo, RawEvent};
use futures::future::join_all;
use itertools::Itertools;
use rayon::prelude::*;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use tracing::{debug, error, warn};

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::types::Partition;
use crate::metrics::MetricsHelper;
use crate::metrics_const::{
    DUPLICATE_EVENTS_PUBLISHED_COUNTER, EVENT_PARSING_DURATION_MS, FAIL_OPEN_EVENTS_PASSED_THROUGH,
    KAFKA_PRODUCER_SEND_DURATION_MS, PARTITION_BATCH_PROCESSING_DURATION_MS,
    TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM, TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM,
    TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER, TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM,
    TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM, TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM,
};
use crate::pipelines::traits::{EventParser, FailOpenProcessor};
use crate::pipelines::DeduplicationResult;
use crate::pipelines::{TimestampDeduplicator, TimestampDeduplicatorConfig};
use crate::store::DeduplicationStoreConfig;
use crate::store_manager::StoreManager;

use super::duplicate_event::DuplicateEvent;
use super::IngestionEventParser;

/// Configuration for the ingestion events deduplication processor
#[derive(Debug, Clone)]
pub struct DeduplicationConfig {
    pub output_topic: Option<String>,
    pub duplicate_events_topic: Option<String>,
    pub producer_config: ClientConfig,
    pub store_config: DeduplicationStoreConfig,
    pub producer_send_timeout: Duration,
    pub flush_interval: Duration,
    /// When true, bypass all deduplication and forward events directly to the output topic.
    pub fail_open: bool,
}

#[derive(Clone)]
pub struct DuplicateEventProducerWrapper {
    pub producer: Arc<FutureProducer<KafkaContext>>,
    pub topic: String,
}

impl DuplicateEventProducerWrapper {
    pub fn new(topic: String, producer: Arc<FutureProducer<KafkaContext>>) -> Result<Self> {
        Ok(Self { producer, topic })
    }

    /// Send a duplicate event (static version for concurrent execution)
    ///
    /// Takes owned values so it can be collected into a Vec of futures and executed with join_all.
    pub async fn send_static(
        producer: Arc<FutureProducer<KafkaContext>>,
        topic: String,
        duplicate_event: DuplicateEvent,
        kafka_key: String,
        timeout: Duration,
        partition_topic: String,
        partition_number: i32,
    ) -> Result<()> {
        let payload =
            serde_json::to_vec(&duplicate_event).context("Failed to serialize duplicate event")?;

        let delivery_result = producer
            .send(
                FutureRecord::to(&topic).key(&kafka_key).payload(&payload),
                Timeout::After(timeout),
            )
            .await;

        let metrics = MetricsHelper::with_partition(&partition_topic, partition_number);

        match delivery_result {
            Ok(_) => {
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &topic)
                    .with_label("status", "success")
                    .increment(1);
                Ok(())
            }
            Err((e, _)) => {
                metrics
                    .counter(DUPLICATE_EVENTS_PUBLISHED_COUNTER)
                    .with_label("topic", &topic)
                    .with_label("status", "failure")
                    .increment(1);

                error!(
                    "Failed to publish duplicate event to topic {}: {}",
                    topic, e
                );
                Ok(())
            }
        }
    }
}

/// Batch processor for ingestion events with timestamp-based deduplication.
///
/// This processor:
/// 1. Parses CapturedEvent (wire format) into RawEvent (domain format)
/// 2. Extracts deduplication keys based on timestamp + event + distinct_id + token
/// 3. Checks for duplicates in RocksDB using `TimestampDeduplicator`
/// 4. Publishes non-duplicate events to output topic
/// 5. Optionally publishes duplicate detection results to a separate topic
pub struct IngestionEventsBatchProcessor {
    config: DeduplicationConfig,

    /// Kafka producer for publishing non-duplicate events
    producer: Option<Arc<FutureProducer<KafkaContext>>>,

    /// Kafka producer for publishing duplicate detection results
    duplicate_producer: Option<DuplicateEventProducerWrapper>,

    /// Generic timestamp-based deduplicator
    deduplicator: TimestampDeduplicator<RawEvent>,

    /// Offset tracker for recording producer offsets (used for checkpointing)
    offset_tracker: Option<Arc<OffsetTracker>>,
}

#[async_trait]
impl BatchConsumerProcessor<CapturedEvent> for IngestionEventsBatchProcessor {
    async fn process_batch(&self, messages: Vec<KafkaMessage<CapturedEvent>>) -> Result<()> {
        if self.config.fail_open {
            return self.process_batch_fail_open(messages).await;
        }

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

#[async_trait]
impl FailOpenProcessor<CapturedEvent> for IngestionEventsBatchProcessor {
    async fn process_batch_fail_open(
        &self,
        messages: Vec<KafkaMessage<CapturedEvent>>,
    ) -> Result<()> {
        let batch_start = Instant::now();
        let message_count = messages.len();

        let (producer, output_topic) = match (&self.producer, &self.config.output_topic) {
            (Some(p), Some(t)) => (p.clone(), t.clone()),
            _ => {
                // No output topic configured — nothing to forward
                metrics::counter!(FAIL_OPEN_EVENTS_PASSED_THROUGH).increment(message_count as u64);
                return Ok(());
            }
        };

        let mut publish_futures = Vec::with_capacity(message_count);
        for msg in &messages {
            let (payload, headers) = msg.to_original_contents();
            let key = msg
                .key_as_str()
                .and_then(|r| r.ok())
                .unwrap_or("")
                .to_string();

            publish_futures.push(Self::publish_event_static(
                producer.clone(),
                payload.to_vec(),
                headers.cloned(),
                key,
                output_topic.clone(),
                self.config.producer_send_timeout,
            ));
        }

        let results = join_all(publish_futures).await;

        let mut max_producer_offset: Option<i64> = None;
        for result in results {
            match result {
                Ok(offset) => {
                    max_producer_offset =
                        Some(max_producer_offset.map_or(offset, |current| current.max(offset)));
                }
                Err(e) => {
                    error!("Failed to publish event in fail-open mode: {e:#}");
                    return Err(e);
                }
            }
        }

        // Record the max producer offset for checkpointing
        if let Some(ref tracker) = self.offset_tracker {
            if let Some(offset) = max_producer_offset {
                // In fail-open mode, messages may span multiple partitions in this batch.
                // Record offset per input partition for accuracy.
                for msg in &messages {
                    let partition = msg.get_topic_partition();
                    tracker.mark_produced(&partition, offset);
                }
            }
        }

        metrics::counter!(FAIL_OPEN_EVENTS_PASSED_THROUGH).increment(message_count as u64);

        let batch_duration = batch_start.elapsed();
        metrics::histogram!(PARTITION_BATCH_PROCESSING_DURATION_MS)
            .record(batch_duration.as_millis() as f64);

        debug!(
            message_count = message_count,
            duration_ms = batch_duration.as_millis(),
            "Fail-open: forwarded batch without deduplication"
        );

        Ok(())
    }
}

impl IngestionEventsBatchProcessor {
    /// Create a new deduplication processor with a store manager
    pub fn new(
        config: DeduplicationConfig,
        store_manager: Arc<StoreManager>,
        producer: Option<Arc<FutureProducer<KafkaContext>>>,
        duplicate_producer: Option<DuplicateEventProducerWrapper>,
    ) -> Result<Self> {
        // Create deduplicator - publishing is handled by this processor directly,
        // not by the deduplicator, so we don't set publisher config.
        let dedup_config = TimestampDeduplicatorConfig {
            pipeline_name: "ingestion_events".to_string(),
            publisher: None,
            offset_tracker: None,
        };
        let deduplicator = TimestampDeduplicator::new(dedup_config, store_manager);

        Ok(Self {
            config,
            producer,
            duplicate_producer,
            deduplicator,
            offset_tracker: None,
        })
    }

    /// Create a new deduplication processor with offset tracking for checkpointing
    pub fn new_with_offset_tracker(
        config: DeduplicationConfig,
        store_manager: Arc<StoreManager>,
        producer: Option<Arc<FutureProducer<KafkaContext>>>,
        duplicate_producer: Option<DuplicateEventProducerWrapper>,
        offset_tracker: Arc<OffsetTracker>,
    ) -> Result<Self> {
        let dedup_config = TimestampDeduplicatorConfig {
            pipeline_name: "ingestion_events".to_string(),
            publisher: None,
            offset_tracker: Some(offset_tracker.clone()),
        };
        let deduplicator = TimestampDeduplicator::new(dedup_config, store_manager);

        Ok(Self {
            config,
            producer,
            duplicate_producer,
            deduplicator,
            offset_tracker: Some(offset_tracker),
        })
    }

    async fn process_partition_batch(
        &self,
        partition: Partition,
        messages: Vec<&KafkaMessage<CapturedEvent>>,
    ) -> Result<()> {
        let batch_start = Instant::now();
        let message_count = messages.len();

        // Parse events in parallel (CPU-bound work - good use of rayon)
        // Use block_in_place to avoid blocking the async runtime thread pool
        let parsing_start = Instant::now();
        let parsed_events: Vec<Result<RawEvent>> = tokio::task::block_in_place(|| {
            messages
                .par_iter()
                .map(|msg| IngestionEventParser::parse(msg))
                .collect()
        });
        let parsing_duration = parsing_start.elapsed();
        metrics::histogram!(EVENT_PARSING_DURATION_MS).record(parsing_duration.as_millis() as f64);

        // Collect successful parses and extract metadata sequentially
        // This avoids cloning the entire message - we just copy the small pieces we need
        let successful_count = parsed_events.iter().filter(|r| r.is_ok()).count();
        let mut events_owned: Vec<RawEvent> = Vec::with_capacity(successful_count);
        let mut payloads = Vec::with_capacity(successful_count);
        let mut headers_vec = Vec::with_capacity(successful_count);
        let mut keys = Vec::with_capacity(successful_count);
        let mut event_indices: Vec<usize> = Vec::with_capacity(successful_count);

        for (idx, msg) in messages.iter().enumerate() {
            if let Ok(event) = &parsed_events[idx] {
                event_indices.push(events_owned.len());
                events_owned.push(RawEvent {
                    uuid: event.uuid,
                    event: event.event.clone(),
                    distinct_id: event.distinct_id.clone(),
                    token: event.token.clone(),
                    timestamp: event.timestamp.clone(),
                    properties: event.properties.clone(),
                    ..Default::default()
                });

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
                error!("Failed to parse event: {e:#}");
            }
        }

        if events_owned.is_empty() {
            return Ok(());
        }

        // Deduplicate the batch for this partition using TimestampDeduplicator
        let event_refs: Vec<&RawEvent> = events_owned.iter().collect();
        let dedup_results = self
            .deduplicator
            .deduplicate_batch(partition.topic(), partition.partition_number(), event_refs)
            .await?;

        // Create metrics helper for similarity metrics
        let metrics =
            MetricsHelper::with_partition(partition.topic(), partition.partition_number());

        // Process results: emit metrics and collect publish futures
        // We batch all Kafka sends and execute them concurrently for better throughput
        let mut unique_event_futures = Vec::new();
        let mut duplicate_event_futures = Vec::new();

        for (idx, result) in dedup_results.iter().enumerate() {
            let raw_event = &events_owned[idx];
            let payload = &payloads[idx];
            let headers = &headers_vec[idx];
            let key = &keys[idx];

            // Emit similarity metrics for duplicates
            Self::emit_similarity_metrics(result, raw_event, &metrics);

            // Collect duplicate event publish futures
            if let Some(ref duplicate_producer) = self.duplicate_producer {
                if self.should_publish_duplicate_event(result) {
                    if let Some(original_event) = result.get_original_event() {
                        let duplicate_event = DuplicateEvent::from_result(original_event, result);
                        if let Some(event) = duplicate_event {
                            duplicate_event_futures.push(
                                DuplicateEventProducerWrapper::send_static(
                                    duplicate_producer.producer.clone(),
                                    duplicate_producer.topic.clone(),
                                    event,
                                    key.clone(),
                                    self.config.producer_send_timeout,
                                    partition.topic().to_string(),
                                    partition.partition_number(),
                                ),
                            );
                        }
                    }
                }
            }

            // Collect unique event publish futures
            if !result.is_duplicate() {
                if let Some(ref producer) = self.producer {
                    if let Some(ref output_topic) = self.config.output_topic {
                        unique_event_futures.push(Self::publish_event_static(
                            producer.clone(),
                            payload.clone(),
                            headers.clone(),
                            key.clone(),
                            output_topic.clone(),
                            self.config.producer_send_timeout,
                        ));
                    }
                }
            }
        }

        // Execute all duplicate event publishes concurrently (fire-and-forget, errors logged inside)
        if !duplicate_event_futures.is_empty() {
            join_all(duplicate_event_futures).await;
        }

        // Execute all unique event publishes concurrently
        if !unique_event_futures.is_empty() {
            let results = join_all(unique_event_futures).await;
            // Track max producer offset and check for errors
            let mut max_producer_offset: Option<i64> = None;
            for result in results {
                match result {
                    Ok(offset) => {
                        max_producer_offset =
                            Some(max_producer_offset.map_or(offset, |current| current.max(offset)));
                    }
                    Err(e) => {
                        error!("Failed to publish non-duplicate event: {e:#}");
                        return Err(e);
                    }
                }
            }
            // Record the max producer offset for this input partition (for checkpointing)
            if let (Some(ref tracker), Some(offset)) = (&self.offset_tracker, max_producer_offset) {
                tracker.mark_produced(&partition, offset);
            }
        }

        // Record total partition batch processing time
        let batch_duration = batch_start.elapsed();
        metrics::histogram!(PARTITION_BATCH_PROCESSING_DURATION_MS)
            .record(batch_duration.as_millis() as f64);

        // Warn on slow partition batches (>= 2 seconds indicates potential issues)
        if batch_duration >= Duration::from_secs(2) {
            warn!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                message_count = message_count,
                duration_ms = batch_duration.as_millis(),
                parsing_duration_ms = parsing_duration.as_millis(),
                "Slow partition batch processing"
            );
        }

        Ok(())
    }

    /// Determine if an event should be published to the duplicate events topic
    fn should_publish_duplicate_event(&self, result: &DeduplicationResult<RawEvent>) -> bool {
        matches!(
            result,
            DeduplicationResult::ConfirmedDuplicate(_) | DeduplicationResult::PotentialDuplicate(_)
        )
    }

    /// Publish event to output topic (static version for concurrent execution)
    ///
    /// Takes owned values so it can be collected into a Vec of futures and executed with join_all.
    /// Returns the producer offset on success, which is used for checkpoint tracking.
    async fn publish_event_static(
        producer: Arc<FutureProducer<KafkaContext>>,
        payload: Vec<u8>,
        headers: Option<rdkafka::message::OwnedHeaders>,
        key: String,
        output_topic: String,
        timeout: Duration,
    ) -> Result<i64> {
        let mut record = FutureRecord::to(&output_topic).key(&key).payload(&payload);

        if let Some(ref h) = headers {
            record = record.headers(h.clone());
        }

        let send_start = Instant::now();
        let result = producer.send(record, Timeout::After(timeout)).await;
        let send_duration = send_start.elapsed();
        metrics::histogram!(KAFKA_PRODUCER_SEND_DURATION_MS)
            .record(send_duration.as_millis() as f64);

        match result {
            Ok((_partition, offset)) => {
                debug!(
                    "Successfully published non-duplicate event with key {} to {} at offset {}",
                    key, output_topic, offset
                );
                Ok(offset)
            }
            Err((e, _)) => {
                error!(
                    "Failed to publish event with key {} to {}: {e:#}",
                    key, output_topic
                );
                Err(anyhow::Error::from(e).context(format!(
                    "Failed to publish event with key '{}' to topic '{}'",
                    key, output_topic
                )))
            }
        }
    }

    /// Emit similarity-related metrics for duplicate detection.
    ///
    /// These metrics track how similar duplicate events are to their originals,
    /// helping identify SDK bugs vs legitimate retries.
    fn emit_similarity_metrics(
        result: &DeduplicationResult<RawEvent>,
        raw_event: &RawEvent,
        metrics: &MetricsHelper,
    ) {
        let duplicate_info = match result {
            DeduplicationResult::ConfirmedDuplicate(info) => Some(info),
            DeduplicationResult::PotentialDuplicate(info) => Some(info),
            _ => None,
        };

        if let Some(info) = duplicate_info {
            if let Some(lib_info) = raw_event.extract_library_info() {
                metrics
                    .histogram(TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(info.unique_uuids_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(info.similarity.overall_score);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(info.similarity.different_field_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(info.similarity.different_property_count as f64);

                metrics
                    .histogram(TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                    .with_label("lib", &lib_info.name)
                    .record(info.similarity.properties_similarity);

                for (field_name, _, _) in &info.similarity.different_fields {
                    metrics
                        .counter(TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER)
                        .with_label("lib", &lib_info.name)
                        .with_label("field", &field_name.to_string())
                        .increment(1);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipelines::DuplicateReason;
    use crate::store::DeduplicationStoreConfig;
    use crate::test_utils::create_test_tracker;
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
            fail_open: false,
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
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        // Create a batch of new events
        let events = [
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
            .deduplicator
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
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        // First batch - all new
        let batch1 = [
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let results1 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert_eq!(results1.len(), 2);
        assert!(matches!(results1[0], DeduplicationResult::New));
        assert!(matches!(results1[1], DeduplicationResult::New));

        // Second batch - same events (timestamp duplicates)
        let batch2 = [
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let refs2: Vec<&RawEvent> = batch2.iter().collect();
        let results2 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, refs2)
            .await
            .unwrap();
        assert_eq!(results2.len(), 2);
        assert!(results2[0].is_duplicate());
        assert!(results2[1].is_duplicate());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_mixed_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        // First batch - establish baseline
        let batch1 = [create_test_raw_event(
            Some(uuid1),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results1 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert!(matches!(results1[0], DeduplicationResult::New));

        // Second batch - mix of new and duplicate
        let batch2 = [
            // Exact duplicate (timestamp)
            create_test_raw_event(Some(uuid1), "event1", "user1", "2024-01-01T00:00:00Z"),
            // New event
            create_test_raw_event(Some(uuid2), "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let results2 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();

        assert_eq!(results2.len(), 2);
        assert!(results2[0].is_duplicate()); // Timestamp duplicate
        assert!(matches!(results2[1], DeduplicationResult::New)); // New event
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_events_without_uuid() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        // First batch - events without UUIDs
        let batch1 = [
            create_test_raw_event(None, "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(None, "event2", "user2", "2024-01-01T00:00:01Z"),
        ];

        let results1 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();
        assert_eq!(results1.len(), 2);
        assert!(matches!(results1[0], DeduplicationResult::New));
        assert!(matches!(results1[1], DeduplicationResult::New));

        // Second batch - duplicate events (only timestamp-based dedup)
        let batch2 = [create_test_raw_event(
            None,
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results2 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();
        assert!(results2[0].is_duplicate());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_large_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

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
            .deduplicator
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
            .deduplicator
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
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        let uuid1 = Uuid::new_v4();

        // First event
        let batch1 = [create_test_raw_event(
            Some(uuid1),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch1.iter().collect())
            .await
            .unwrap();

        // Same event with different UUID
        let uuid2 = Uuid::new_v4();
        let batch2 = [create_test_raw_event(
            Some(uuid2),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let results2 = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch2.iter().collect())
            .await
            .unwrap();

        // Should be detected as timestamp duplicate with only UUID different
        assert!(matches!(
            &results2[0],
            DeduplicationResult::ConfirmedDuplicate(info) if info.reason == DuplicateReason::OnlyUuidDifferent
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_batch_deduplication_within_same_batch() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Pre-create store (as would happen during rebalance)
        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        let uuid = Uuid::new_v4();

        // Batch with duplicate events within the same batch
        let batch = [
            create_test_raw_event(Some(uuid), "event1", "user1", "2024-01-01T00:00:00Z"),
            create_test_raw_event(Some(uuid), "event1", "user1", "2024-01-01T00:00:00Z"),
        ];

        let results = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, batch.iter().collect())
            .await
            .unwrap();

        assert_eq!(results.len(), 2);
        // First should be new
        assert!(matches!(results[0], DeduplicationResult::New));
        // Second should be duplicate
        assert!(results[1].is_duplicate());
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_deduplicate_batch_gracefully_drops_when_store_missing() {
        // Test that deduplicate_batch returns Ok(vec![]) when the store doesn't exist.
        // This simulates the scenario where a partition was revoked and messages
        // arrive for it due to rdkafka buffering. Messages should be gracefully dropped.
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // NOTE: We intentionally do NOT pre-create a store here

        let processor =
            IngestionEventsBatchProcessor::new(config, store_manager.clone(), None, None).unwrap();

        // Create a batch of events
        let events = [create_test_raw_event(
            Some(Uuid::new_v4()),
            "event1",
            "user1",
            "2024-01-01T00:00:00Z",
        )];

        let event_refs: Vec<&RawEvent> = events.iter().collect();

        // deduplicate_batch should return Ok(vec![]) - graceful drop, not an error
        let result = processor
            .deduplicator
            .deduplicate_batch("test-topic", 0, event_refs)
            .await;

        assert!(
            result.is_ok(),
            "deduplicate_batch should return Ok when store doesn't exist (graceful drop)"
        );
        assert!(
            result.unwrap().is_empty(),
            "deduplicate_batch should return empty results when store doesn't exist"
        );
    }
}
