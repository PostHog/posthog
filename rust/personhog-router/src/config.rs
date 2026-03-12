use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50052")]
    pub grpc_address: SocketAddr,

    /// URL of the personhog-replica backend
    #[envconfig(default = "http://127.0.0.1:50051")]
    pub replica_url: String,

    /// Timeout for backend requests in milliseconds
    #[envconfig(default = "5000")]
    pub backend_timeout_ms: u64,

    #[envconfig(default = "9101")]
    pub metrics_port: u16,

    /// Maximum number of retry attempts for transient backend errors (0 = no retries)
    #[envconfig(default = "3")]
    pub max_retries: u32,

    /// Initial backoff delay in milliseconds before the first retry
    #[envconfig(default = "25")]
    pub initial_backoff_ms: u64,

    /// Maximum backoff delay in milliseconds (caps exponential growth)
    #[envconfig(default = "500")]
    pub max_backoff_ms: u64,
}

impl Config {
    pub fn backend_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_timeout_ms)
    }

    pub fn retry_config(&self) -> RetryConfig {
        RetryConfig {
            max_retries: self.max_retries,
            initial_backoff_ms: self.initial_backoff_ms,
            max_backoff_ms: self.max_backoff_ms,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub initial_backoff_ms: u64,
    pub max_backoff_ms: u64,
}
