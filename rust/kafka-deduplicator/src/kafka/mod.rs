// Stateful Kafka module - coordinates Kafka consumption with external state systems
pub mod batch_consumer;
pub mod batch_context;
pub mod batch_message;
pub mod config;
pub mod message;
pub mod metrics_consts;
pub mod rebalance_handler;
pub mod stateful_consumer;
pub mod stateful_context;
pub mod tracker;
pub mod types;

// used in "mod tests" and tests/ directory (integration tests)
// so not exported as `#[cfg(test)]`
pub mod test_utils;

// Public API - what users of the kafka library should use
pub use config::ConsumerConfigBuilder;
pub use message::{AckableMessage, MessageProcessor};
pub use rebalance_handler::RebalanceHandler;
pub use stateful_consumer::StatefulKafkaConsumer;
pub use stateful_context::StatefulConsumerContext;
pub use tracker::{InFlightTracker, MessageHandle};
