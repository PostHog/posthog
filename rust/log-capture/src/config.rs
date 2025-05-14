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
    pub clickhouse_host: String,
    #[envconfig(default = "default")]
    pub clickhouse_user: String,
    #[envconfig()]
    pub clickhouse_password: String,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
