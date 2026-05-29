//! Kafka consumers — one rdkafka `StreamConsumer` per input topic (TDD §2.3).
//!
//! Each consumer deserializes its topic and emits a typed `ShuffleMessage`
//! ([`crate::partitions`]) to the partition router. Planned submodules (TDD §3):
//! - `events` — `cohort_stream_events`, the hot path (PR 1.7): the wire [`CohortStreamEvent`] plus
//!   the [`CohortStreamEventsConsumer`] that routes each event to its partition worker and commits
//!   processed offsets.
//! - `person_merges` — `KAFKA_PERSON_MERGE_EVENTS`; drives the Phase 1 drain on P_old's worker (PR 3.1)
//! - `merge_transfer` — `cohort_merge_state_transfer`; drives the Phase 2 apply on P_new's worker (PR 3.1)
//! - `cascade` — `cohort_cascade_events`, self-fed cascade input (PR 3.4)
//! - `seed_events` — `cohort_stream_seed_events`, cold-start backfill (PR 6.2)

pub mod events;

pub use events::{CohortStreamEvent, CohortStreamEventsConsumer, ConsumedEvent, EventDispatcher};
