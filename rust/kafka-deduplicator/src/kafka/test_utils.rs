use rdkafka::config::ClientConfig;
use rdkafka::consumer::BaseConsumer;
use std::sync::Arc;

use super::generic_context::GenericConsumerContext;
use super::rebalance_handler::RebalanceHandler;

/// Test utilities for kafka module tests
pub fn create_test_consumer<H: RebalanceHandler + 'static>(
    handler: Arc<H>,
) -> BaseConsumer<GenericConsumerContext> {
    let context = GenericConsumerContext::new(handler);
    
    let consumer: BaseConsumer<GenericConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", "localhost:9092")
        .set("group.id", "test-group")
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create_with_context(context)
        .expect("Consumer creation failed");
    
    consumer
}