use std::path::PathBuf;

use crate::job::backoff::BackoffPolicy;
use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

// Re-export KafkaConfig for testing
pub use common_kafka::config::KafkaConfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    // ~100MB
    #[envconfig(default = "100000000")]
    pub chunk_size: usize,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // Same test key as the plugin server
    #[envconfig(default = "00beef0000beef0000beef0000beef00")]
    pub encryption_keys: String, // comma separated list of fernet keys

    #[envconfig(from = "KAFKA_TOPIC_MAIN", default = "events_plugin_ingestion")]
    pub kafka_topic_main: String,

    #[envconfig(
        from = "KAFKA_TOPIC_HISTORICAL",
        default = "events_plugin_ingestion_historical"
    )]
    pub kafka_topic_historical: String,

    #[envconfig(
        from = "KAFKA_TOPIC_OVERFLOW",
        default = "events_plugin_ingestion_overflow"
    )]
    pub kafka_topic_overflow: String,

    // Exponential backoff defaults
    #[envconfig(from = "BACKOFF_INITIAL_SECONDS", default = "60")]
    pub backoff_initial_seconds: u64,

    #[envconfig(from = "BACKOFF_MAX_SECONDS", default = "3600")]
    pub backoff_max_seconds: u64,

    #[envconfig(from = "BACKOFF_MULTIPLIER", default = "2.0")]
    pub backoff_multiplier: f64,

    // 0 means unlimited retries
    #[envconfig(from = "BACKOFF_MAX_ATTEMPTS", default = "0")]
    pub backoff_max_attempts: u32,

    // In-memory cache configuration
    #[envconfig(from = "IDENTIFY_MEMORY_CACHE_CAPACITY", default = "1000000")]
    pub identify_memory_cache_capacity: u64,
    #[envconfig(from = "IDENTIFY_MEMORY_CACHE_TTL_SECONDS", default = "3600")]
    pub identify_memory_cache_ttl_seconds: u64,

    // Group cache configuration
    #[envconfig(from = "GROUP_MEMORY_CACHE_CAPACITY", default = "1000000")]
    pub group_memory_cache_capacity: u64,
    #[envconfig(from = "GROUP_MEMORY_CACHE_TTL_SECONDS", default = "3600")]
    pub group_memory_cache_ttl_seconds: u64,

    // Force disable person processing for specific token:distinct_id pairs
    #[envconfig(from = "FORCE_DISABLE_PERSON_PROCESSING", default = "")]
    pub force_disable_person_processing: String,

    // Source chunk size for capture sink jobs. Kept smaller than the default
    // because each chunk becomes a single HTTP request to the capture service,
    // which enforces a 20MB body limit.
    #[envconfig(default = "15000000")]
    pub capture_chunk_size: usize,

    // Internal capture service URL for the CaptureEmitter
    #[envconfig(from = "CAPTURE_URL", default = "http://localhost:3307")]
    pub capture_url: String,

    // Dedicated root for temp files created during job processing. Swept on
    // every startup to reclaim space leaked by non-graceful pod terminations.
    #[envconfig(from = "STAGING_DIR", default = "/tmp/batch-import-worker")]
    pub staging_dir: String,

    // Fail-fast guard: if the staging directory grows past this many bytes while
    // downloading a part, the job is paused (surfaced to the user) instead of the
    // pod being evicted under disk pressure. 0 disables the guard. Size this below
    // the staging volume capacity in deployment.
    #[envconfig(from = "STAGING_DIR_MAX_BYTES", default = "0")]
    pub staging_dir_max_bytes: u64,

    // Where compressed sources stage decompressed part plaintext: `local_disk`
    // (default, per-pod disk) or `temp_bucket` (internal S3). Selects the
    // StagingBackend; nothing branches on it until routing lands.
    #[envconfig(from = "STAGING_BACKEND", default = "local_disk")]
    pub staging_backend: String,

    // Internal S3 "temp bucket" used when STAGING_BACKEND=temp_bucket. Empty
    // string means unset. TEMP_BUCKET_NAME is required in that mode.
    #[envconfig(from = "TEMP_BUCKET_NAME", default = "")]
    pub temp_bucket_name: String,
    #[envconfig(from = "TEMP_BUCKET_ENDPOINT", default = "")]
    pub temp_bucket_endpoint: String,
    #[envconfig(from = "TEMP_BUCKET_REGION", default = "")]
    pub temp_bucket_region: String,
    #[envconfig(from = "TEMP_BUCKET_PREFIX", default = "batch-import-staging/")]
    pub temp_bucket_prefix: String,

    // Per-part decompressed-byte ceiling enforced by the fetch+decompress pipeline
    // (decompression-bomb / cost guard). 0 disables it. Breaching it pauses the job
    // with an actionable error rather than staging unbounded plaintext.
    #[envconfig(from = "STAGED_PLAINTEXT_MAX_BYTES", default = "0")]
    pub staged_plaintext_max_bytes: u64,
}

/// Which staging backend a job's compressed sources use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StagingBackendKind {
    LocalDisk,
    TempBucket,
}

impl Config {
    pub fn resolve_kafka_topic(&self, logical_topic: &str) -> Result<String, anyhow::Error> {
        match logical_topic {
            "main" => Ok(self.kafka_topic_main.clone()),
            "historical" => Ok(self.kafka_topic_historical.clone()),
            "overflow" => Ok(self.kafka_topic_overflow.clone()),
            _ => Err(anyhow::Error::msg(format!(
                "Unknown kafka topic: {logical_topic}"
            ))),
        }
    }

    pub fn staging_dir(&self) -> PathBuf {
        PathBuf::from(&self.staging_dir)
    }

    /// Resolve and validate the configured staging backend. Fails fast when
    /// `temp_bucket` is selected without a bucket name, or on an unknown value.
    pub fn staging_backend(&self) -> Result<StagingBackendKind, anyhow::Error> {
        match self.staging_backend.as_str() {
            "local_disk" => Ok(StagingBackendKind::LocalDisk),
            "temp_bucket" => {
                if self.temp_bucket_name.trim().is_empty() {
                    return Err(anyhow::Error::msg(
                        "STAGING_BACKEND=temp_bucket requires TEMP_BUCKET_NAME to be set",
                    ));
                }
                Ok(StagingBackendKind::TempBucket)
            }
            other => Err(anyhow::Error::msg(format!(
                "Unknown STAGING_BACKEND '{other}' (expected 'local_disk' or 'temp_bucket')"
            ))),
        }
    }

    /// Optional custom S3 endpoint (local dev / SeaweedFS). `None` when unset.
    pub fn temp_bucket_endpoint(&self) -> Option<&str> {
        let e = self.temp_bucket_endpoint.trim();
        (!e.is_empty()).then_some(e)
    }

    /// Optional S3 region override. `None` when unset.
    pub fn temp_bucket_region(&self) -> Option<&str> {
        let r = self.temp_bucket_region.trim();
        (!r.is_empty()).then_some(r)
    }

    pub fn backoff_policy(&self) -> BackoffPolicy {
        BackoffPolicy::new(
            std::time::Duration::from_secs(self.backoff_initial_seconds),
            self.backoff_multiplier,
            std::time::Duration::from_secs(self.backoff_max_seconds),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_kafka_topic_main() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("main").unwrap();
        assert_eq!(result, "events_plugin_ingestion");
    }

    #[test]
    fn test_resolve_kafka_topic_historical() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("historical").unwrap();
        assert_eq!(result, "events_plugin_ingestion_historical");
    }

    #[test]
    fn test_resolve_kafka_topic_overflow() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("overflow").unwrap();
        assert_eq!(result, "events_plugin_ingestion_overflow");
    }

    #[test]
    fn test_resolve_kafka_topic_unknown() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("unknown");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: unknown"));
    }

    #[test]
    fn test_resolve_kafka_topic_empty() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic:"));
    }

    #[test]
    fn test_resolve_kafka_topic_case_sensitive() {
        let config = Config::init_from_env().unwrap();
        let result = config.resolve_kafka_topic("MAIN");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Unknown kafka topic: MAIN"));
    }

    #[test]
    fn test_backoff_policy_defaults() {
        let config = Config::init_from_env().unwrap();
        let p = config.backoff_policy();
        assert_eq!(p.initial_delay.as_secs(), 60);
        assert_eq!(p.max_delay.as_secs(), 3600);
        assert!((p.multiplier - 2.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_staging_backend_defaults_to_local_disk() {
        let config = Config::init_from_env().unwrap();
        assert_eq!(config.staging_backend, "local_disk");
        assert_eq!(
            config.staging_backend().unwrap(),
            StagingBackendKind::LocalDisk
        );
        assert_eq!(config.staged_plaintext_max_bytes, 0);
        assert_eq!(config.temp_bucket_prefix, "batch-import-staging/");
        assert_eq!(config.temp_bucket_endpoint(), None);
        assert_eq!(config.temp_bucket_region(), None);
    }

    fn config_for_backend(backend: &str, bucket: &str) -> Config {
        let mut config = Config::init_from_env().unwrap();
        config.staging_backend = backend.to_string();
        config.temp_bucket_name = bucket.to_string();
        config
    }

    #[test]
    fn test_staging_backend_temp_bucket_requires_name() {
        let config = config_for_backend("temp_bucket", "");
        let err = config.staging_backend().unwrap_err().to_string();
        assert!(err.contains("TEMP_BUCKET_NAME"), "unexpected error: {err}");
    }

    #[test]
    fn test_staging_backend_temp_bucket_ok_with_name() {
        let config = config_for_backend("temp_bucket", "my-bucket");
        assert_eq!(
            config.staging_backend().unwrap(),
            StagingBackendKind::TempBucket
        );
    }

    #[test]
    fn test_staging_backend_unknown_value_errors() {
        let config = config_for_backend("nfs", "");
        let err = config.staging_backend().unwrap_err().to_string();
        assert!(
            err.contains("Unknown STAGING_BACKEND"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn test_temp_bucket_endpoint_and_region_optional() {
        let mut config = Config::init_from_env().unwrap();
        config.temp_bucket_endpoint = "  ".to_string();
        config.temp_bucket_region = "".to_string();
        assert_eq!(config.temp_bucket_endpoint(), None);
        assert_eq!(config.temp_bucket_region(), None);

        config.temp_bucket_endpoint = "http://localhost:8333".to_string();
        config.temp_bucket_region = "us-east-1".to_string();
        assert_eq!(config.temp_bucket_endpoint(), Some("http://localhost:8333"));
        assert_eq!(config.temp_bucket_region(), Some("us-east-1"));
    }
}
