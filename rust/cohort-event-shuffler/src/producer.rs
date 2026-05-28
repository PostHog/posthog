//! Kafka producer for `cohort_stream_events` (TDD §2.2, §4.3).
//!
//! Implemented in PR 1.1: a `FutureProducer` that re-publishes each forwarded event
//! keyed by `hash(team_id, person_id)`, so `cohort-stream-processor`'s Stage 1 consumes
//! it with per-partition state affinity (the `rust/kafka-deduplicator` partition model).
