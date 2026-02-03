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

mod dedup_result;
mod duplicate_event;
mod keys;
mod metadata;
mod parser;
mod processor;

pub use dedup_result::{DeduplicationResult, DeduplicationResultReason, DeduplicationType};
pub use duplicate_event::DuplicateEvent;
pub use parser::IngestionEventParser;
pub use processor::{
    DeduplicationConfig, DuplicateEventProducerWrapper, IngestionEventsBatchProcessor,
};
