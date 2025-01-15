use chrono::Duration;
use cyclotron_core::{PoolConfig, WorkerConfig};
use envconfig::Envconfig;
use uuid::Uuid;

use common_kafka::config::KafkaConfig;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3304")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/cyclotron")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub pg_max_connections: u32,

    #[envconfig(default = "1")]
    pub pg_min_connections: u32,

    #[envconfig(default = "30")]
    pub pg_acquire_timeout_seconds: u64,

    #[envconfig(default = "300")]
    pub pg_max_lifetime_seconds: u64,

    #[envconfig(default = "60")]
    pub pg_idle_timeout_seconds: u64,

    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,

    #[envconfig(default = "default_worker_id")]
    pub worker_id: String,

    #[envconfig(default = "default")]
    pub shard_id: String,

    #[envconfig(default = "1")]
    pub job_poll_interval_seconds: i64,

    #[envconfig(default = "1000")]
    pub concurrent_requests_limit: u32,

    #[envconfig(default = "30")]
    pub fetch_timeout_seconds: i64,

    #[envconfig(default = "10")]
    pub max_retry_attempts: u32,

    #[envconfig(default = "fetch")]
    pub queue_served: String,

    #[envconfig(default = "1000")]
    pub batch_size: usize,

    #[envconfig(default = "1000000")]
    pub max_response_bytes: usize,

    #[envconfig(default = "4000")]
    pub retry_backoff_base_ms: i64,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    // Worker tuning params
    #[envconfig(default = "5")]
    pub heartbeat_window_seconds: u64,

    #[envconfig(default = "500")]
    pub linger_time_ms: u64,

    #[envconfig(default = "100")]
    pub max_updates_buffered: usize,

    #[envconfig(default = "10000000")]
    pub max_bytes_buffered: usize,

    #[envconfig(default = "10")]
    pub flush_loop_interval_ms: u64,
}

#[allow(dead_code)]
fn default_worker_id() -> String {
    Uuid::now_v7().to_string()
}

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub host: String,
    pub port: u16,
    pub worker_id: String,
    pub shard_id: String,
    pub job_poll_interval: Duration, // How long we wait to poll for new jobs, when we're at capacity or find no new jobs
    pub concurrent_requests_limit: u32,
    pub fetch_timeout: Duration,
    pub max_retry_attempts: u32,
    pub queue_served: String,
    pub batch_size: usize,
    pub max_response_bytes: usize,
    pub retry_backoff_base: Duration, // Job retry backoff times are this * attempt count
    pub allow_internal_ips: bool,
}

impl Config {
    pub fn to_components(self) -> (AppConfig, PoolConfig, KafkaConfig, WorkerConfig) {
        let app_config = AppConfig {
            host: self.host,
            port: self.port,
            worker_id: self.worker_id,
            shard_id: self.shard_id,
            job_poll_interval: Duration::seconds(self.job_poll_interval_seconds),
            concurrent_requests_limit: self.concurrent_requests_limit,
            fetch_timeout: Duration::seconds(self.fetch_timeout_seconds),
            max_retry_attempts: self.max_retry_attempts,
            queue_served: self.queue_served,
            batch_size: self.batch_size,
            max_response_bytes: self.max_response_bytes,
            retry_backoff_base: Duration::milliseconds(self.retry_backoff_base_ms),
            allow_internal_ips: self.allow_internal_ips,
        };

        let pool_config = PoolConfig {
            db_url: self.database_url,
            max_connections: Some(self.pg_max_connections),
            min_connections: Some(self.pg_min_connections),
            acquire_timeout_seconds: Some(self.pg_acquire_timeout_seconds),
            max_lifetime_seconds: Some(self.pg_max_lifetime_seconds),
            idle_timeout_seconds: Some(self.pg_idle_timeout_seconds),
        };

        let worker_config = WorkerConfig {
            heartbeat_window_seconds: Some(self.heartbeat_window_seconds),
            linger_time_ms: Some(self.linger_time_ms),
            max_updates_buffered: Some(self.max_updates_buffered),
            max_bytes_buffered: Some(self.max_bytes_buffered),
            flush_loop_interval_ms: Some(self.flush_loop_interval_ms),
        };

        (app_config, pool_config, self.kafka, worker_config)
    }
}
