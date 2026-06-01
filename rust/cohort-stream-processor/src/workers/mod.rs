//! Stage 1 per-partition workers: the I/O + channel layer that drives the pure domain logic in
//! [`crate::stage1`].

pub mod event_path;
pub mod worker;

pub use event_path::{process_event, EventOutcome, SkipReason};
pub use worker::Stage1Worker;
