//! ClickHouse events pipeline implementation.
//!
//! This module contains the deduplication logic for events from the
//! `clickhouse_events_json` Kafka topic (output of the ingestion pipeline).
//!
//! # Event Type
//!
//! - `ClickHouseEvent` - Events that have been processed by the ingestion
//!   pipeline and are ready to be written to ClickHouse
//!
//! # Deduplication Strategy
//!
//! This pipeline uses timestamp-based deduplication:
//! - Events are keyed by (timestamp, event_name, distinct_id, team_id)
//! - Duplicates are detected by matching these fields

mod keys;
mod metadata;
mod parser;
mod processor;
mod similarity;

use common_types::ClickHouseEvent;

pub use metadata::ClickHouseEventMetadata;
pub use parser::ClickHouseEventParser;
pub use processor::{ClickHouseEventsBatchProcessor, ClickHouseEventsConfig};

use crate::pipelines::timestamp_deduplicator::DeduplicatableEvent;

impl DeduplicatableEvent for ClickHouseEvent {
    type Metadata = ClickHouseEventMetadata;

    fn has_same_uuid(&self, metadata: &Self::Metadata) -> bool {
        metadata.is_same_uuid(self)
    }
}
