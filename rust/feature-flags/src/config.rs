use std::net::SocketAddr;

use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:3001")]
    pub address: SocketAddr,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub write_database_url: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub read_database_url: String,

    #[envconfig(default = "1024")]
    pub max_concurrent_jobs: usize,

    #[envconfig(default = "100")]
    pub max_pg_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,
}
