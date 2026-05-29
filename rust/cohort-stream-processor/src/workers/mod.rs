//! Stage 1 per-partition workers (TDD §2.3, §4.1) — PR 1.6.
//!
//! The orchestration half of Stage 1: the I/O + channel layer that drives the pure domain logic in
//! [`crate::stage1`].
//!
//! - `event_path` — [`process_event`], the per-event read-modify-write (no Kafka; directly testable).
//! - `worker` — [`Stage1Worker`], the long-lived channel-drain task per partition.

pub mod event_path;
pub mod worker;

pub use event_path::{process_event, EventOutcome, SkipReason};
pub use worker::Stage1Worker;
