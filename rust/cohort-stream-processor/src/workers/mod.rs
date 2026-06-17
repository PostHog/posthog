//! Stage 1 per-partition workers: the I/O + channel layer that drives the pure domain logic in
//! [`crate::stage1`].

pub mod cascade_path;
pub mod event_path;
pub mod merge_gc;
pub mod merge_path;
pub mod stage2_path;
pub mod sweep_callback;
pub mod worker;

pub use event_path::{process_event, EventOutcome, SkipReason};
pub use merge_gc::{handle_merge_gc, MergeGcCursor};
pub use merge_path::{
    CascadeConfig, MergeWorkerDeps, TransferRetryPolicy, DEFAULT_MERGE_GC_SCAN_LIMIT,
};
pub use stage2_path::compose_stage2;
pub use worker::Stage1Worker;
