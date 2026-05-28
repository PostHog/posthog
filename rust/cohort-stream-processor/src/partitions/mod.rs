//! Partition-affined routing and per-partition workers (TDD §2.3, §2.5).
//!
//! Lifts the partition model from `rust/kafka-deduplicator` so that all state mutations
//! for a given `(team_id, person_id)` serialize through exactly one worker, with no
//! cross-worker coordination on the hot path. Planned submodules (TDD §3):
//! - `router` — partition-assignment routing, lifted from `kafka-deduplicator` `routing_processor.rs` (PR 1.5)
//! - `worker` — long-lived per-partition task (PR 1.6)
//! - `shuffle_message` — typed enum: `Event | PersonMergeDrain | MergeTransferApply | Cascade | Seed | Sweep` (PR 1.5)
//! - `offset_tracker` — per-key Kafka offset tracking for replay idempotence, extending `kafka-deduplicator` `offset_tracker.rs` (PR 1.5)
