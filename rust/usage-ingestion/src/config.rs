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
    /// Empty keeps the Redis projection disabled, which is the safe default for existing deployments.
    #[envconfig(from = "USAGE_INGESTION_REDIS_URL", default = "")]
    pub redis_url: String,
    #[envconfig(from = "USAGE_INGESTION_REDIS_FLUSH_INTERVAL_SECONDS", default = "15")]
    pub redis_flush_interval_seconds: u64,
    // Overridable so a test environment can use the suffixed topic its Kafka engine table reads.
    #[envconfig(
        from = "USAGE_INGESTION_TOPIC",
        default = "clickhouse_billing_usage_records"
    )]
    pub topic: String,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        if self.redis_flush_interval_seconds == 0 {
            return Err(
                "USAGE_INGESTION_REDIS_FLUSH_INTERVAL_SECONDS must be positive".to_string(),
            );
        }
        Ok(())
    }
}
