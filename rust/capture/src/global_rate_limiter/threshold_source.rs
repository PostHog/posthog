use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{Client as RedisClient, CustomRedisError};
use metrics::{counter, gauge};
use tokio::time::interval;
use tracing::{error, info, warn};

use super::GlobalRateLimiter;

const REDIS_FETCH_COUNTER: &str = "capture_global_rate_limit_thresholds_redis_fetch";
const LOADED_COUNT_GAUGE: &str = "capture_global_rate_limit_thresholds_loaded_count";
const LAST_REFRESH_GAUGE: &str = "capture_global_rate_limit_thresholds_last_refresh_timestamp";

/// Parse the dynamic-threshold JSON blob written by Django.
///
/// The blob is a flat JSON object mapping the fully-resolved key (either
/// `token` or `token:distinct_id`) to its threshold, e.g.
/// `{"phc_abc": 1000, "phc_abc:noisy_user": 50}`.
pub fn parse_thresholds(json_str: &str) -> Result<HashMap<String, u64>, CustomRedisError> {
    serde_json::from_str(json_str)
        .map_err(|e| CustomRedisError::ParseError(format!("Failed to parse thresholds JSON: {e}")))
}

/// Repository for fetching the dynamic custom-threshold map from storage.
/// Abstracted so the refresh loop can be unit-tested with a mock.
#[async_trait]
pub trait ThresholdRepository: Send + Sync {
    /// Fetch the current custom-threshold map. `Ok(None)` means the key is
    /// absent (no custom thresholds configured); `Err` means the fetch failed.
    async fn get_thresholds(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError>;
}

/// Redis-backed implementation. Reads a single key holding the plain JSON blob
/// written by Django (UTF-8, no compression), mirroring the event-restrictions
/// repository.
pub struct RedisThresholdRepository {
    redis: Arc<dyn RedisClient + Send + Sync>,
    key: String,
}

impl RedisThresholdRepository {
    /// Build a repository from an existing Redis client. Lets callers share the
    /// event-restrictions Redis client rather than opening a second pool.
    pub fn from_client(redis: Arc<dyn RedisClient + Send + Sync>, key: String) -> Self {
        Self { redis, key }
    }

    /// Build a repository that owns a fresh UTF-8 Redis client for `redis_url`.
    /// Retained for standalone use and tests; production wiring prefers
    /// `from_client` to reuse the event-restrictions client.
    pub async fn new(
        redis_url: String,
        key: String,
        response_timeout: Option<Duration>,
        connection_timeout: Option<Duration>,
    ) -> Result<Self, CustomRedisError> {
        let redis = Arc::new(
            common_redis::RedisClient::with_config(
                redis_url,
                common_redis::CompressionConfig::disabled(),
                common_redis::RedisValueFormat::Utf8,
                response_timeout,
                connection_timeout,
            )
            .await?,
        );
        Ok(Self { redis, key })
    }
}

#[async_trait]
impl ThresholdRepository for RedisThresholdRepository {
    async fn get_thresholds(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError> {
        let json_str = match self.redis.get(self.key.clone()).await {
            Ok(s) => s,
            Err(CustomRedisError::NotFound) => {
                counter!(REDIS_FETCH_COUNTER, "result" => "not_found").increment(1);
                return Ok(None);
            }
            Err(e) => {
                counter!(REDIS_FETCH_COUNTER, "result" => "error").increment(1);
                warn!(key = %self.key, error = %e, "Failed to fetch custom rate-limit thresholds from Redis");
                return Err(e);
            }
        };

        match parse_thresholds(&json_str) {
            Ok(map) => {
                counter!(REDIS_FETCH_COUNTER, "result" => "success").increment(1);
                Ok(Some(map))
            }
            Err(e) => {
                counter!(REDIS_FETCH_COUNTER, "result" => "parse_error").increment(1);
                warn!(key = %self.key, error = %e, "Failed to parse custom rate-limit thresholds from Redis");
                Err(e)
            }
        }
    }
}

/// Fetch thresholds once and push them into the limiter.
///
/// Returns `true` to keep the current repository, `false` if the fetch failed
/// (dead connection) and the caller should reconnect on the next tick. On any
/// failure the limiter keeps its current thresholds (fail-static). Redis is
/// authoritative when reachable: an absent key clears custom thresholds.
async fn refresh_once(limiter: &GlobalRateLimiter, repository: &dyn ThresholdRepository) -> bool {
    match repository.get_thresholds().await {
        Ok(Some(map)) => {
            let count = map.len();
            limiter.replace_custom_keys(map);
            gauge!(LOADED_COUNT_GAUGE).set(count as f64);
            gauge!(LAST_REFRESH_GAUGE).set(chrono::Utc::now().timestamp() as f64);
            true
        }
        Ok(None) => {
            limiter.replace_custom_keys(HashMap::new());
            gauge!(LOADED_COUNT_GAUGE).set(0.0);
            gauge!(LAST_REFRESH_GAUGE).set(chrono::Utc::now().timestamp() as f64);
            true
        }
        Err(e) => {
            error!(error = %e, "Failed to refresh custom rate-limit thresholds, keeping current values");
            false
        }
    }
}

/// Refresh the limiter's custom thresholds from Redis until shutdown.
///
/// Models the event-restrictions refresh task: the repository is created lazily
/// via `create_repository` so a Redis outage at startup leaves the limiter on
/// its seeded (CSV) thresholds and retries each tick. `tokio::time::interval`
/// ticks immediately, so the first fetch happens without delay.
pub async fn start_refresh_task<F, Fut>(
    limiter: Arc<GlobalRateLimiter>,
    create_repository: F,
    refresh_interval: Duration,
    shutdown_handle: lifecycle::Handle,
) where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = Result<Arc<dyn ThresholdRepository>, CustomRedisError>>,
{
    let mut interval = interval(refresh_interval);
    let mut repository: Option<Arc<dyn ThresholdRepository>> = None;

    loop {
        tokio::select! {
            _ = shutdown_handle.shutdown_recv() => {
                info!("Global rate limit custom-threshold refresh task shutting down");
                break;
            }
            _ = interval.tick() => {
                if repository.is_none() {
                    match create_repository().await {
                        Ok(repo) => {
                            info!("Global rate limit custom thresholds connected to Redis");
                            repository = Some(repo);
                        }
                        Err(e) => {
                            error!(error = %e, "Failed to connect to custom-threshold Redis, will retry");
                            continue;
                        }
                    }
                }

                if !refresh_once(limiter.as_ref(), repository.as_ref().unwrap().as_ref()).await {
                    repository = None;
                }
            }
        }
    }
}

#[cfg(test)]
pub mod testing {
    use super::*;
    use tokio::sync::Mutex;

    /// Mock repository for unit-testing the refresh path.
    pub struct MockThresholdRepository {
        result: Mutex<Result<Option<HashMap<String, u64>>, CustomRedisError>>,
    }

    impl MockThresholdRepository {
        pub fn with_thresholds(map: Option<HashMap<String, u64>>) -> Self {
            Self {
                result: Mutex::new(Ok(map)),
            }
        }

        pub fn with_error(error: CustomRedisError) -> Self {
            Self {
                result: Mutex::new(Err(error)),
            }
        }
    }

    #[async_trait]
    impl ThresholdRepository for MockThresholdRepository {
        async fn get_thresholds(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError> {
            self.result.lock().await.clone()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::testing::MockThresholdRepository;
    use super::*;

    fn test_limiter() -> Arc<GlobalRateLimiter> {
        // Feature-on wrapper: CSV seeds one token-level override, hierarchical
        // resolver enabled so token:distinct_id falls back to token.
        Arc::new(GlobalRateLimiter::for_test_with_dynamic_thresholds(Some(
            "phc_seed=7",
        )))
    }

    #[test]
    fn test_parse_thresholds_flat_object() {
        let json = r#"{"phc_abc": 1000, "phc_abc:noisy": 50}"#;
        let map = parse_thresholds(json).unwrap();
        assert_eq!(map.get("phc_abc"), Some(&1000));
        assert_eq!(map.get("phc_abc:noisy"), Some(&50));
        assert_eq!(map.len(), 2);
    }

    #[test]
    fn test_parse_thresholds_empty_object() {
        assert!(parse_thresholds("{}").unwrap().is_empty());
    }

    #[test]
    fn test_parse_thresholds_rejects_malformed() {
        assert!(parse_thresholds("not json").is_err());
        // Non-numeric threshold values are rejected.
        assert!(parse_thresholds(r#"{"k": "abc"}"#).is_err());
    }

    #[tokio::test]
    async fn test_refresh_once_applies_thresholds() {
        let limiter = test_limiter();
        // Before refresh, only the CSV seed is present (exact + token fallback).
        assert!(limiter.is_custom_key("phc_seed"));
        assert!(!limiter.is_custom_key("phc_dyn"));

        let repo = MockThresholdRepository::with_thresholds(Some(HashMap::from([(
            "phc_dyn".to_string(),
            99u64,
        )])));
        assert!(refresh_once(&limiter, &repo).await);

        // Redis is authoritative: the swapped-in map replaces the CSV seed.
        assert!(limiter.is_custom_key("phc_dyn"));
        assert!(!limiter.is_custom_key("phc_seed"));
    }

    #[tokio::test]
    async fn test_refresh_once_hierarchical_fallback() {
        let limiter = test_limiter();
        let repo = MockThresholdRepository::with_thresholds(Some(HashMap::from([(
            "phc_tok".to_string(),
            10u64,
        )])));
        assert!(refresh_once(&limiter, &repo).await);

        // token:distinct_id resolves to the token-level threshold via the resolver.
        assert!(limiter.is_custom_key("phc_tok"));
        assert!(limiter.is_custom_key("phc_tok:any_user"));
        assert!(!limiter.is_custom_key("other_tok:any_user"));
    }

    #[tokio::test]
    async fn test_refresh_once_empty_key_clears_thresholds() {
        let limiter = test_limiter();
        assert!(limiter.is_custom_key("phc_seed"));

        let repo = MockThresholdRepository::with_thresholds(None);
        assert!(refresh_once(&limiter, &repo).await);

        // Absent key => Redis says no custom thresholds; the seed is cleared.
        assert!(!limiter.is_custom_key("phc_seed"));
    }

    #[tokio::test]
    async fn test_refresh_once_error_is_fail_static() {
        let limiter = test_limiter();
        // Seed a known dynamic value first.
        let repo_ok = MockThresholdRepository::with_thresholds(Some(HashMap::from([(
            "phc_dyn".to_string(),
            42u64,
        )])));
        assert!(refresh_once(&limiter, &repo_ok).await);
        assert!(limiter.is_custom_key("phc_dyn"));

        // A failed fetch must not change the current thresholds and signals reconnect.
        let repo_err = MockThresholdRepository::with_error(CustomRedisError::Timeout);
        assert!(!refresh_once(&limiter, &repo_err).await);
        assert!(limiter.is_custom_key("phc_dyn"));
    }
}
