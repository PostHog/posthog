use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "USAGE_INGESTION_GRPC_ADDRESS", default = "0.0.0.0:7143")]
    pub grpc_address: String,
    #[envconfig(from = "USAGE_INGESTION_METRICS_ADDRESS", default = "0.0.0.0:7144")]
    pub metrics_address: String,
    #[envconfig(from = "USAGE_INGESTION_TEAM_ORGANIZATION_REDIS_URL")]
    pub team_organization_redis_url: String,
    #[envconfig(from = "USAGE_INGESTION_DATABASE_URL")]
    pub database_url: String,
    #[envconfig(from = "OBJECT_STORAGE_BUCKET")]
    pub object_storage_bucket: String,
    #[envconfig(from = "OBJECT_STORAGE_REGION", default = "us-east-1")]
    pub object_storage_region: String,
    #[envconfig(from = "OBJECT_STORAGE_ENDPOINT")]
    pub object_storage_endpoint: Option<String>,
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
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_batch_size == 0 || self.max_batch_size > 5_000 {
            return Err("USAGE_INGESTION_MAX_BATCH_SIZE must be between 1 and 5000".to_string());
        }
        Ok(())
    }
}
