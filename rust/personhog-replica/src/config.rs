use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50051")]
    pub grpc_address: SocketAddr,

    /// Storage backend to use. Currently supported: "postgres"
    #[envconfig(default = "postgres")]
    pub storage_backend: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "0")]
    pub min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    #[envconfig(default = "5000")]
    pub statement_timeout_ms: u64,

    #[envconfig(default = "9100")]
    pub metrics_port: u16,
}

impl Config {
    pub fn acquire_timeout(&self) -> Duration {
        Duration::from_secs(self.acquire_timeout_secs)
    }

    pub fn idle_timeout(&self) -> Option<Duration> {
        if self.idle_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.idle_timeout_secs))
        }
    }

    pub fn statement_timeout(&self) -> Option<u64> {
        if self.statement_timeout_ms == 0 {
            None
        } else {
            Some(self.statement_timeout_ms)
        }
    }
}
