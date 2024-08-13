use envconfig::Envconfig;
use uuid::Uuid;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3302")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/cyclotron")]
    pub database_url: String,

    #[envconfig(default = "30")]
    pub cleanup_interval_secs: u64,

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

    pub worker_id: Option<String>,
}

impl Config {
    pub fn get_id(&self) -> String {
        self.worker_id
            .clone()
            .unwrap_or_else(|| Uuid::now_v7().to_string())
    }
}
