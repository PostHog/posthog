use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    // Topic the kafka_uptime_pings CH table consumes from. Must match
    // `KAFKA_CLICKHOUSE_UPTIME_PINGS` in posthog/kafka_client/topics.py.
    #[envconfig(default = "clickhouse_uptime_pings")]
    pub kafka_pings_topic: String,

    // Topic the CDP internal-events consumer reads from. Status-change events
    // ($uptime_monitor_status_changed) are published here.
    #[envconfig(default = "cdp_internal_events")]
    pub kafka_internal_events_topic: String,

    // Max monitors claimed in a single batch. Tune up if a single worker can't keep up.
    #[envconfig(default = "100")]
    pub claim_batch_size: i64,

    // How long we lease a monitor for. The lease is informational — claim eligibility is
    // already gated by `next_check_at`, which we advance during the claim.
    #[envconfig(default = "60")]
    pub lease_ttl_seconds: i64,

    // Idle sleep when there's nothing to claim. Keep this short so newly-added monitors
    // start being pinged quickly.
    #[envconfig(default = "1000")]
    pub idle_sleep_ms: u64,

    // HTTP request timeout for the actual ping.
    #[envconfig(default = "10")]
    pub ping_timeout_seconds: u64,

    // How many in-flight pings a single worker fans out before awaiting.
    #[envconfig(default = "32")]
    pub ping_concurrency: usize,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3320")]
    pub port: u16,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
    }
}
