// Kafka module - batch consumption with rebalance handling
pub mod batch_consumer;
pub mod batch_context;
pub mod batch_message;
pub mod config;
pub mod metrics_consts;
pub mod rebalance_handler;
pub mod types;

// Used in "mod tests" and tests/ directory (integration tests)
pub mod test_utils;

// Public API
pub use config::ConsumerConfigBuilder;
pub use rebalance_handler::RebalanceHandler;
