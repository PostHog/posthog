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
