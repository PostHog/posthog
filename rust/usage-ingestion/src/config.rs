use std::time::Duration;

use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "USAGE_INGESTION_GRPC_ADDRESS", default = "0.0.0.0:7143")]
    pub grpc_address: String,
    #[envconfig(from = "USAGE_INGESTION_METRICS_ADDRESS", default = "0.0.0.0:7144")]
    pub metrics_address: String,
    #[envconfig(from = "USAGE_INGESTION_DATABASE_URL")]
    pub database_url: String,
    #[envconfig(from = "KAFKA_HOSTS", default = "localhost:9092")]
    pub kafka_hosts: String,
    #[envconfig(from = "KAFKA_TLS", default = "false")]
    pub kafka_tls: bool,
    #[envconfig(from = "USAGE_INGESTION_MAX_BATCH_SIZE", default = "500")]
    pub max_batch_size: usize,
    // Overridable so a test environment can use the suffixed topic its Kafka engine table reads.
    #[envconfig(
        from = "USAGE_INGESTION_TOPIC",
        default = "clickhouse_billing_usage_records"
    )]
    pub topic: String,
    /// Maximum age of a gRPC connection in seconds before the server sends GOAWAY.
    /// Producers reconnect transparently, which restaggers them across the pods.
    /// 0 = disabled (connections live indefinitely).
    /// Shorter than personhog's 300 because a producer holds one connection and this fleet
    /// runs near its CPU request when the load lands unevenly.
    #[envconfig(from = "USAGE_INGESTION_GRPC_MAX_CONNECTION_AGE_SECS", default = "60")]
    pub grpc_max_connection_age_secs: u64,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        // A few seconds would make every producer spend its time reconnecting.
        if self.grpc_max_connection_age_secs > 0 && self.grpc_max_connection_age_secs < 10 {
            return Err(
                "USAGE_INGESTION_GRPC_MAX_CONNECTION_AGE_SECS must be 0 or at least 10".to_string(),
            );
        }
        Ok(())
    }

    pub fn grpc_max_connection_age(&self) -> Option<Duration> {
        if self.grpc_max_connection_age_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_max_connection_age_secs))
        }
    }
}
