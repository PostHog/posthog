//! Kafka deduplicator service.
//!
//! ## Error logging (anyhow)
//!
//! When logging `anyhow::Error` or other error types that implement `std::error::Error` with
//! a cause chain, use formats that include the full chain so root causes are visible in logs:
//!
//! - **Inline format:** `{e:#}` — full chain on one line (`outer: middle: root cause`).
//! - **Structured field:** `error = ?e` — full chain with `Caused by:` sections (Debug).
//!
//! Avoid `{}` / `%e` (Display) for errors — they only show the top-level message and hide the chain.
//!
//! When constructing errors, use `.context()` / `.with_context()` so the original error remains
//! the source. Avoid `anyhow!("...{e}")` — that formats the error into a string and drops the chain.

pub mod checkpoint;
pub mod checkpoint_manager;
pub mod config;
pub mod kafka;
pub mod metrics;
pub mod metrics_const;
pub mod pipelines;
pub mod processor_rebalance_handler;
pub mod rebalance_tracker;
pub mod rocksdb;
pub mod service;
pub mod store;
pub mod store_manager;
pub mod test_utils;
pub mod utils;

// Re-export commonly used types for convenience
pub use config::PipelineType;
pub use pipelines::{DeduplicationKeyExtractor, DeduplicationMetadata, EventParser};
