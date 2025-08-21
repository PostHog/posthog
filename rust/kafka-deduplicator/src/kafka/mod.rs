// Stateful Kafka module - coordinates Kafka consumption with external state systems
pub mod config;
pub mod message;
pub mod rebalance_handler;
pub mod stateful_consumer;
pub mod stateful_context;
pub mod tracker;

#[cfg(test)]
pub mod test_utils;

// Public API - what users of the kafka library should use
pub use config::ConsumerConfigBuilder;
pub use message::{AckableMessage, MessageProcessor};
pub use rebalance_handler::RebalanceHandler;
pub use stateful_consumer::StatefulKafkaConsumer;
pub use stateful_context::StatefulConsumerContext;
pub use tracker::{InFlightTracker, MessageHandle};
