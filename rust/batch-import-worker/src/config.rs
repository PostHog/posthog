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

    // Dedicated cross-account role for managed-migration S3 imports. Customer trust
    // policies reference this role's ARN (not the worker's own identity), so the worker
    // role-chains through it: ambient creds -> managed-migrations role -> customer role.
    // Required for IAM-role-auth jobs; when unset they fail with a contact-support error
    // (the customer hop can never succeed without it). Key-auth jobs don't need it.
    #[envconfig(from = "MANAGED_MIGRATIONS_ROLE_ARN")]
    pub managed_migrations_role_arn: Option<String>,

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
    // Custom S3 endpoint for local dev / CI (SeaweedFS: http://localhost:8333 with
    // bucket `posthog`, any credentials, and TEMP_BUCKET_FORCE_PATH_STYLE=true).
    #[envconfig(from = "TEMP_BUCKET_ENDPOINT", default = "")]
    pub temp_bucket_endpoint: String,
    #[envconfig(from = "TEMP_BUCKET_REGION", default = "")]
    pub temp_bucket_region: String,
    #[envconfig(from = "TEMP_BUCKET_PREFIX", default = "batch-import-staging/")]
    pub temp_bucket_prefix: String,

    // Explicit S3 credentials for local dev / CI without IAM (production uses the
    // standard AWS chain: IRSA web-identity). Both must be set to take effect.
    #[envconfig(from = "TEMP_BUCKET_ACCESS_KEY_ID", default = "")]
    pub temp_bucket_access_key_id: String,
    #[envconfig(from = "TEMP_BUCKET_SECRET_ACCESS_KEY", default = "")]
    pub temp_bucket_secret_access_key: String,

    // Path-style object URLs (required by S3-compatible dev stores like SeaweedFS).
    #[envconfig(from = "TEMP_BUCKET_FORCE_PATH_STYLE", default = "false")]
    pub temp_bucket_force_path_style: bool,

    // Timeout for a single S3 request attempt, including body transfer. Must be
    // large enough for a full CHUNK_SIZE (~100 MB) ranged GET on a slow path.
    #[envconfig(from = "TEMP_BUCKET_ATTEMPT_TIMEOUT_SECS", default = "120")]
    pub temp_bucket_attempt_timeout_secs: u64,

    // Total time budget for an S3 operation across all client-level retries.
    #[envconfig(from = "TEMP_BUCKET_OPERATION_TIMEOUT_SECS", default = "600")]
    pub temp_bucket_operation_timeout_secs: u64,

    // Client-level retries per S3 operation (job-level backoff retries on top).
    #[envconfig(from = "TEMP_BUCKET_MAX_RETRIES", default = "3")]
    pub temp_bucket_max_retries: usize,

    // Concurrent in-flight requests to the temp bucket per job client.
    #[envconfig(from = "TEMP_BUCKET_MAX_CONCURRENT_REQUESTS", default = "16")]
    pub temp_bucket_max_concurrent_requests: usize,

    // Multipart upload part size when staging a part. S3 assembles the numbered
    // parts into one object; part size bounds the maximum staged object size
    // (part_size x 10,000 parts — the AWS multipart limit) and the upload's
    // memory footprint (part_size x (concurrency + 1) buffered in RAM).
    // 64 MiB => 640 GiB max staged part at ~320 MiB peak RAM. Must be within
    // S3's 5 MiB..5 GiB part-size bounds.
    #[envconfig(from = "TEMP_BUCKET_UPLOAD_PART_SIZE_BYTES", default = "67108864")]
    pub temp_bucket_upload_part_size_bytes: u64,

    // Concurrent in-flight part uploads while staging. Staging throughput is
    // producer-bound (origin download + gzip decode), so a small window suffices
    // to keep uploads fully overlapped.
    #[envconfig(from = "TEMP_BUCKET_UPLOAD_CONCURRENCY", default = "4")]
    pub temp_bucket_upload_concurrency: usize,

    // Per-part decompressed-byte ceiling enforced by the fetch+decompress pipeline
    // (decompression-bomb / cost guard). Breaching it pauses the job with an
    // actionable error rather than staging unbounded plaintext.
    //
    // 0 means "no operator-configured ceiling", NOT unlimited: in temp_bucket mode
    // an implicit ceiling just below the S3 multipart wall always applies (see
    // `effective_plaintext_ceiling`), so an oversized part pauses with the
    // actionable message instead of an opaque multipart failure. The local
    // streaming path has no wall and stays unlimited when this is 0.
    #[envconfig(from = "STAGED_PLAINTEXT_MAX_BYTES", default = "0")]
    pub staged_plaintext_max_bytes: u64,

    // Per-object ceiling on staged plaintext retained as quarantine evidence when a
    // job pauses on a data error. Objects above it are deleted without an evidence
    // copy, bounding how much temp-bucket capacity repeated pause-and-recreate loops
    // can pin until the bucket TTL. 0 disables the cap. Default 10 GiB.
    #[envconfig(from = "TEMP_BUCKET_QUARANTINE_MAX_BYTES", default = "10737418240")]
    pub temp_bucket_quarantine_max_bytes: u64,
}

/// S3 multipart uploads are capped at 10,000 parts (AWS hard limit).
const S3_MAX_MULTIPART_PARTS: u64 = 10_000;
/// S3 part-size bounds: 5 MiB minimum (except the last part), 5 GiB maximum.
const S3_MIN_PART_SIZE_BYTES: u64 = 5 * 1024 * 1024;
const S3_MAX_PART_SIZE_BYTES: u64 = 5 * 1024 * 1024 * 1024;
/// S3 single-object size cap.
const S3_MAX_OBJECT_BYTES: u64 = 5 * 1024 * 1024 * 1024 * 1024;

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
    /// `temp_bucket` is selected without a bucket name, with upload knobs outside
    /// S3's multipart bounds, or on an unknown value.
    pub fn staging_backend(&self) -> Result<StagingBackendKind, anyhow::Error> {
        match self.staging_backend.as_str() {
            "local_disk" => Ok(StagingBackendKind::LocalDisk),
            "temp_bucket" => {
                if self.temp_bucket_name.trim().is_empty() {
                    return Err(anyhow::Error::msg(
                        "STAGING_BACKEND=temp_bucket requires TEMP_BUCKET_NAME to be set",
                    ));
                }
                if !(S3_MIN_PART_SIZE_BYTES..=S3_MAX_PART_SIZE_BYTES)
                    .contains(&self.temp_bucket_upload_part_size_bytes)
                {
                    // Sub-5MiB parts are rejected by S3 on every multi-part stage;
                    // catch the misconfiguration before any job work starts.
                    return Err(anyhow::Error::msg(format!(
                        "TEMP_BUCKET_UPLOAD_PART_SIZE_BYTES={} outside S3 part-size bounds \
                         ({S3_MIN_PART_SIZE_BYTES}..={S3_MAX_PART_SIZE_BYTES})",
                        self.temp_bucket_upload_part_size_bytes
                    )));
                }
                if self.temp_bucket_upload_concurrency == 0 {
                    return Err(anyhow::Error::msg(
                        "TEMP_BUCKET_UPLOAD_CONCURRENCY must be >= 1",
                    ));
                }
                Ok(StagingBackendKind::TempBucket)
            }
            other => Err(anyhow::Error::msg(format!(
                "Unknown STAGING_BACKEND '{other}' (expected 'local_disk' or 'temp_bucket')"
            ))),
        }
    }

    /// The largest object the temp bucket can hold with the configured part size:
    /// S3 caps multipart uploads at 10,000 parts and objects at 5 TiB.
    fn temp_bucket_object_wall_bytes(&self) -> u64 {
        std::cmp::min(
            self.temp_bucket_upload_part_size_bytes
                .saturating_mul(S3_MAX_MULTIPART_PARTS),
            S3_MAX_OBJECT_BYTES,
        )
    }

    /// Effective per-part decompressed-byte ceiling in temp_bucket mode.
    ///
    /// Always non-zero: an implicit ceiling at 95% of the S3 multipart wall applies
    /// even when `STAGED_PLAINTEXT_MAX_BYTES=0`, so an oversized part always pauses
    /// with the actionable "split the import" message and can never reach the wall's
    /// opaque multipart failure. An operator-configured ceiling only tightens it.
    pub fn effective_plaintext_ceiling(&self) -> u64 {
        let implicit = self.temp_bucket_object_wall_bytes() / 100 * 95;
        if self.staged_plaintext_max_bytes > 0 {
            std::cmp::min(self.staged_plaintext_max_bytes, implicit)
        } else {
            implicit
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

    /// Explicit S3 credentials (local dev / CI). `None` unless both parts are set;
    /// production relies on the standard AWS chain (IRSA) instead.
    pub fn temp_bucket_credentials(&self) -> Option<(&str, &str)> {
        let key = self.temp_bucket_access_key_id.trim();
        let secret = self.temp_bucket_secret_access_key.trim();
        (!key.is_empty() && !secret.is_empty()).then_some((key, secret))
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

    #[test]
    fn test_temp_bucket_credentials_require_both_parts() {
        let mut config = Config::init_from_env().unwrap();
        assert_eq!(config.temp_bucket_credentials(), None);
        config.temp_bucket_access_key_id = "key".to_string();
        assert_eq!(config.temp_bucket_credentials(), None);
        config.temp_bucket_secret_access_key = "secret".to_string();
        assert_eq!(config.temp_bucket_credentials(), Some(("key", "secret")));
    }

    #[test]
    fn test_upload_knob_validation_bounds() {
        // Sub-5MiB parts are rejected by S3 on multi-part stages; >5GiB is the S3
        // part-size maximum; concurrency 0 would deadlock the writer. Each must
        // fail fast at config resolution — but only in temp_bucket mode, where the
        // knobs are actually consumed.
        let cases: Vec<(u64, usize, &str)> = vec![
            (4 * 1024 * 1024, 4, "TEMP_BUCKET_UPLOAD_PART_SIZE_BYTES"),
            (
                6 * 1024 * 1024 * 1024,
                4,
                "TEMP_BUCKET_UPLOAD_PART_SIZE_BYTES",
            ),
            (64 * 1024 * 1024, 0, "TEMP_BUCKET_UPLOAD_CONCURRENCY"),
        ];
        for (part_size, concurrency, expected) in cases {
            let mut config = config_for_backend("temp_bucket", "my-bucket");
            config.temp_bucket_upload_part_size_bytes = part_size;
            config.temp_bucket_upload_concurrency = concurrency;
            let err = config.staging_backend().unwrap_err().to_string();
            assert!(
                err.contains(expected),
                "part_size={part_size} concurrency={concurrency}: unexpected error: {err}"
            );

            let mut local = config_for_backend("local_disk", "");
            local.temp_bucket_upload_part_size_bytes = part_size;
            local.temp_bucket_upload_concurrency = concurrency;
            assert_eq!(
                local.staging_backend().unwrap(),
                StagingBackendKind::LocalDisk,
                "local_disk mode must not validate unused upload knobs"
            );
        }
    }

    #[test]
    fn test_effective_plaintext_ceiling_is_always_below_the_wall() {
        let mut config = config_for_backend("temp_bucket", "my-bucket");

        // Defaults: 64 MiB parts -> 640 GiB wall -> implicit ceiling at 95%.
        let wall: u64 = 64 * 1024 * 1024 * 10_000;
        assert_eq!(config.effective_plaintext_ceiling(), wall / 100 * 95);

        // An operator ceiling only tightens the implicit one...
        config.staged_plaintext_max_bytes = 1_000_000;
        assert_eq!(config.effective_plaintext_ceiling(), 1_000_000);

        // ...and can never loosen it past the wall.
        config.staged_plaintext_max_bytes = u64::MAX;
        assert_eq!(config.effective_plaintext_ceiling(), wall / 100 * 95);

        // Maximum part size: the wall clamps at S3's 5 TiB object cap.
        config.staged_plaintext_max_bytes = 0;
        config.temp_bucket_upload_part_size_bytes = 5 * 1024 * 1024 * 1024;
        let object_cap: u64 = 5 * 1024 * 1024 * 1024 * 1024;
        assert_eq!(config.effective_plaintext_ceiling(), object_cap / 100 * 95);
    }
}
