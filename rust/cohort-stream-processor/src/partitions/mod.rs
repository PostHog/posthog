//! Partition-affined routing and per-partition workers (TDD §2.3, §2.5).
//!
//! Lifts the partition model from `rust/kafka-deduplicator` so that all state mutations for a
//! given `(team_id, person_id)` serialize through exactly one worker, with no cross-worker
//! coordination on the hot path (the §2.5 worker-affinity invariant). Submodules (TDD §3):
//! - `shuffle_message` — the typed unit of work the router dispatches (PR 1.5)
//! - `router` — partition → worker-channel routing, lifted from `kafka-deduplicator`
//!   `routing_processor.rs` + `partition_router.rs` (PR 1.5)
//! - `offset_tracker` — per-partition commit tracking plus the per-key replay primitive,
//!   lifted/extended from `kafka-deduplicator` `offset_tracker.rs` for replay idempotence (PR 1.5)
//!
//! The long-lived per-partition worker that owns the `Receiver` returned by
//! [`router::PartitionRouter::add_partition`] and runs the Stage 1 processing loop lives in
//! [`crate::workers`] (PR 1.6).

pub mod offset_tracker;
pub mod router;
pub mod shuffle_message;

pub use offset_tracker::{is_replay, OffsetTracker};
pub use router::{PartitionRouter, RouteError};
pub use shuffle_message::ShuffleMessage;
