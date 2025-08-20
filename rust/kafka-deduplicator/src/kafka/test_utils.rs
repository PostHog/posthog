use rdkafka::config::ClientConfig;
use rdkafka::consumer::BaseConsumer;
use std::sync::Arc;

use super::rebalance_handler::RebalanceHandler;
use super::stateful_context::StatefulConsumerContext;
use super::tracker::InFlightTracker;

/// Test utilities for kafka module tests
pub fn create_test_consumer<H: RebalanceHandler + 'static>(
    handler: Arc<H>,
) -> BaseConsumer<StatefulConsumerContext> {
    let tracker = Arc::new(InFlightTracker::new());
    let context = StatefulConsumerContext::new(handler, tracker);

    let consumer: BaseConsumer<StatefulConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", "localhost:9092")
        .set("group.id", "test-group")
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create_with_context(context)
        .expect("Consumer creation failed");

    consumer
}
