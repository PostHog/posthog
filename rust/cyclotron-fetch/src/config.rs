use chrono::Duration;
use cyclotron_core::PoolConfig;
use envconfig::Envconfig;
use uuid::Uuid;

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

    pub worker_id: Option<String>,              // Default to a UUID
    pub job_poll_interval_seconds: Option<u32>, // Defaults to 1
    pub concurrent_requests_limit: Option<u32>, // Defaults to 1000
    pub fetch_timeout_seconds: Option<u32>,     // Defaults to 30
    pub max_retry_attempts: Option<u32>,        // Defaults to 10
    pub queue_served: Option<String>,           // Default to "fetch"
    pub batch_size: Option<usize>,              // Defaults to 1000
    pub max_response_bytes: Option<usize>,      // Defaults to 1MB
    pub retry_backoff_base_ms: Option<u32>,     // Defaults to 4000
}

// I do this instead of using envconfig's defaults because
// envconfig doesn't support defaults provided by functions,
// which is frustrating when I want to use UUIDs, and if I'm
// going to break out one field, I might as well break out
// everything into "AppConfig" and "PoolConfig"
#[derive(Debug, Clone)]
pub struct AppConfig {
    pub host: String,
    pub port: u16,
    pub worker_id: String,
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
    pub fn to_components(self) -> (AppConfig, PoolConfig) {
        let worker_id = self.worker_id.unwrap_or_else(|| Uuid::now_v7().to_string());
        let job_poll_interval_seconds = self.job_poll_interval_seconds.unwrap_or(1);
        let concurrent_requests_limit = self.concurrent_requests_limit.unwrap_or(1000);
        let fetch_timeout_seconds = self.fetch_timeout_seconds.unwrap_or(30);
        let max_retry_attempts = self.max_retry_attempts.unwrap_or(10);
        let queue_served = self.queue_served.unwrap_or_else(|| "fetch".to_string());

        let app_config = AppConfig {
            host: self.host,
            port: self.port,
            worker_id,
            job_poll_interval: Duration::seconds(job_poll_interval_seconds as i64),
            concurrent_requests_limit,
            fetch_timeout: Duration::seconds(fetch_timeout_seconds as i64),
            max_retry_attempts,
            queue_served,
            batch_size: self.batch_size.unwrap_or(1000),
            max_response_bytes: self.max_response_bytes.unwrap_or(1024 * 1024),
            retry_backoff_base: Duration::milliseconds(
                self.retry_backoff_base_ms.unwrap_or(4000) as i64
            ),
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

        (app_config, pool_config)
    }
}
