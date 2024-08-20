use envconfig::Envconfig;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3300")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub database_url: String,

    #[envconfig(default = "default")]
    pub queue_name: String,

    #[envconfig(default = "100")]
    pub max_pg_connections: u32,

    #[envconfig(default = "5000000")]
    pub max_body_size: usize,

    #[envconfig(default = "100")]
    pub concurrency_limit: usize,

    #[envconfig(default = "false")]
    pub hog_mode: bool,
}

impl Config {
    pub fn bind(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}
