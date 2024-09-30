pub mod config;
pub mod kafka_consumer;
pub mod kafka_messages;
pub mod kafka_producer;
pub mod test;

pub const APP_METRICS_TOPIC: &str = "clickhouse_app_metrics";
pub const APP_METRICS2_TOPIC: &str = "clickhouse_app_metrics2";
