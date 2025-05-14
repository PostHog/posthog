use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    #[envconfig(from = "JWT_SECRET")]
    pub jwt_secret: String,

    #[envconfig(default = "http://localhost:8000")]
    pub clickhouse_url: String,

    #[envconfig(from = "CLICKHOUSE_DATABASE", default = "default")]
    pub clickhouse_database: String,

    #[envconfig(from = "CLICKHOUSE_USER", default = "default")]
    pub clickhouse_user: String,

    #[envconfig(from = "CLICKHOUSE_PASSWORD", default = "")]
    pub clickhouse_password: String,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
