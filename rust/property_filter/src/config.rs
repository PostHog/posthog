use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/test_posthog")]
    pub database_url: String,

    #[envconfig(default = "8")]
    pub max_pg_connections: u32,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,
}
