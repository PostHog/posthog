//! Generic timestamp-based deduplicator.
//!
//! This module provides a unified `TimestampDeduplicator<E>` that can deduplicate
//! any event type that implements the required traits. This eliminates code
//! duplication between the ingestion_events and clickhouse_events pipelines.
//!
//! # Example
//!
//! ```ignore
//! // For ingestion events with publishing:
//! let dedup = TimestampDeduplicator::<RawEvent>::builder()
//!     .store_manager(store_manager)
//!     .pipeline_name("ingestion_events")
//!     .publisher(Some(publisher))
//!     .build();
//!
//! // For clickhouse events without publishing:
//! let dedup = TimestampDeduplicator::<ClickHouseEvent>::builder()
//!     .store_manager(store_manager)
//!     .pipeline_name("clickhouse_events")
//!     .build();
//! ```

use std::collections::HashMap;
use std::marker::PhantomData;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::Result;
use common_kafka::kafka_producer::KafkaContext;
use rdkafka::producer::FutureProducer;

use crate::kafka::offset_tracker::OffsetTracker;
use crate::metrics_const::PARTITION_BATCH_PROCESSING_DURATION_MS;
use crate::pipelines::processor::{
    batch_read_timestamp_records, batch_write_timestamp_records, emit_deduplication_result_metrics,
    get_result_labels, get_store_or_drop, DeduplicationResult, DuplicateInfo, DuplicateReason,
    StoreResult,
};
use crate::pipelines::traits::{DeduplicationKeyExtractor, DeduplicationMetadata};
use crate::pipelines::EnrichedEvent;
use crate::store::DeduplicationStore;
use crate::store_manager::StoreManager;

/// Trait for events that can be deduplicated using timestamp-based strategy.
///
/// This combines all the requirements for an event type to be used with
/// `TimestampDeduplicator`.
pub trait DeduplicatableEvent: DeduplicationKeyExtractor + Send + Sync + Sized {
    /// The metadata type used to track duplicates for this event type.
    type Metadata: DeduplicationMetadata<Self> + Send + Sync;

    /// Check if this event has the same UUID as seen in metadata.
    ///
    /// This is used to distinguish retries (same UUID) from SDK bugs (different UUID).
    fn has_same_uuid(&self, metadata: &Self::Metadata) -> bool;
}

/// Publisher configuration for optional event publishing.
#[derive(Clone)]
pub struct PublisherConfig {
    pub producer: Arc<FutureProducer<KafkaContext>>,
    pub output_topic: String,
    pub send_timeout: Duration,
}

/// Configuration for the timestamp deduplicator.
#[derive(Clone)]
pub struct TimestampDeduplicatorConfig {
    /// Name of this pipeline (for metrics)
    pub pipeline_name: String,
    /// Optional publisher for non-duplicate events
    pub publisher: Option<PublisherConfig>,
    /// Optional offset tracker for checkpointing
    pub offset_tracker: Option<Arc<OffsetTracker>>,
}

/// Generic timestamp-based deduplicator.
///
/// This struct provides the core deduplication logic that works with any event
/// type implementing `DeduplicatableEvent`. The actual batch processing
/// (organizing by partition, handling Kafka messages) is left to the caller.
pub struct TimestampDeduplicator<E: DeduplicatableEvent> {
    config: TimestampDeduplicatorConfig,
    store_manager: Arc<StoreManager>,
    _phantom: PhantomData<E>,
}

impl<E: DeduplicatableEvent> TimestampDeduplicator<E> {
    /// Create a new timestamp deduplicator.
    pub fn new(config: TimestampDeduplicatorConfig, store_manager: Arc<StoreManager>) -> Self {
        Self {
            config,
            store_manager,
            _phantom: PhantomData,
        }
    }

    /// Get the pipeline name for metrics.
    pub fn pipeline_name(&self) -> &str {
        &self.config.pipeline_name
    }

    /// Get the store manager.
    pub fn store_manager(&self) -> &Arc<StoreManager> {
        &self.store_manager
    }

    /// Get the publisher config if configured.
    pub fn publisher(&self) -> Option<&PublisherConfig> {
        self.config.publisher.as_ref()
    }

    /// Get the offset tracker if configured.
    pub fn offset_tracker(&self) -> Option<&Arc<OffsetTracker>> {
        self.config.offset_tracker.as_ref()
    }

    /// Deduplicate a batch of events for a single partition.
    ///
    /// This is the core deduplication logic that:
    /// 1. Extracts dedup keys from events
    /// 2. Batch reads existing metadata from RocksDB
    /// 3. Checks for duplicates (including within-batch)
    /// 4. Updates metadata and batch writes back to RocksDB
    /// 5. Emits metrics
    ///
    /// Returns the deduplication results for each event, or an empty vec if
    /// the store was not found (partition revoked during rebalance).
    pub async fn deduplicate_batch(
        &self,
        topic: &str,
        partition: i32,
        events: Vec<&E>,
    ) -> Result<Vec<DeduplicationResult<E>>> {
        let batch_start = Instant::now();

        // Get the store for this partition (gracefully drops if not found)
        let store = match get_store_or_drop(&self.store_manager, topic, partition, events.len())? {
            StoreResult::Found(store) => store,
            StoreResult::NotFound => return Ok(vec![]),
        };

        // Run deduplication logic
        let results = self.deduplicate_events_internal(&store, &events)?;

        // Emit metrics for each result
        for result in &results {
            emit_deduplication_result_metrics(
                topic,
                partition,
                &self.config.pipeline_name,
                get_result_labels(result),
            );
        }

        // Record batch processing time
        let batch_duration = batch_start.elapsed();
        metrics::histogram!(PARTITION_BATCH_PROCESSING_DURATION_MS)
            .record(batch_duration.as_millis() as f64);

        Ok(results)
    }

    /// Internal deduplication logic operating on the store.
    fn deduplicate_events_internal(
        &self,
        store: &DeduplicationStore,
        events: &[&E],
    ) -> Result<Vec<DeduplicationResult<E>>> {
        // Step 1: Extract dedup keys
        let enriched_events: Vec<EnrichedEvent<E>> = events
            .iter()
            .map(|event| EnrichedEvent {
                dedup_key_bytes: event.extract_dedup_key(),
                event: *event,
            })
            .collect();

        // Step 2: Batch read from RocksDB
        let keys_refs: Vec<&[u8]> = enriched_events
            .iter()
            .map(|e| e.dedup_key_bytes.as_slice())
            .collect();
        let existing_records = batch_read_timestamp_records(store, keys_refs)?;

        // Step 3: Process results and prepare writes
        let event_count = enriched_events.len();
        let mut batch_cache: HashMap<Vec<u8>, Vec<u8>> = HashMap::with_capacity(event_count);
        let mut writes: Vec<(Vec<u8>, Vec<u8>)> = Vec::with_capacity(event_count);
        let mut dedup_results: Vec<DeduplicationResult<E>> = Vec::with_capacity(event_count);

        for (idx, enriched) in enriched_events.iter().enumerate() {
            // Check RocksDB first, then batch cache for within-batch duplicates
            let existing_bytes: Option<&[u8]> = existing_records[idx].as_deref().or_else(|| {
                batch_cache
                    .get(&enriched.dedup_key_bytes)
                    .map(|v| v.as_slice())
            });

            let (result, metadata) = self.check_duplicate(existing_bytes, enriched.event)?;

            // Serialize and prepare write
            let value = metadata.to_bytes()?;
            writes.push((enriched.dedup_key_bytes.clone(), value.clone()));
            batch_cache.insert(enriched.dedup_key_bytes.clone(), value);

            dedup_results.push(result);
        }

        // Step 4: Batch write to RocksDB
        batch_write_timestamp_records(store, &writes)?;

        Ok(dedup_results)
    }

    /// Check if an event is a duplicate based on existing metadata.
    ///
    /// Returns the deduplication result and the updated metadata.
    /// The result includes similarity information and the original event for duplicates.
    fn check_duplicate(
        &self,
        existing_bytes: Option<&[u8]>,
        event: &E,
    ) -> Result<(DeduplicationResult<E>, E::Metadata)> {
        match existing_bytes {
            Some(bytes) => {
                let mut metadata = E::Metadata::from_bytes(bytes)?;

                // Calculate similarity with the original event
                let similarity = metadata.calculate_similarity(event)?;
                let original_event = metadata.get_original_event()?;
                let is_same_uuid = event.has_same_uuid(&metadata);

                // Update metadata to track this duplicate
                metadata.update_duplicate(event);

                // Get unique UUIDs count after update
                let unique_uuids_count = metadata.unique_uuids_count();

                // Determine the duplicate reason based on similarity and UUID
                let reason = if similarity.overall_score == 1.0 {
                    DuplicateReason::SameEvent
                } else if is_same_uuid {
                    DuplicateReason::SameUuid
                } else if similarity.different_fields.len() == 1
                    && similarity.different_fields[0].0 == "uuid"
                {
                    DuplicateReason::OnlyUuidDifferent
                } else {
                    // Different content - this is a potential duplicate, not confirmed
                    return Ok((
                        DeduplicationResult::PotentialDuplicate(DuplicateInfo {
                            reason: DuplicateReason::ContentDiffers,
                            similarity,
                            original_event,
                            unique_uuids_count,
                        }),
                        metadata,
                    ));
                };

                Ok((
                    DeduplicationResult::ConfirmedDuplicate(DuplicateInfo {
                        reason,
                        similarity,
                        original_event,
                        unique_uuids_count,
                    }),
                    metadata,
                ))
            }
            None => {
                let metadata = E::Metadata::new(event);
                Ok((DeduplicationResult::New, metadata))
            }
        }
    }
}

// Unit tests for TimestampDeduplicator use concrete event types
// See clickhouse_events/processor.rs and ingestion_events/processor.rs for integration tests
