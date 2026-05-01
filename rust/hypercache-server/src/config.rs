use std::net::SocketAddr;
use std::str::FromStr;

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;
use tracing::level_filters::LevelFilter;

/// Bool that accepts "1", "0", "true", "false" from env vars.
#[derive(Clone, Debug)]
pub struct FlexBool(pub bool);

impl FromStr for FlexBool {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Ok(FlexBool(true)),
            "0" | "false" | "no" | "off" | "" => Ok(FlexBool(false)),
            _ => Err(format!("Invalid boolean value: '{s}'")),
        }
    }
}

impl std::ops::Deref for FlexBool {
    type Target = bool;
    fn deref(&self) -> &bool {
        &self.0
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(from = "ADDRESS", default = "0.0.0.0:3002")]
    pub address: SocketAddr,

    #[envconfig(from = "REDIS_URL", default = "redis://localhost:6379/")]
    pub redis_url: String,

    /// Optional: separate URL for Redis read replicas.
    /// Falls back to REDIS_URL if not set.
    #[envconfig(from = "REDIS_READER_URL", default = "")]
    pub redis_reader_url: String,

    #[envconfig(from = "REDIS_TIMEOUT_MS", default = "100")]
    pub redis_timeout_ms: u64,

    #[envconfig(from = "OBJECT_STORAGE_REGION", default = "us-east-1")]
    pub object_storage_region: String,

    #[envconfig(from = "OBJECT_STORAGE_BUCKET", default = "posthog")]
    pub object_storage_bucket: String,

    #[envconfig(from = "OBJECT_STORAGE_ENDPOINT", default = "")]
    pub object_storage_endpoint: String,

    #[envconfig(from = "ENABLE_METRICS", default = "false")]
    pub enable_metrics: FlexBool,

    #[envconfig(from = "DEBUG", default = "false")]
    pub debug: FlexBool,

    #[envconfig(from = "MAX_CONCURRENCY", default = "1000")]
    pub max_concurrency: usize,

    // --- Negative cache (in-memory miss markers to avoid repeated Redis+S3 lookups) ---
    #[envconfig(from = "NEGATIVE_CACHE_ENABLED", default = "false")]
    pub negative_cache_enabled: FlexBool,

    #[envconfig(from = "NEGATIVE_CACHE_MAX_ENTRIES", default = "100000")]
    pub negative_cache_max_entries: u64,

    #[envconfig(from = "NEGATIVE_CACHE_TTL_SECONDS", default = "300")]
    pub negative_cache_ttl_seconds: u64,

    // --- OpenTelemetry ---
    #[envconfig(from = "OTEL_URL")]
    pub otel_url: Option<String>,

    #[envconfig(from = "OTEL_SAMPLING_RATE", default = "1.0")]
    pub otel_sampling_rate: f64,

    #[envconfig(from = "OTEL_SERVICE_NAME", default = "hypercache-server")]
    pub otel_service_name: String,

    #[envconfig(from = "OTEL_EXPORT_TIMEOUT_SECS", default = "3")]
    pub otel_export_timeout_secs: u64,

    #[envconfig(from = "OTEL_LOG_LEVEL", default = "ERROR")]
    pub otel_log_level: LevelFilter,

    // --- Continuous profiling ---
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,
}
