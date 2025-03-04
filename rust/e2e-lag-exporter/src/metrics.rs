use metrics::{describe_gauge, gauge};

// Metrics constants
pub const METRIC_CONSUMER_LAG: &str = "consumer_lag";
pub const METRIC_CONSUMER_TIMESTAMP: &str = "consumer_last_message_timestamp";

/// Register all metrics with descriptions
pub fn register_metrics() {
    describe_gauge!(
        METRIC_CONSUMER_LAG,
        "Number of messages behind for the consumer group"
    );
    describe_gauge!(
        METRIC_CONSUMER_TIMESTAMP,
        "Timestamp of the last message consumed by the consumer group"
    );
}

/// Record the consumer lag count metric
pub fn record_lag_count(topic: &str, partition: i32, consumergroup: &str, lag: i64) {
    let topic_owned = topic.to_string();
    let partition_str = format!("{}", partition);
    let consumergroup_owned = consumergroup.to_string();

    gauge!(METRIC_CONSUMER_LAG,
        "topic" => topic_owned,
        "partition" => partition_str,
        "consumergroup" => consumergroup_owned,
    )
    .set(lag as f64);
}

/// Record the consumer lag time metric in milliseconds
pub fn record_timestamp(topic: &str, partition: i32, consumergroup: &str, timestamp: i64) {
    let topic_owned = topic.to_string();
    let partition_str = format!("{}", partition);
    let consumergroup_owned = consumergroup.to_string();

    gauge!(METRIC_CONSUMER_TIMESTAMP,
        "topic" => topic_owned,
        "partition" => partition_str,
        "consumergroup" => consumergroup_owned,
    )
    .set(timestamp as f64);
}
