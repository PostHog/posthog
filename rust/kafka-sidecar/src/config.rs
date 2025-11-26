use serde::Deserialize;
use std::env;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub grpc_port: u16,
    pub metrics_port: u16,
    pub kafka_hosts: String,
    pub kafka_producer_linger_ms: u32,
    pub kafka_producer_queue_mib: u32,
    pub kafka_message_timeout_ms: u32,
    pub kafka_compression_codec: String,
    pub kafka_tls: bool,
    pub kafka_producer_batch_size: u32,
    pub kafka_enable_idempotence: bool,
    pub kafka_max_in_flight: u32,
    pub kafka_retry_backoff_ms: u32,
    pub kafka_socket_timeout_ms: u32,
    pub kafka_metadata_max_age_ms: u32,
}

impl Config {
    pub fn from_env() -> Result<Self, env::VarError> {
        Ok(Config {
            grpc_port: env::var("GRPC_PORT")
                .unwrap_or_else(|_| "50051".to_string())
                .parse()
                .unwrap_or(50051),
            metrics_port: env::var("METRICS_PORT")
                .unwrap_or_else(|_| "9090".to_string())
                .parse()
                .unwrap_or(9090),
            kafka_hosts: env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string()),
            kafka_producer_linger_ms: env::var("KAFKA_PRODUCER_LINGER_MS")
                .unwrap_or_else(|_| "20".to_string())
                .parse()
                .unwrap_or(20),
            kafka_producer_queue_mib: env::var("KAFKA_PRODUCER_QUEUE_MIB")
                .unwrap_or_else(|_| "256".to_string())
                .parse()
                .unwrap_or(256),
            kafka_message_timeout_ms: env::var("KAFKA_MESSAGE_TIMEOUT_MS")
                .unwrap_or_else(|_| "30000".to_string())
                .parse()
                .unwrap_or(30000),
            kafka_compression_codec: env::var("KAFKA_COMPRESSION_CODEC")
                .unwrap_or_else(|_| "snappy".to_string()),
            kafka_tls: env::var("KAFKA_TLS")
                .unwrap_or_else(|_| "false".to_string())
                .parse()
                .unwrap_or(false),
            // New settings with defaults matching plugin-server
            kafka_producer_batch_size: env::var("KAFKA_PRODUCER_BATCH_SIZE")
                .unwrap_or_else(|_| "8388608".to_string()) // 8 MB
                .parse()
                .unwrap_or(8388608),
            kafka_enable_idempotence: env::var("KAFKA_ENABLE_IDEMPOTENCE")
                .unwrap_or_else(|_| "true".to_string())
                .parse()
                .unwrap_or(true),
            kafka_max_in_flight: env::var("KAFKA_MAX_IN_FLIGHT")
                .unwrap_or_else(|_| "5".to_string())
                .parse()
                .unwrap_or(5),
            kafka_retry_backoff_ms: env::var("KAFKA_RETRY_BACKOFF_MS")
                .unwrap_or_else(|_| "500".to_string())
                .parse()
                .unwrap_or(500),
            kafka_socket_timeout_ms: env::var("KAFKA_SOCKET_TIMEOUT_MS")
                .unwrap_or_else(|_| "30000".to_string())
                .parse()
                .unwrap_or(30000),
            kafka_metadata_max_age_ms: env::var("KAFKA_METADATA_MAX_AGE_MS")
                .unwrap_or_else(|_| "30000".to_string())
                .parse()
                .unwrap_or(30000),
        })
    }

    pub fn to_kafka_config(&self) -> common_kafka::config::KafkaConfig {
        common_kafka::config::KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_producer_linger_ms: self.kafka_producer_linger_ms,
            kafka_producer_queue_mib: self.kafka_producer_queue_mib,
            kafka_message_timeout_ms: self.kafka_message_timeout_ms,
            kafka_compression_codec: self.kafka_compression_codec.clone(),
            kafka_tls: self.kafka_tls,
            kafka_producer_queue_messages: 100000,
            kafka_topic_metadata_refresh_interval_ms: Some(self.kafka_metadata_max_age_ms),
            kafka_producer_batch_size: Some(self.kafka_producer_batch_size),
            kafka_enable_idempotence: Some(self.kafka_enable_idempotence),
            kafka_max_in_flight: Some(self.kafka_max_in_flight),
            kafka_retry_backoff_ms: Some(self.kafka_retry_backoff_ms),
            kafka_socket_timeout_ms: Some(self.kafka_socket_timeout_ms),
            kafka_metadata_max_age_ms: Some(self.kafka_metadata_max_age_ms),
        }
    }
}
