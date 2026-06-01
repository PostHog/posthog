//! Kafka consumers — one rdkafka `StreamConsumer` per input topic. The `events` submodule covers
//! `cohort_stream_events`, the hot path.

pub mod events;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
