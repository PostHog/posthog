// Kafka module - batch consumption with rebalance handling
pub mod batch_consumer;
pub mod batch_context;
pub mod batch_message;
pub mod config;
pub mod metrics_consts;
pub mod offset_tracker;
pub mod partition_router;
pub mod partition_worker;
pub mod rebalance_handler;
pub mod routing_processor;
pub mod types;

// Used in "mod tests" and tests/ directory (integration tests)
pub mod test_utils;

// Public API
pub use config::ConsumerConfigBuilder;
pub use offset_tracker::{OffsetTracker, OffsetTrackerError};
pub use partition_router::{PartitionRouter, PartitionRouterConfig};
pub use partition_worker::{PartitionBatch, PartitionWorker, PartitionWorkerConfig};
pub use rebalance_handler::RebalanceHandler;
pub use routing_processor::RoutingProcessor;
