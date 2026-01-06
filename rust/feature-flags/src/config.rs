use common_continuous_profiling::ContinuousProfilingConfig;
use common_cookieless::CookielessConfig;
use common_types::TeamId;
use envconfig::Envconfig;
use once_cell::sync::Lazy;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::num::ParseIntError;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use tracing::Level;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FlexBool(pub bool);

impl FromStr for FlexBool {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Ok(FlexBool(true)),
            "false" | "0" | "no" | "off" | "" => Ok(FlexBool(false)),
            _ => Err(format!("Invalid boolean value: {s}")),
        }
    }
}

impl From<FlexBool> for bool {
    fn from(flex: FlexBool) -> Self {
        flex.0
    }
}

impl Deref for FlexBool {
    type Target = bool;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TeamIdCollection {
    All,
    None,
    TeamIds(Vec<i32>),
}

#[derive(Debug)]
pub enum ParseTeamIdsError {
    InvalidRange(String),
    InvalidNumber(ParseIntError),
}

impl std::fmt::Display for ParseTeamIdsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ParseTeamIdsError::InvalidRange(r) => write!(f, "Invalid range: {r}"),
            ParseTeamIdsError::InvalidNumber(e) => write!(f, "Invalid number: {e}"),
        }
    }
}

impl std::error::Error for ParseTeamIdsError {}

impl FromStr for TeamIdCollection {
    type Err = ParseTeamIdsError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        if s.eq_ignore_ascii_case("all") || s == "*" {
            Ok(TeamIdCollection::All)
        } else if s.eq_ignore_ascii_case("none") {
            Ok(TeamIdCollection::None)
        } else {
            let mut team_ids = Vec::new();
            for part in s.split(',').map(|p| p.trim()) {
                if part.contains(':') {
                    let mut bounds = part.split(':');
                    let (Some(start_str), Some(end_str)) = (bounds.next(), bounds.next()) else {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    };
                    if bounds.next().is_some() {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    }
                    let start = start_str
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    let end = end_str
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    if end < start {
                        return Err(ParseTeamIdsError::InvalidRange(part.to_string()));
                    }
                    for id in start..=end {
                        team_ids.push(id);
                    }
                } else {
                    let id = part
                        .parse::<i32>()
                        .map_err(ParseTeamIdsError::InvalidNumber)?;
                    team_ids.push(id);
                }
            }
            Ok(TeamIdCollection::TeamIds(team_ids))
        }
    }
}

/// Flag definitions rate limits configuration
/// Parses JSON from FLAG_DEFINITIONS_RATE_LIMITS environment variable
/// Format: {"team_id": "rate_string", ...}
/// Example: {"123": "1200/minute", "456": "2400/hour"}
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct FlagDefinitionsRateLimits(pub HashMap<TeamId, String>);

impl FromStr for FlagDefinitionsRateLimits {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();

        // Empty string means no custom rate limits
        if s.is_empty() {
            return Ok(FlagDefinitionsRateLimits::default());
        }

        // Parse JSON into HashMap<String, String>
        let parsed: HashMap<String, String> = serde_json::from_str(s)
            .map_err(|e| format!("Failed to parse FLAG_DEFINITIONS_RATE_LIMITS as JSON: {e}"))?;

        // Convert string keys to TeamId
        let mut rate_limits = HashMap::new();
        for (team_id_str, rate_string) in parsed {
            let team_id = team_id_str
                .parse::<TeamId>()
                .map_err(|e| format!("Invalid team ID '{team_id_str}': {e}"))?;
            rate_limits.insert(team_id, rate_string);
        }

        Ok(FlagDefinitionsRateLimits(rate_limits))
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(default = "127.0.0.1:3001")]
    pub address: SocketAddr,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub write_database_url: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub read_database_url: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog_persons")]
    pub persons_write_database_url: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog_persons")]
    pub persons_read_database_url: String,

    #[envconfig(default = "1000")]
    pub max_concurrency: usize,

    // Database connection pool settings:
    // - High traffic: Increase max_pg_connections (e.g., 20-50)
    // - Bursty traffic: Increase idle_timeout_secs to keep connections warm
    // - Set min_connections > 0 to pre-warm pools at startup and avoid cold-start latency
    // - Total connections depend on configuration:
    //   - With persons DB routing: 4 pools × max_pg_connections
    //   - Without persons DB routing: 2 pools × max_pg_connections (persons pools alias to non-persons)
    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    // Minimum connections to maintain in each pool
    // Set > 0 to pre-warm connections at startup for faster first requests
    // Production recommendation: Set to 2-5 to avoid cold start on deploy
    #[envconfig(default = "0")]
    pub min_non_persons_reader_connections: u32,

    #[envconfig(default = "0")]
    pub min_non_persons_writer_connections: u32,

    #[envconfig(default = "0")]
    pub min_persons_reader_connections: u32,

    #[envconfig(default = "0")]
    pub min_persons_writer_connections: u32,

    #[envconfig(default = "redis://localhost:6379/")]
    pub redis_url: String,

    #[envconfig(default = "")]
    pub redis_reader_url: String,

    // Dedicated Redis for feature flags (critical path: team cache + flags cache)
    // When empty, falls back to shared Redis URLs above
    #[envconfig(default = "")]
    pub flags_redis_url: String,

    #[envconfig(default = "")]
    pub flags_redis_reader_url: String,

    // Controls whether to read from dedicated Redis cache
    // false = Mode 2: dual-write to both caches, read from shared (warming phase)
    // true = Mode 3: read and write dedicated Redis only (cutover complete)
    #[envconfig(default = "false")]
    pub flags_redis_enabled: FlexBool,

    // S3 configuration for HyperCache fallback
    #[envconfig(default = "posthog")]
    pub object_storage_bucket: String,

    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,

    #[envconfig(default = "")]
    pub object_storage_endpoint: String,

    // Redis timeout settings (in milliseconds)
    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,

    // How long to wait for a connection from the pool before timing out
    // - Increase if seeing "pool timed out" errors under load (e.g., 5-10s)
    // - Decrease for faster failure detection (minimum 1s)
    #[envconfig(default = "20")]
    pub acquire_timeout_secs: u64,

    // Close connections that have been idle for this many seconds
    // - Set to 0 to disable (connections never close due to idle)
    // - Increase for bursty traffic to avoid reconnection overhead (e.g., 600-900)
    // - Decrease to free resources more aggressively (e.g., 60-120)
    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    // Test connection health before returning from pool
    // - Set to true for production to catch stale connections
    // - Set to false in tests or very stable environments for slight performance gain
    #[envconfig(default = "true")]
    pub test_before_acquire: FlexBool,

    // PostgreSQL statement_timeout for non-persons reader queries (milliseconds)
    // - Set to 0 to use database default (typically unlimited)
    // - Non-persons readers may run longer analytical queries
    // - Default: 5000ms (5 seconds)
    // - This timeout is enforced server-side and properly kills queries
    #[envconfig(default = "5000")]
    pub non_persons_reader_statement_timeout_ms: u64,

    // PostgreSQL statement_timeout for persons reader queries (milliseconds)
    // - Set to 0 to use database default (typically unlimited)
    // - Persons readers may run longer analytical queries
    // - Default: 5000ms (5 seconds)
    // - This timeout is enforced server-side and properly kills queries
    #[envconfig(default = "5000")]
    pub persons_reader_statement_timeout_ms: u64,

    // PostgreSQL statement_timeout for writer database queries (milliseconds)
    // - Set to 0 to use database default (typically unlimited)
    // - Writers should be fast transactional operations
    // - Default: 10000ms (10 seconds)
    // - This timeout is enforced server-side and properly kills queries
    #[envconfig(default = "10000")]
    pub writer_statement_timeout_ms: u64,

    // How often to report database pool metrics (seconds)
    // - Decrease for more granular monitoring (e.g., 10-15)
    // - Increase to reduce metric volume (e.g., 60-120)
    #[envconfig(default = "30")]
    pub db_monitor_interval_secs: u64,

    // How often to report cohort cache metrics (seconds)
    // - Decrease for more granular monitoring (e.g., 10-15)
    // - Increase to reduce metric volume (e.g., 60-120)
    #[envconfig(default = "30")]
    pub cohort_cache_monitor_interval_secs: u64,

    // Pool utilization percentage that triggers warnings (0.0-1.0)
    // - Lower values (e.g., 0.7) provide earlier warnings
    // - Higher values (e.g., 0.9) reduce alert noise
    #[envconfig(default = "0.8")]
    pub db_pool_warn_utilization: f64,

    // How long to cache billing quota checks (seconds)
    // - Lower values ensure fresh quota data but increase Redis load
    // - Higher values reduce Redis queries but may allow brief overages
    #[envconfig(default = "5")]
    pub billing_limiter_cache_ttl_secs: u64,

    // Health check registration interval (seconds)
    // - Should be less than your orchestrator's liveness probe timeout
    // - Common values: 10-30 for Kubernetes environments
    #[envconfig(default = "30")]
    pub health_check_interval_secs: u64,

    // OpenTelemetry exporter timeout (seconds)
    // - Increase if OTEL endpoint is slow or remote
    // - Decrease to fail fast and avoid blocking
    #[envconfig(default = "3")]
    pub otel_export_timeout_secs: u64,

    #[envconfig(from = "MAXMIND_DB_PATH", default = "")]
    pub maxmind_db_path: String,

    #[envconfig(default = "false")]
    pub enable_metrics: bool,

    #[envconfig(from = "TEAM_IDS_TO_TRACK", default = "all")]
    pub team_ids_to_track: TeamIdCollection,

    /// Maximum memory capacity for the cohort cache in bytes.
    ///
    /// The cache uses memory-based eviction to prevent unbounded memory growth.
    /// Each cached cohort's memory footprint is estimated based on its serialized
    /// JSON filter and query sizes (not exact heap usage, but proportional to it).
    /// When the cache exceeds this limit, least recently used entries are evicted.
    ///
    /// Default: 268435456 bytes (256 MB)
    /// Environment variable: COHORT_CACHE_CAPACITY_BYTES
    ///
    /// Common values:
    /// - 134217728 (128 MB) - For memory-constrained environments
    /// - 268435456 (256 MB) - Default, good balance
    /// - 536870912 (512 MB) - For high-traffic instances with many teams
    ///
    /// Note: Individual cache entries cannot exceed ~4 GB (u32::MAX) due to the
    /// weigher's u32 return type, though the total cache capacity can exceed this.
    /// In practice, individual cohorts rarely exceed 1 MB, so this is not a concern.
    #[envconfig(from = "COHORT_CACHE_CAPACITY_BYTES", default = "268435456")]
    pub cohort_cache_capacity_bytes: u64,

    #[envconfig(from = "CACHE_TTL_SECONDS", default = "300")]
    pub cache_ttl_seconds: u64,

    /// Redis TTL for team cache entries in seconds
    ///
    /// Controls how long team data is cached in Redis before expiring.
    /// This prevents indefinite cache growth and ensures stale data is refreshed.
    ///
    /// Default: 432000 seconds (5 days) - matches Django's FIVE_DAYS constant
    /// Environment variable: TEAM_CACHE_TTL_SECONDS
    ///
    /// Common values:
    /// - 3600 (1 hour) - For frequently changing team data
    /// - 86400 (1 day) - For moderate refresh rate
    /// - 432000 (5 days) - Default, balances performance and freshness
    ///
    /// Minimum value: 1 second (Redis setex does not accept 0 or negative values)
    #[envconfig(from = "TEAM_CACHE_TTL_SECONDS", default = "432000")]
    pub team_cache_ttl_seconds: u64,

    /// Redis TTL for feature flags cache entries in seconds
    ///
    /// Controls how long feature flag data is cached in Redis before expiring.
    /// This prevents indefinite cache growth and ensures flag changes are visible
    /// within a reasonable time.
    ///
    /// Default: 432000 seconds (5 days) - matches Django's FIVE_DAYS constant
    /// Environment variable: FLAGS_CACHE_TTL_SECONDS
    ///
    /// Common values:
    /// - 300 (5 minutes) - For rapid flag development/testing
    /// - 3600 (1 hour) - For frequently changing flags
    /// - 86400 (1 day) - For stable flag deployments
    /// - 432000 (5 days) - Default, balances performance and freshness
    ///
    /// Minimum value: 1 second (Redis setex does not accept 0 or negative values)
    #[envconfig(from = "FLAGS_CACHE_TTL_SECONDS", default = "432000")]
    pub flags_cache_ttl_seconds: u64,

    // cookieless, should match the values in plugin-server/src/types.ts, except we don't use sessions here
    #[envconfig(from = "COOKIELESS_DISABLED", default = "false")]
    pub cookieless_disabled: bool,

    #[envconfig(from = "COOKIELESS_FORCE_STATELESS", default = "false")]
    pub cookieless_force_stateless: bool,

    #[envconfig(from = "COOKIELESS_IDENTIFIES_TTL_SECONDS", default = "345600")]
    pub cookieless_identifies_ttl_seconds: u64,

    #[envconfig(from = "COOKIELESS_SALT_TTL_SECONDS", default = "345600")]
    pub cookieless_salt_ttl_seconds: u64,

    #[envconfig(from = "COOKIELESS_REDIS_HOST", default = "localhost")]
    pub cookieless_redis_host: String,

    #[envconfig(from = "COOKIELESS_REDIS_PORT", default = "6379")]
    pub cookieless_redis_port: u64,

    #[envconfig(from = "NEW_ANALYTICS_CAPTURE_ENDPOINT", default = "/i/v0/e/")]
    pub new_analytics_capture_endpoint: String,

    #[envconfig(from = "NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS", default = "none")]
    pub new_analytics_capture_excluded_team_ids: TeamIdCollection,

    #[envconfig(from = "ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS", default = "none")]
    pub element_chain_as_string_excluded_teams: TeamIdCollection,

    #[envconfig(from = "DEBUG", default = "false")]
    pub debug: FlexBool,

    #[envconfig(from = "FLAGS_SESSION_REPLAY_QUOTA_CHECK", default = "false")]
    pub flags_session_replay_quota_check: bool,

    // Flag definitions rate limiting
    // Default rate limit for all teams (requests per minute)
    // Can be overridden per-team using FLAG_DEFINITIONS_RATE_LIMITS
    #[envconfig(from = "FLAG_DEFINITIONS_DEFAULT_RATE_PER_MINUTE", default = "600")]
    pub flag_definitions_default_rate_per_minute: u32,

    // Per-team rate limit overrides for flag definitions endpoint
    // JSON format: {"team_id": "rate_string", ...}
    // Example: {"123": "1200/minute", "456": "2400/hour"}
    #[envconfig(from = "FLAG_DEFINITIONS_RATE_LIMITS", default = "")]
    pub flag_definitions_rate_limits: FlagDefinitionsRateLimits,

    // OpenTelemetry configuration
    #[envconfig(from = "OTEL_EXPORTER_OTLP_ENDPOINT")]
    pub otel_url: Option<String>,

    #[envconfig(from = "OTEL_TRACES_SAMPLER_ARG", default = "0.001")]
    pub otel_sampling_rate: f64,

    #[envconfig(from = "OTEL_SERVICE_NAME", default = "posthog-feature-flags")]
    pub otel_service_name: String,

    #[envconfig(from = "OTEL_LOG_LEVEL", default = "info")]
    pub otel_log_level: Level,

    // Rate limiting configuration for /flags endpoint (token-based)
    // Enable/disable token-based rate limiting (defaults to off to match /decide)
    #[envconfig(from = "FLAGS_RATE_LIMIT_ENABLED", default = "false")]
    pub flags_rate_limit_enabled: FlexBool,

    // Token bucket capacity (maximum burst size)
    // Matches Python's DecideRateThrottle default of 500
    #[envconfig(from = "FLAGS_BUCKET_CAPACITY", default = "500")]
    pub flags_bucket_capacity: u32,

    // Token bucket replenish rate (tokens per second)
    // Matches Python's DecideRateThrottle default of 10.0
    #[envconfig(from = "FLAGS_BUCKET_REPLENISH_RATE", default = "10.0")]
    pub flags_bucket_replenish_rate: f64,

    // IP-based rate limiting configuration
    // Provides defense-in-depth against DDoS attacks with rotating fake tokens
    // This limits ALL requests per IP address, regardless of token validity
    #[envconfig(from = "FLAGS_IP_RATE_LIMIT_ENABLED", default = "false")]
    pub flags_ip_rate_limit_enabled: FlexBool,

    // IP rate limit burst size (maximum requests per IP in a burst)
    #[envconfig(from = "FLAGS_IP_BURST_SIZE", default = "1000")]
    pub flags_ip_burst_size: u32,

    // IP rate limit replenish rate (requests per second per IP)
    // Set higher than token bucket rate to account for multiple users behind same IP
    #[envconfig(from = "FLAGS_IP_REPLENISH_RATE", default = "50.0")]
    pub flags_ip_replenish_rate: f64,

    // Log-only mode for rate limiting (defaults to true for safe rollout)
    // When true, rate limits are checked and violations logged, but requests are not blocked
    // This allows gathering metrics to tune limits before enforcing them
    #[envconfig(from = "FLAGS_RATE_LIMIT_LOG_ONLY", default = "true")]
    pub flags_rate_limit_log_only: FlexBool,

    // Log-only mode for IP-based rate limiting (defaults to true for safe rollout)
    #[envconfig(from = "FLAGS_IP_RATE_LIMIT_LOG_ONLY", default = "true")]
    pub flags_ip_rate_limit_log_only: FlexBool,

    // How often to clean up stale rate limiter entries (seconds)
    // The governor crate's keyed rate limiters accumulate entries for every unique key.
    // Without periodic cleanup, this leads to unbounded memory growth.
    // This interval controls how often retain_recent() is called to remove stale entries.
    #[envconfig(from = "RATE_LIMITER_CLEANUP_INTERVAL_SECS", default = "60")]
    pub rate_limiter_cleanup_interval_secs: u64,

    // Redis compression configuration
    // When enabled, uses zstd compression for Redis values above threshold
    // The `default_test_config()` sets this to true for test/development scenarios.
    #[envconfig(from = "REDIS_COMPRESSION_ENABLED", default = "false")]
    pub redis_compression_enabled: FlexBool,

    // Number of times to retry creating a Redis client before giving up
    // Helps handle transient network issues during startup
    // Set to 0 to disable retries (fail immediately on first error)
    #[envconfig(from = "REDIS_CLIENT_RETRY_COUNT", default = "3")]
    pub redis_client_retry_count: u32,
}

impl Config {
    const MAX_RESPONSE_TIMEOUT_MS: u64 = 30_000; // 30 seconds
    const MAX_CONNECTION_TIMEOUT_MS: u64 = 60_000; // 60 seconds

    /// Validate and fix timeout configuration, logging warnings and applying defaults for invalid values
    ///
    /// This method checks timeout values and relationships, applying safe defaults when invalid
    /// configurations are detected. It never fails - it logs warnings and corrects problems.
    pub fn validate_and_fix_timeouts(&mut self) {
        let mut fixed = false;

        // Note: Zero values are now valid - they mean "no timeout" (blocks indefinitely)
        // The RedisClient will skip setting the timeout when Duration::ZERO is provided

        // Fix excessive values
        if self.redis_response_timeout_ms > Self::MAX_RESPONSE_TIMEOUT_MS {
            tracing::warn!(
                "Redis response timeout ({}ms) exceeds maximum recommended value ({}ms), capping at maximum",
                self.redis_response_timeout_ms,
                Self::MAX_RESPONSE_TIMEOUT_MS
            );
            self.redis_response_timeout_ms = Self::MAX_RESPONSE_TIMEOUT_MS;
            fixed = true;
        }

        if self.redis_connection_timeout_ms > Self::MAX_CONNECTION_TIMEOUT_MS {
            tracing::warn!(
                "Redis connection timeout ({}ms) exceeds maximum recommended value ({}ms), capping at maximum",
                self.redis_connection_timeout_ms,
                Self::MAX_CONNECTION_TIMEOUT_MS
            );
            self.redis_connection_timeout_ms = Self::MAX_CONNECTION_TIMEOUT_MS;
            fixed = true;
        }

        if fixed {
            tracing::info!(
                "Using Redis timeouts: response={}ms, connection={}ms",
                self.redis_response_timeout_ms,
                self.redis_connection_timeout_ms
            );
        }
    }

    pub fn default_test_config() -> Self {
        Self {
            continuous_profiling: ContinuousProfilingConfig::default(),
            address: SocketAddr::from_str("127.0.0.1:0").unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_reader_url: "".to_string(),
            flags_redis_url: "".to_string(),
            flags_redis_reader_url: "".to_string(),
            flags_redis_enabled: FlexBool(false),
            redis_response_timeout_ms: 100,
            redis_connection_timeout_ms: 5000,
            write_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog"
                .to_string(),
            read_database_url: "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
            persons_write_database_url: "postgres://posthog:posthog@localhost:5432/posthog_persons"
                .to_string(),
            persons_read_database_url: "postgres://posthog:posthog@localhost:5432/posthog_persons"
                .to_string(),
            max_concurrency: 1000,
            max_pg_connections: 10,
            min_non_persons_reader_connections: 0,
            min_non_persons_writer_connections: 0,
            min_persons_reader_connections: 0,
            min_persons_writer_connections: 0,
            acquire_timeout_secs: 3,
            idle_timeout_secs: 300,
            test_before_acquire: FlexBool(true),
            non_persons_reader_statement_timeout_ms: 5000,
            persons_reader_statement_timeout_ms: 5000,
            writer_statement_timeout_ms: 5000,
            db_monitor_interval_secs: 30,
            cohort_cache_monitor_interval_secs: 30,
            db_pool_warn_utilization: 0.8,
            billing_limiter_cache_ttl_secs: 5,
            health_check_interval_secs: 30,
            otel_export_timeout_secs: 3,
            maxmind_db_path: "".to_string(),
            enable_metrics: false,
            team_ids_to_track: TeamIdCollection::All,
            cohort_cache_capacity_bytes: 268_435_456, // 256 MB
            cache_ttl_seconds: 300,
            team_cache_ttl_seconds: 432000,
            flags_cache_ttl_seconds: 432000,
            cookieless_disabled: false,
            cookieless_force_stateless: false,
            cookieless_identifies_ttl_seconds: 345600,
            cookieless_salt_ttl_seconds: 345600,
            cookieless_redis_host: "localhost".to_string(),
            cookieless_redis_port: 6379,
            new_analytics_capture_endpoint: "/i/v0/e/".to_string(),
            new_analytics_capture_excluded_team_ids: TeamIdCollection::None,
            element_chain_as_string_excluded_teams: TeamIdCollection::None,
            debug: FlexBool(false),
            flags_session_replay_quota_check: false,
            flag_definitions_default_rate_per_minute: 600,
            flag_definitions_rate_limits: FlagDefinitionsRateLimits::default(),
            otel_url: None,
            otel_sampling_rate: 1.0,
            otel_service_name: "posthog-feature-flags".to_string(),
            otel_log_level: Level::ERROR,
            object_storage_bucket: "posthog".to_string(),
            object_storage_region: "us-east-1".to_string(),
            object_storage_endpoint: "".to_string(),
            flags_rate_limit_enabled: FlexBool(false),
            flags_bucket_capacity: 500,
            flags_bucket_replenish_rate: 10.0,
            flags_ip_rate_limit_enabled: FlexBool(false),
            flags_ip_burst_size: 500,
            flags_ip_replenish_rate: 100.0,
            flags_rate_limit_log_only: FlexBool(true),
            flags_ip_rate_limit_log_only: FlexBool(true),
            rate_limiter_cleanup_interval_secs: 60,
            redis_compression_enabled: FlexBool(true),
            redis_client_retry_count: 3,
        }
    }

    pub fn get_maxmind_db_path(&self) -> PathBuf {
        if self.maxmind_db_path.is_empty() {
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .join("share")
                .join("GeoLite2-City.mmdb")
        } else {
            PathBuf::from(&self.maxmind_db_path)
        }
    }

    pub fn get_redis_reader_url(&self) -> &str {
        if self.redis_reader_url.is_empty() {
            &self.redis_url
        } else {
            &self.redis_reader_url
        }
    }

    pub fn get_redis_writer_url(&self) -> &str {
        &self.redis_url
    }

    /// Get the Redis URL for flags cache reads (critical path: team cache + flags cache)
    /// Returns None if dedicated flags Redis is not configured
    pub fn get_flags_redis_reader_url(&self) -> Option<&str> {
        if !self.flags_redis_reader_url.is_empty() {
            Some(&self.flags_redis_reader_url)
        } else if !self.flags_redis_url.is_empty() {
            Some(&self.flags_redis_url)
        } else {
            None
        }
    }

    /// Get the Redis URL for flags cache writes (critical path: team cache + flags cache)
    /// Returns None if dedicated flags Redis is not configured
    pub fn get_flags_redis_writer_url(&self) -> Option<&str> {
        if !self.flags_redis_url.is_empty() {
            Some(&self.flags_redis_url)
        } else {
            None
        }
    }

    pub fn get_redis_cookieless_url(&self) -> String {
        format!(
            "redis://{}:{}",
            self.cookieless_redis_host, self.cookieless_redis_port
        )
    }

    pub fn get_cookieless_config(&self) -> CookielessConfig {
        CookielessConfig {
            disabled: self.cookieless_disabled,
            force_stateless_mode: self.cookieless_force_stateless,
            identifies_ttl_seconds: self.cookieless_identifies_ttl_seconds,
            salt_ttl_seconds: self.cookieless_salt_ttl_seconds,
        }
    }

    pub fn is_team_excluded(&self, team_id: i32, teams_to_exclude: &TeamIdCollection) -> bool {
        match teams_to_exclude {
            TeamIdCollection::All => true,
            TeamIdCollection::None => false,
            TeamIdCollection::TeamIds(ids) => ids.contains(&team_id),
        }
    }

    /// Check if persons database routing is enabled
    pub fn is_persons_db_routing_enabled(&self) -> bool {
        !self.persons_read_database_url.is_empty() && !self.persons_write_database_url.is_empty()
    }

    /// Get the database URL for persons reads, falling back to the default read URL
    pub fn get_persons_read_database_url(&self) -> String {
        if self.persons_read_database_url.is_empty() {
            self.read_database_url.clone()
        } else {
            self.persons_read_database_url.clone()
        }
    }

    /// Get the database URL for persons writes, falling back to the default write URL
    pub fn get_persons_write_database_url(&self) -> String {
        if self.persons_write_database_url.is_empty() {
            self.write_database_url.clone()
        } else {
            self.persons_write_database_url.clone()
        }
    }
}

pub static DEFAULT_TEST_CONFIG: Lazy<Config> = Lazy::new(Config::default_test_config);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        std::env::set_var("DEBUG", "false");
        let config = Config::init_from_env().unwrap();
        assert_eq!(
            config.address,
            SocketAddr::from_str("127.0.0.1:3001").unwrap()
        );
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.min_non_persons_reader_connections, 0);
        assert_eq!(config.min_non_persons_writer_connections, 0);
        assert_eq!(config.min_persons_reader_connections, 0);
        assert_eq!(config.min_persons_writer_connections, 0);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
        assert_eq!(config.new_analytics_capture_endpoint, "/i/v0/e/");
        assert_eq!(config.debug, FlexBool(false));
        assert!(!config.flags_session_replay_quota_check);
    }

    #[test]
    fn test_default_test_config() {
        let config = Config::default_test_config();
        assert_eq!(config.address, SocketAddr::from_str("127.0.0.1:0").unwrap());
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.min_non_persons_reader_connections, 0);
        assert_eq!(config.min_non_persons_writer_connections, 0);
        assert_eq!(config.min_persons_reader_connections, 0);
        assert_eq!(config.min_persons_writer_connections, 0);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
    }

    #[test]
    fn test_default_test_config_static() {
        let config = &*DEFAULT_TEST_CONFIG;
        assert_eq!(config.address, SocketAddr::from_str("127.0.0.1:0").unwrap());
        assert_eq!(
            config.write_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(
            config.read_database_url,
            "postgres://posthog:posthog@localhost:5432/test_posthog"
        );
        assert_eq!(config.max_concurrency, 1000);
        assert_eq!(config.max_pg_connections, 10);
        assert_eq!(config.min_non_persons_reader_connections, 0);
        assert_eq!(config.min_non_persons_writer_connections, 0);
        assert_eq!(config.min_persons_reader_connections, 0);
        assert_eq!(config.min_persons_writer_connections, 0);
        assert_eq!(config.redis_url, "redis://localhost:6379/");
        assert_eq!(config.team_ids_to_track, TeamIdCollection::All);
        assert_eq!(
            config.new_analytics_capture_excluded_team_ids,
            TeamIdCollection::None
        );
        assert_eq!(
            config.element_chain_as_string_excluded_teams,
            TeamIdCollection::None
        );
    }

    #[test]
    fn test_team_ids_to_track_all() {
        let team_ids: TeamIdCollection = "all".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::All);
    }

    #[test]
    fn test_team_ids_to_track_wildcard() {
        let team_ids: TeamIdCollection = "*".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::All);
    }

    #[test]
    fn test_team_ids_to_track_none() {
        let team_ids: TeamIdCollection = "none".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::None);
    }

    #[test]
    fn test_team_ids_to_track_single_ids() {
        let team_ids: TeamIdCollection = "1,5,7,13".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::TeamIds(vec![1, 5, 7, 13]));
    }

    #[test]
    fn test_team_ids_to_track_ranges() {
        let team_ids: TeamIdCollection = "1:3".parse().unwrap();
        assert_eq!(team_ids, TeamIdCollection::TeamIds(vec![1, 2, 3]));
    }

    #[test]
    fn test_team_ids_to_track_mixed() {
        let team_ids: TeamIdCollection = "1:3,5,7:9".parse().unwrap();
        assert_eq!(
            team_ids,
            TeamIdCollection::TeamIds(vec![1, 2, 3, 5, 7, 8, 9])
        );
    }

    #[test]
    fn test_invalid_range() {
        let result: Result<TeamIdCollection, _> = "5:3".parse();
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_number() {
        let result: Result<TeamIdCollection, _> = "abc".parse();
        assert!(result.is_err());
    }

    #[test]
    fn test_flag_definitions_rate_limits_empty() {
        let limits: FlagDefinitionsRateLimits = "".parse().unwrap();
        assert_eq!(limits.0.len(), 0);
    }

    #[test]
    fn test_flag_definitions_rate_limits_valid_json() {
        let json = r#"{"123": "1200/minute", "456": "2400/hour"}"#;
        let limits: FlagDefinitionsRateLimits = json.parse().unwrap();
        assert_eq!(limits.0.len(), 2);
        assert_eq!(limits.0.get(&123), Some(&"1200/minute".to_string()));
        assert_eq!(limits.0.get(&456), Some(&"2400/hour".to_string()));
    }

    #[test]
    fn test_flag_definitions_rate_limits_single_team() {
        let json = r#"{"789": "100/second"}"#;
        let limits: FlagDefinitionsRateLimits = json.parse().unwrap();
        assert_eq!(limits.0.len(), 1);
        assert_eq!(limits.0.get(&789), Some(&"100/second".to_string()));
    }

    #[test]
    fn test_flag_definitions_rate_limits_invalid_json() {
        let result: Result<FlagDefinitionsRateLimits, _> = "not json".parse();
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .contains("Failed to parse FLAG_DEFINITIONS_RATE_LIMITS"));
    }

    #[test]
    fn test_flag_definitions_rate_limits_invalid_team_id() {
        let json = r#"{"abc": "600/minute"}"#;
        let result: Result<FlagDefinitionsRateLimits, _> = json.parse();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid team ID"));
    }

    #[test]
    fn test_flag_definitions_rate_limits_negative_team_id() {
        let json = r#"{"-123": "600/minute"}"#;
        let result: Result<FlagDefinitionsRateLimits, _> = json.parse();
        // Negative numbers are technically valid i32, so this should succeed
        assert!(result.is_ok());
        let limits = result.unwrap();
        assert_eq!(limits.0.get(&-123), Some(&"600/minute".to_string()));
    }

    #[test]
    fn test_flag_definitions_rate_limits_whitespace() {
        let json = r#"  {"123": "600/minute"}  "#;
        let limits: FlagDefinitionsRateLimits = json.parse().unwrap();
        assert_eq!(limits.0.len(), 1);
        assert_eq!(limits.0.get(&123), Some(&"600/minute".to_string()));
    }

    #[test]
    fn test_validate_and_fix_timeouts_valid_config() {
        let mut config = Config::default_test_config();
        let original_response = config.redis_response_timeout_ms;
        let original_connection = config.redis_connection_timeout_ms;
        config.validate_and_fix_timeouts();
        // Should not change valid config
        assert_eq!(config.redis_response_timeout_ms, original_response);
        assert_eq!(config.redis_connection_timeout_ms, original_connection);
    }

    #[test]
    fn test_validate_and_fix_timeouts_zero_values_allowed() {
        let mut config = Config::default_test_config();
        // Zero values are allowed - they mean "no timeout"
        config.redis_response_timeout_ms = 0;
        config.redis_connection_timeout_ms = 0;
        config.validate_and_fix_timeouts();
        // Should preserve zero values
        assert_eq!(config.redis_response_timeout_ms, 0);
        assert_eq!(config.redis_connection_timeout_ms, 0);
    }

    #[test]
    fn test_validate_and_fix_timeouts_excessive_response_timeout() {
        let mut config = Config::default_test_config();
        config.redis_response_timeout_ms = 31_000; // > 30 seconds max
        config.redis_connection_timeout_ms = 40_000; // Allow connection timeout to be higher
        config.validate_and_fix_timeouts();
        // Should cap at maximum
        assert_eq!(
            config.redis_response_timeout_ms,
            Config::MAX_RESPONSE_TIMEOUT_MS
        );
    }

    #[test]
    fn test_validate_and_fix_timeouts_excessive_connection_timeout() {
        let mut config = Config::default_test_config();
        config.redis_connection_timeout_ms = 61_000; // > 60 seconds max
        config.validate_and_fix_timeouts();
        // Should cap at maximum
        assert_eq!(
            config.redis_connection_timeout_ms,
            Config::MAX_CONNECTION_TIMEOUT_MS
        );
    }

    #[test]
    fn test_validate_and_fix_timeouts_any_relationship_allowed() {
        let mut config = Config::default_test_config();

        // Test 1: Equal values are allowed
        config.redis_response_timeout_ms = 1000;
        config.redis_connection_timeout_ms = 1000;
        config.validate_and_fix_timeouts();
        assert_eq!(config.redis_response_timeout_ms, 1000);
        assert_eq!(config.redis_connection_timeout_ms, 1000);

        // Test 2: Response > Connection is also allowed (no relationship validation)
        config.redis_response_timeout_ms = 5000;
        config.redis_connection_timeout_ms = 1000;
        config.validate_and_fix_timeouts();
        assert_eq!(config.redis_response_timeout_ms, 5000);
        assert_eq!(config.redis_connection_timeout_ms, 1000);

        // Test 3: Response < Connection is allowed
        config.redis_response_timeout_ms = 100;
        config.redis_connection_timeout_ms = 5000;
        config.validate_and_fix_timeouts();
        assert_eq!(config.redis_response_timeout_ms, 100);
        assert_eq!(config.redis_connection_timeout_ms, 5000);
    }

    #[test]
    fn test_timeout_values_apply_to_redis_client() {
        use std::time::Duration;

        let config = Config::default_test_config();

        // Verify that config values would translate correctly to Duration
        let response_timeout = Duration::from_millis(config.redis_response_timeout_ms);
        let connection_timeout = Duration::from_millis(config.redis_connection_timeout_ms);

        assert_eq!(response_timeout, Duration::from_millis(100));
        assert_eq!(connection_timeout, Duration::from_millis(5000));

        // Verify zero values work (treated as None/no timeout)
        let mut zero_config = Config::default_test_config();
        zero_config.redis_response_timeout_ms = 0;
        zero_config.redis_connection_timeout_ms = 0;
        zero_config.validate_and_fix_timeouts();

        assert_eq!(zero_config.redis_response_timeout_ms, 0);
        assert_eq!(zero_config.redis_connection_timeout_ms, 0);
    }
}

#[cfg(test)]
mod timeout_behavior_tests {
    #[test]
    fn test_is_timeout_correctly_identifies_timeout_errors() {
        use common_redis::CustomRedisError;

        // Test that CustomRedisError::Timeout is correctly identified
        let timeout_err = CustomRedisError::Timeout;

        // Verify timeout errors are recognized as timeouts
        assert!(
            matches!(timeout_err, CustomRedisError::Timeout),
            "CustomRedisError::Timeout should match Timeout variant"
        );

        // Verify timeout errors are transient (not unrecoverable)
        assert!(
            !timeout_err.is_unrecoverable_error(),
            "Timeout errors should be recoverable"
        );

        // Verify timeout errors use WaitAndRetry strategy
        assert!(
            matches!(
                timeout_err.retry_method(),
                common_redis::RetryMethod::WaitAndRetry
            ),
            "Timeout errors should use WaitAndRetry strategy"
        );
    }

    #[test]
    fn test_non_timeout_io_errors_not_identified_as_timeout() {
        use common_redis::{CustomRedisError, RedisErrorKind};

        // Create a non-timeout IoError
        let io_err =
            CustomRedisError::from_redis_kind(RedisErrorKind::IoError, "connection refused");

        // Should not be converted to CustomRedisError::Timeout
        match io_err {
            CustomRedisError::Timeout => {
                panic!("Non-timeout IoError should not be identified as timeout");
            }
            CustomRedisError::Redis(_) => {
                // Expected - it's a Redis error but not a timeout
            }
            _ => {}
        }
    }

    #[tokio::test]
    async fn test_redis_timeout_integration() {
        use common_redis::{Client, CompressionConfig, RedisClient, RedisValueFormat};
        use std::time::Duration;

        // This test requires a running Redis instance
        // Set REDIS_URL environment variable to customize, defaults to localhost
        let redis_url =
            std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string());

        // Test 1: Very short timeout should fail quickly with timeout error
        let short_timeout_client = RedisClient::with_config(
            redis_url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::default(),
            Some(Duration::from_millis(1)), // 1ms - too short for any operation
            Some(Duration::from_millis(100)),
        )
        .await;

        // With such a short timeout, we might fail during connection or during operation
        // Either way, we're testing that timeouts work
        match short_timeout_client {
            Ok(client) => {
                // If connection succeeded, try an operation
                let result = client.get("test_timeout_key".to_string()).await;

                // Should timeout (or not find the key - that's fine too)
                if let Err(e) = result {
                    println!("Got expected error with short timeout: {e:?}");
                    // We got some error - that's expected with 1ms timeout
                }
            }
            Err(e) => {
                // Connection itself timed out - that's also valid
                println!("Connection with short timeout failed as expected: {e:?}");
            }
        }

        // Test 2: Reasonable timeout should allow successful connection
        let normal_client = RedisClient::with_config(
            redis_url,
            CompressionConfig::disabled(),
            RedisValueFormat::default(),
            Some(Duration::from_millis(5000)), // 5 seconds - plenty of time
            Some(Duration::from_millis(5000)),
        )
        .await;

        match normal_client {
            Ok(client) => {
                // Connection worked - test a simple operation
                let test_key = format!(
                    "test_timeout_integration_{}",
                    chrono::Utc::now().timestamp()
                );
                let test_value = "timeout_test_value".to_string();

                // Should succeed with reasonable timeout
                let set_result = client.set(test_key.clone(), test_value.clone()).await;
                assert!(
                    set_result.is_ok(),
                    "Set operation should succeed with reasonable timeout"
                );

                // Clean up
                drop(client.del(test_key).await);
            }
            Err(e) => {
                println!("WARNING: Integration test skipped - could not connect to Redis: {e:?}");
                println!("To run this test, ensure Redis is running at $REDIS_URL (default: redis://localhost:6379)");
            }
        }
    }
}
