//! Ingestion events pipeline implementation.
//!
//! This module contains the deduplication logic specific to PostHog's
//! ingestion events (CapturedEvent/RawEvent from the capture service).
//!
//! # Event Types
//!
//! - `CapturedEvent` - Wire format from Kafka (from capture service)
//! - `RawEvent` - Domain format used for deduplication logic
//!
//! # Deduplication Strategy
//!
//! This pipeline uses timestamp-based deduplication:
//! - Events are keyed by (timestamp, event_name, distinct_id, token)
//! - Duplicates are detected by matching these fields
//! - Similarity scoring tracks how different duplicate events are

mod duplicate_event;
mod keys;
mod metadata;
mod parser;
mod processor;
mod similarity;

use common_types::RawEvent;

pub use duplicate_event::DuplicateEvent;
pub use metadata::{SerializableRawEvent, TimestampMetadata};
pub use parser::IngestionEventParser;
pub use processor::{
    DeduplicationConfig, DuplicateEventProducerWrapper, IngestionEventsBatchProcessor,
};

use crate::pipelines::timestamp_deduplicator::DeduplicatableEvent;

impl DeduplicatableEvent for RawEvent {
    type Metadata = TimestampMetadata;

    fn has_same_uuid(&self, metadata: &Self::Metadata) -> bool {
        match self.uuid {
            Some(uuid) => metadata.seen_uuids.contains(&uuid.to_string()),
            None => false, // No UUID means we can't confirm it's the same
        }
    }
}
