use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    #[envconfig(from = "JWT_SECRET")]
    pub jwt_secret: String,

    #[envconfig()]
    pub clickhouse_url: String,

    #[envconfig(from = "CLICKHOUSE_DATABASE", default = "default")]
    pub clickhouse_database: String,

    #[envconfig(from = "CLICKHOUSE_USER", default = "default")]
    pub clickhouse_user: String,

    #[envconfig(from = "CLICKHOUSE_PASSWORD", default = "")]
    pub clickhouse_password: String,

    #[envconfig(from = "INSETER_PERIOD_MS", default = "1000")]
    pub inserter_period_ms: u64,

    #[envconfig(from = "INSETER_MAX_BYTES", default = "50000000")]
    pub inserter_max_bytes: u64,

    #[envconfig(from = "INSETER_MAX_ROWS", default = "10000")]
    pub inserter_max_rows: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
