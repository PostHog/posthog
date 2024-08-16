use chrono::Duration;

use cyclotron_core::PoolConfig;
use envconfig::Envconfig;
use uuid::Uuid;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3303")]
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

    // Generally, this should be equivalent to a "shard id", as only one janitor should be running
    // per shard
    pub janitor_id: Option<String>,

    #[envconfig(default = "10")]
    pub janitor_max_touches: i16,

    #[envconfig(default = "60")]
    pub janitor_stall_timeout_seconds: u16,
}

impl Config {
    pub fn get_janitor_config(&self) -> JanitorConfig {
        let pool_config = PoolConfig {
            db_url: self.database_url.clone(),
            max_connections: Some(self.pg_max_connections),
            min_connections: Some(self.pg_min_connections),
            acquire_timeout_seconds: Some(self.pg_acquire_timeout_seconds),
            max_lifetime_seconds: Some(self.pg_max_lifetime_seconds),
            idle_timeout_seconds: Some(self.pg_idle_timeout_seconds),
        };

        let settings = JanitorSettings {
            stall_timeout: Duration::seconds(self.janitor_stall_timeout_seconds as i64),
            max_touches: self.janitor_max_touches,
            id: self
                .janitor_id
                .clone()
                .unwrap_or_else(|| Uuid::now_v7().to_string()),
        };

        JanitorConfig {
            pool: pool_config,
            settings,
        }
    }
}

pub struct JanitorConfig {
    pub pool: PoolConfig,
    pub settings: JanitorSettings,
}

pub struct JanitorSettings {
    pub stall_timeout: Duration,
    pub max_touches: i16,
    pub id: String,
}
