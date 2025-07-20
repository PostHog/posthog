use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // gRPC server configuration (OTLP)
    #[envconfig(from = "GRPC_BIND_HOST", default = "::")]
    pub grpc_host: String,

    #[envconfig(from = "GRPC_BIND_PORT", default = "4317")]
    pub grpc_port: u16,

    // HTTP server configuration (OTLP)
    #[envconfig(from = "HTTP_BIND_HOST", default = "::")]
    pub http_host: String,

    #[envconfig(from = "HTTP_BIND_PORT", default = "4318")]
    pub http_port: u16,

    // Management server configuration (health checks, metrics)
    #[envconfig(from = "MGMT_BIND_HOST", default = "::")]
    pub mgmt_host: String,

    #[envconfig(from = "MGMT_BIND_PORT", default = "8000")]
    pub mgmt_port: u16,

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

    #[envconfig(from = "CLICKHOUSE_TABLE", default = "logs")]
    pub clickhouse_table: String,

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

    pub fn grpc_bind_address(&self) -> String {
        format!("{}:{}", self.grpc_host, self.grpc_port)
    }

    pub fn http_bind_address(&self) -> String {
        format!("{}:{}", self.http_host, self.http_port)
    }

    pub fn mgmt_bind_address(&self) -> String {
        format!("{}:{}", self.mgmt_host, self.mgmt_port)
    }
}