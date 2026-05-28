//! Kafka consumer for `clickhouse_events_json` (TDD §2.2).
//!
//! Implemented in PR 1.1: an rdkafka `StreamConsumer` that reads the live event stream,
//! drops events without a `person_id`, and skips events for teams with zero
//! realtime-supported filters — mirroring `cdp-precalculated-filters.consumer.ts`
//! (`:187-194`, `:219-222`). Matching events are handed to [`crate::producer`] for
//! re-keying.
