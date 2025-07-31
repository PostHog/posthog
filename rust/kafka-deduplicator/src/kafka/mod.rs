// Generic Kafka module - can be extracted as independent library
pub mod config;
pub mod generic_consumer;
pub mod generic_context;
pub mod message;
pub mod rebalance_handler;
pub mod tracker;

#[cfg(test)]
pub mod test_utils;

// Public API - what users of the kafka library should use
pub use config::ConsumerConfig;
pub use generic_consumer::GenericKafkaConsumer;
pub use generic_context::GenericConsumerContext;
pub use message::{AckableMessage, MessageProcessor};  
pub use rebalance_handler::RebalanceHandler;
pub use tracker::{InFlightTracker, MessageHandle};