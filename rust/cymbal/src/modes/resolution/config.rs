use std::net::SocketAddr;

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

use crate::core::config::ResolverConfig;

const DEFAULT_CACHE_KEY_PREFIX: &str = "@posthog/cymbal-resolution-cache";
const DEFAULT_CACHE_RESPONSE_TIMEOUT_MS: u64 = 50;
const DEFAULT_CACHE_CONNECTION_TIMEOUT_MS: u64 = 1_000;
const DEFAULT_FAILURE_TTL_SECONDS: u64 = 86_400;
const DEFAULT_TOUCH_TTL_SECONDS: u64 = 43_200;
const DEFAULT_COMPRESSION_THRESHOLD_BYTES: usize = 512;
const DEFAULT_COMPRESSION_LEVEL: i32 = 3;
const DEFAULT_MAX_ENCODED_VALUE_BYTES: usize = 1024 * 1024;
const DEFAULT_MAX_DECODED_VALUE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Envconfig, Clone, Debug, PartialEq, Eq)]
pub struct ResolutionCacheConfig {
    #[envconfig(from = "RESOLUTION_CACHE_ENABLED", default = "false")]
    pub enabled: bool,

    #[envconfig(from = "RESOLUTION_CACHE_REDIS_URL")]
    pub redis_url: Option<String>,

    #[envconfig(
        from = "RESOLUTION_CACHE_KEY_PREFIX",
        default = "@posthog/cymbal-resolution-cache"
    )]
    pub key_prefix: String,

    #[envconfig(from = "RESOLUTION_CACHE_RESPONSE_TIMEOUT_MS", default = "50")]
    pub response_timeout_ms: u64,

    #[envconfig(from = "RESOLUTION_CACHE_CONNECTION_TIMEOUT_MS", default = "1000")]
    pub connection_timeout_ms: u64,

    #[envconfig(from = "RESOLUTION_CACHE_FAILURE_TTL_SECONDS", default = "86400")]
    pub failure_ttl_seconds: u64,

    #[envconfig(from = "RESOLUTION_CACHE_TOUCH_TTL_SECONDS", default = "43200")]
    pub touch_ttl_seconds: u64,

    #[envconfig(from = "RESOLUTION_CACHE_COMPRESSION_ENABLED", default = "true")]
    pub compression_enabled: bool,

    #[envconfig(from = "RESOLUTION_CACHE_COMPRESSION_THRESHOLD_BYTES", default = "512")]
    pub compression_threshold_bytes: usize,

    #[envconfig(from = "RESOLUTION_CACHE_COMPRESSION_LEVEL", default = "3")]
    pub compression_level: i32,

    #[envconfig(from = "RESOLUTION_CACHE_MAX_ENCODED_VALUE_BYTES", default = "1048576")]
    pub max_encoded_value_bytes: usize,

    #[envconfig(from = "RESOLUTION_CACHE_MAX_DECODED_VALUE_BYTES", default = "4194304")]
    pub max_decoded_value_bytes: usize,
}

impl Default for ResolutionCacheConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            redis_url: None,
            key_prefix: DEFAULT_CACHE_KEY_PREFIX.to_string(),
            response_timeout_ms: DEFAULT_CACHE_RESPONSE_TIMEOUT_MS,
            connection_timeout_ms: DEFAULT_CACHE_CONNECTION_TIMEOUT_MS,
            failure_ttl_seconds: DEFAULT_FAILURE_TTL_SECONDS,
            touch_ttl_seconds: DEFAULT_TOUCH_TTL_SECONDS,
            compression_enabled: true,
            compression_threshold_bytes: DEFAULT_COMPRESSION_THRESHOLD_BYTES,
            compression_level: DEFAULT_COMPRESSION_LEVEL,
            max_encoded_value_bytes: DEFAULT_MAX_ENCODED_VALUE_BYTES,
            max_decoded_value_bytes: DEFAULT_MAX_DECODED_VALUE_BYTES,
        }
    }
}

impl ResolutionCacheConfig {
    pub fn validate(&self) -> Result<(), String> {
        if !self.enabled {
            return Ok(());
        }

        if self
            .redis_url
            .as_deref()
            .is_none_or(|url| url.trim().is_empty())
        {
            return Err("RESOLUTION_CACHE_REDIS_URL is required when enabled".to_string());
        }
        if self.key_prefix.trim().is_empty() {
            return Err("RESOLUTION_CACHE_KEY_PREFIX cannot be empty".to_string());
        }
        if self.response_timeout_ms == 0 {
            return Err("RESOLUTION_CACHE_RESPONSE_TIMEOUT_MS must be positive".to_string());
        }
        if self.connection_timeout_ms == 0 {
            return Err("RESOLUTION_CACHE_CONNECTION_TIMEOUT_MS must be positive".to_string());
        }
        if self.failure_ttl_seconds == 0 {
            return Err("RESOLUTION_CACHE_FAILURE_TTL_SECONDS must be positive".to_string());
        }
        if self.touch_ttl_seconds == 0 {
            return Err("RESOLUTION_CACHE_TOUCH_TTL_SECONDS must be positive".to_string());
        }
        if !(0..=22).contains(&self.compression_level) {
            return Err("RESOLUTION_CACHE_COMPRESSION_LEVEL must be between 0 and 22".to_string());
        }
        if self.max_encoded_value_bytes == 0 {
            return Err("RESOLUTION_CACHE_MAX_ENCODED_VALUE_BYTES must be positive".to_string());
        }
        if self.max_decoded_value_bytes == 0 {
            return Err("RESOLUTION_CACHE_MAX_DECODED_VALUE_BYTES must be positive".to_string());
        }

        Ok(())
    }
}

/// Top-level config for resolution mode. Owns the shared resolver config and the
/// resolution service settings — no processing-only knobs. `INTERNAL_API_SECRET`
/// and `SYMBOL_RESOLUTION_CONCURRENCY` come from the nested `resolver`.
#[derive(Envconfig, Clone)]
pub struct ResolutionConfig {
    #[envconfig(nested = true)]
    pub resolver: ResolverConfig,

    #[envconfig(nested = true)]
    pub service: Config,

    #[envconfig(nested = true)]
    pub resolution_cache: ResolutionCacheConfig,

    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,
}

impl ResolutionConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }
}

/// Resolution service settings (gRPC bind, metrics, concurrency, subscribe
/// cadence). Nested into [`ResolutionConfig`].
#[derive(Envconfig, Clone)]
pub struct Config {
    /// gRPC bind address for the cymbal.resolution.v1 server.
    #[envconfig(from = "GRPC_ADDRESS", default = "0.0.0.0:50061")]
    pub grpc_address: SocketAddr,

    /// HTTP bind port for liveness, readiness, and Prometheus metrics.
    #[envconfig(from = "METRICS_PORT", default = "9101")]
    pub metrics_port: u16,

    /// Cap on concurrent gRPC requests accepted by the server before fast
    /// load shedding kicks in. Beyond this, callers receive `UNAVAILABLE`
    /// and retry against another pod — preferred over hidden queue growth
    /// on the symbol-resolution semaphore. Zero disables the limit; the
    /// non-zero default keeps fail-fast semantics by default.
    #[envconfig(from = "MAX_CONCURRENT_REQUESTS", default = "256")]
    pub max_concurrent_requests: usize,

    /// Process-wide cap on concurrent item (exception) processing across all
    /// in-flight `Resolve` requests. Symbol work is governed separately by the
    /// shared `SYMBOL_RESOLUTION_CONCURRENCY` knob on the parent config.
    #[envconfig(from = "MAX_ITEM_CONCURRENCY", default = "64")]
    pub max_item_concurrency: usize,

    /// Service instance identifier surfaced to callers via `LoadEvent` on
    /// the Subscribe stream. Defaults to a random uuid generated at boot
    /// when not provided.
    #[envconfig(from = "SERVICE_INSTANCE_ID")]
    pub service_instance_id: Option<String>,

    /// Default cadence for the freshness/draining `Subscribe` RPC in
    /// milliseconds. Callers may suggest a cadence via
    /// `SubscribeRequest.tick_hint_ms`; the server clamps to
    /// `[subscribe_min_tick_ms, subscribe_max_tick_ms]` so a misbehaving
    /// caller cannot induce excess work.
    #[envconfig(from = "SUBSCRIBE_TICK_INTERVAL_MS", default = "1000")]
    pub subscribe_tick_interval_ms: u64,

    /// Lower bound for the load-event tick cadence. Hints below this are
    /// clamped up.
    #[envconfig(from = "SUBSCRIBE_MIN_TICK_MS", default = "100")]
    pub subscribe_min_tick_ms: u64,

    /// Upper bound for the load-event tick cadence. Hints above this are
    /// clamped down so a misconfigured caller cannot make the stream stale.
    #[envconfig(from = "SUBSCRIBE_MAX_TICK_MS", default = "10000")]
    pub subscribe_max_tick_ms: u64,
}

#[cfg(test)]
mod tests {
    use super::ResolutionCacheConfig;

    #[test]
    fn resolution_cache_defaults_disabled_and_bounded() {
        let config = ResolutionCacheConfig::default();

        assert!(!config.enabled);
        assert!(config.redis_url.is_none());
        assert_eq!(config.key_prefix, "@posthog/cymbal-resolution-cache");
        assert_eq!(config.response_timeout_ms, 50);
        assert_eq!(config.connection_timeout_ms, 1_000);
        assert_eq!(config.failure_ttl_seconds, 86_400);
        assert_eq!(config.touch_ttl_seconds, 43_200);
        assert!(config.compression_enabled);
        assert_eq!(config.compression_threshold_bytes, 512);
        assert_eq!(config.compression_level, 3);
        assert_eq!(config.max_encoded_value_bytes, 1_048_576);
        assert_eq!(config.max_decoded_value_bytes, 4_194_304);
        assert!(config.validate().is_ok());
    }

    #[test]
    fn enabled_resolution_cache_requires_a_url_and_safe_limits() {
        let mut config = ResolutionCacheConfig {
            enabled: true,
            ..Default::default()
        };
        assert!(config.validate().unwrap_err().contains("REDIS_URL"));

        config.redis_url = Some("redis://cache:6379".to_string());
        assert!(config.validate().is_ok());

        type InvalidMutation = (&'static str, fn(&mut ResolutionCacheConfig));
        let invalid_mutations: [InvalidMutation; 6] = [
            ("response timeout", |config: &mut ResolutionCacheConfig| {
                config.response_timeout_ms = 0
            }),
            (
                "connection timeout",
                |config: &mut ResolutionCacheConfig| config.connection_timeout_ms = 0,
            ),
            ("failure ttl", |config: &mut ResolutionCacheConfig| {
                config.failure_ttl_seconds = 0
            }),
            ("touch ttl", |config: &mut ResolutionCacheConfig| {
                config.touch_ttl_seconds = 0
            }),
            ("encoded limit", |config: &mut ResolutionCacheConfig| {
                config.max_encoded_value_bytes = 0
            }),
            ("decoded limit", |config: &mut ResolutionCacheConfig| {
                config.max_decoded_value_bytes = 0
            }),
        ];
        for (name, mutate) in invalid_mutations {
            let mut invalid = config.clone();
            mutate(&mut invalid);
            assert!(invalid.validate().is_err(), "{name}");
        }

        config.key_prefix.clear();
        assert!(config.validate().is_err());
    }
}
