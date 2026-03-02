//! Traits for pipeline implementations.
//!
//! This module contains the core trait definitions that pipelines must implement:
//! - [`DeduplicationKeyExtractor`] - How to extract dedup keys from events
//! - [`EventParser`] - How to parse wire format to domain events
//! - [`DeduplicationMetadata`] - How to manage metadata for deduplication
//! - [`FailOpenProcessor`] - How to handle fail-open mode (bypass deduplication)

use anyhow::Result;
use axum::async_trait;

use crate::kafka::batch_message::KafkaMessage;
use crate::pipelines::EventSimilarity;

/// Trait for extracting deduplication keys from events.
///
/// This trait allows different event types to define how their
/// deduplication key is computed, enabling the deduplicator to
/// work with multiple event schemas.
pub trait DeduplicationKeyExtractor {
    /// Extract a deduplication key as bytes.
    ///
    /// The returned bytes are used as the key in RocksDB for
    /// duplicate detection. Events with the same key are considered
    /// potential duplicates.
    fn extract_dedup_key(&self) -> Vec<u8>;
}

/// Trait for parsing Kafka messages into domain events.
///
/// This trait allows different pipelines to define how their
/// wire format (what comes from Kafka) is transformed into
/// the domain event type used for deduplication.
///
/// # Type Parameters
///
/// * `W` - The wire format type deserialized from Kafka (e.g., `CapturedEvent`)
/// * `E` - The domain event type used for deduplication (e.g., `RawEvent`)
pub trait EventParser<W, E> {
    /// Parse a Kafka message into a domain event.
    ///
    /// This method transforms the wire format into the domain event type,
    /// applying any necessary validation, normalization, or enrichment.
    fn parse(message: &KafkaMessage<W>) -> Result<E>;
}

/// Trait for managing deduplication metadata.
///
/// This trait defines how metadata is created, updated, and queried
/// for deduplication purposes. Different pipelines can implement
/// their own metadata storage strategies.
///
/// # Type Parameters
///
/// * `E` - The domain event type (e.g., `RawEvent`)
pub trait DeduplicationMetadata<E>: Sized {
    /// Create new metadata for the first occurrence of an event.
    fn new(event: &E) -> Self;

    /// Update metadata when a duplicate is detected.
    fn update_duplicate(&mut self, new_event: &E);

    /// Get the original event that was stored.
    fn get_original_event(&self) -> Result<E>;

    /// Calculate similarity between the original event and a new event.
    fn calculate_similarity(&self, new_event: &E) -> Result<EventSimilarity>;

    /// Get the number of unique UUIDs seen for this dedup key.
    fn unique_uuids_count(&self) -> usize;

    /// Serialize metadata to bytes for storage.
    fn to_bytes(&self) -> Result<Vec<u8>>;

    /// Deserialize metadata from bytes.
    fn from_bytes(bytes: &[u8]) -> Result<Self>;
}

/// Trait for processors that support fail-open mode.
///
/// When fail-open is active, the processor bypasses all deduplication store
/// operations and forwards events directly. This serves as an emergency kill
/// switch when the deduplication store is causing issues.
///
/// All pipeline processors must implement this trait to ensure fail-open
/// behavior is handled explicitly for every pipeline. Each processor's
/// `BatchConsumerProcessor::process_batch()` should call this when its
/// config has fail-open enabled.
#[async_trait]
pub trait FailOpenProcessor<T: Send>: Send + Sync {
    /// Process a batch of messages in fail-open mode, bypassing deduplication.
    ///
    /// For pipelines that produce to an output topic, this should parse events
    /// and forward them all without dedup checks. For read-only pipelines,
    /// this should skip processing entirely.
    async fn process_batch_fail_open(&self, messages: Vec<KafkaMessage<T>>) -> Result<()>;
}
