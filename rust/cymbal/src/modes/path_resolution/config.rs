use std::net::SocketAddr;
use std::time::Duration;

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

use crate::core::config::ResolverConfig;

use super::list_store::ListStoreConfig;

#[derive(Envconfig, Clone)]
pub struct PathResolutionConfig {
    /// Only the `object_storage_*` settings are read. This mode connects to nothing else.
    #[envconfig(nested = true)]
    pub resolver: ResolverConfig,

    #[envconfig(nested = true)]
    pub service: Config,

    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,
}

impl PathResolutionConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }

    pub fn list_store(&self) -> ListStoreConfig {
        ListStoreConfig {
            bucket: self.resolver.object_storage_bucket.clone(),
            folder: self.service.repo_paths_folder.clone(),
            cache_bytes: self.service.cache_bytes,
            negative_ttl: Duration::from_secs(self.service.missing_ttl_secs),
            max_decompressed_bytes: self.service.max_decompressed_bytes,
            load_timeout: Duration::from_secs(self.service.load_timeout_secs),
        }
    }
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "GRPC_ADDRESS", default = "0.0.0.0:50062")]
    pub grpc_address: SocketAddr,

    #[envconfig(from = "METRICS_PORT", default = "9101")]
    pub metrics_port: u16,

    /// Concurrent requests accepted before the server sheds load with `UNAVAILABLE`.
    #[envconfig(from = "MAX_CONCURRENT_REQUESTS", default = "256")]
    pub max_concurrent_requests: usize,

    /// Comma-separated secrets that callers may send, current first. Empty rejects every request.
    #[envconfig(from = "CYMBAL_PATH_RESOLUTION_SECRETS", default = "")]
    pub secrets: String,

    /// Must equal Django's `OBJECT_STORAGE_ERROR_TRACKING_REPO_PATHS_FOLDER`.
    #[envconfig(from = "CYMBAL_REPO_PATHS_FOLDER", default = "repo_paths")]
    pub repo_paths_folder: String,

    #[envconfig(from = "CYMBAL_PATH_RESOLUTION_CACHE_BYTES", default = "2147483648")]
    pub cache_bytes: u64,

    #[envconfig(from = "CYMBAL_PATH_RESOLUTION_MISSING_TTL_SECS", default = "120")]
    pub missing_ttl_secs: u64,

    #[envconfig(
        from = "CYMBAL_PATH_RESOLUTION_MAX_DECOMPRESSED_BYTES",
        default = "67108864"
    )]
    pub max_decompressed_bytes: usize,

    #[envconfig(from = "CYMBAL_PATH_RESOLUTION_LOAD_TIMEOUT_SECS", default = "30")]
    pub load_timeout_secs: u64,

    /// Time between failing readiness on shutdown and stopping the server. Callers find pods by
    /// DNS, so this must cover their DNS refresh interval.
    #[envconfig(from = "CYMBAL_PATH_RESOLUTION_DRAIN_SECS", default = "10")]
    pub drain_secs: u64,
}
