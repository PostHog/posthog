use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
use futures::future::BoxFuture;
use tokio::sync::Mutex;
use tracing::warn;

/// Metric emitted per fetch attempt, tagged with the outcome. Unscoped: a source
/// is not tied to a particular limiter instance (the scoped `..._loaded` /
/// `..._last_refresh` gauges live on the refresh loop instead).
const FETCH_COUNTER: &str = "global_rate_limiter_custom_thresholds_fetch_total";

/// A pluggable source of custom-key thresholds for the global rate limiter.
///
/// The refresh loop calls `fetch` on a timer and atomically swaps the returned
/// map into the limiter. `Ok(Some(map))` replaces the current thresholds,
/// `Ok(None)` means "no thresholds configured" (clears them), and `Err` leaves
/// the current map untouched (fail-static). Implementations own their own
/// connection lifecycle, including reconnecting after a transient failure.
#[async_trait]
pub trait CustomKeyThresholdSource: Send + Sync {
    async fn fetch(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError>;
}

/// Parse the dynamic-threshold JSON blob.
///
/// The blob is a flat JSON object mapping a fully-resolved key to its threshold,
/// e.g. `{"phc_abc": 1000, "phc_abc:noisy_user": 50}`. The key structure is
/// opaque to this crate; callers give meaning to keys via a `CustomKeyResolver`.
pub fn parse_thresholds(json_str: &str) -> Result<HashMap<String, u64>, CustomRedisError> {
    serde_json::from_str(json_str)
        .map_err(|e| CustomRedisError::ParseError(format!("Failed to parse thresholds JSON: {e}")))
}

/// Builds a fresh client on demand. Returns a boxed future so the concrete
/// connection type (real Redis in production, a mock in tests) is hidden behind
/// one code path through `client()`/`reset_client()`.
type ClientBuilder = Arc<
    dyn Fn() -> BoxFuture<'static, Result<Arc<dyn Client + Send + Sync>, CustomRedisError>>
        + Send
        + Sync,
>;

/// Redis-backed source. Reads a single key holding the plain JSON blob (UTF-8, no
/// compression), mirroring the event-restrictions repository format.
///
/// `MultiplexedConnection` does not self-heal (only `ConnectionManager` does), so
/// this source owns reconnect itself: it builds its client lazily and drops it on
/// a connection failure, rebuilding on the next `fetch`. A Redis outage at
/// startup or mid-run therefore leaves the limiter on its current thresholds and
/// recovers automatically once Redis is reachable again.
pub struct RedisCustomKeyThresholdSource {
    key: String,
    /// Constructs a new client; invoked on first use and again after a reset.
    build_client: ClientBuilder,
    /// Lazily built; reset to `None` on connection failure so the next `fetch`
    /// rebuilds. The `Mutex` is only contended at the refresh cadence (seconds).
    client: Mutex<Option<Arc<dyn Client + Send + Sync>>>,
}

impl RedisCustomKeyThresholdSource {
    pub fn new(
        redis_url: String,
        key: String,
        response_timeout: Option<Duration>,
        connection_timeout: Option<Duration>,
    ) -> Self {
        // The client is UTF-8 / uncompressed to match the JSON blob Django writes.
        let build_client: ClientBuilder = Arc::new(
            move || -> BoxFuture<'static, Result<Arc<dyn Client + Send + Sync>, CustomRedisError>> {
                let redis_url = redis_url.clone();
                Box::pin(async move {
                    let client: Arc<dyn Client + Send + Sync> = Arc::new(
                        RedisClient::with_config(
                            redis_url,
                            CompressionConfig::disabled(),
                            RedisValueFormat::Utf8,
                            response_timeout,
                            connection_timeout,
                        )
                        .await?,
                    );
                    Ok(client)
                })
            },
        );
        Self {
            key,
            build_client,
            client: Mutex::new(None),
        }
    }

    /// Test seam: build a source from a custom client factory so the
    /// lazy-connect + reconnect path can be exercised without a real Redis.
    #[cfg(test)]
    fn with_client_builder(key: String, build_client: ClientBuilder) -> Self {
        Self {
            key,
            build_client,
            client: Mutex::new(None),
        }
    }

    /// Return the current client, building one if needed.
    async fn client(&self) -> Result<Arc<dyn Client + Send + Sync>, CustomRedisError> {
        let mut guard = self.client.lock().await;
        if let Some(client) = guard.as_ref() {
            return Ok(Arc::clone(client));
        }
        let client = (self.build_client)().await?;
        *guard = Some(Arc::clone(&client));
        Ok(client)
    }

    /// Drop the current client so the next `fetch` rebuilds it.
    async fn reset_client(&self) {
        *self.client.lock().await = None;
    }
}

#[async_trait]
impl CustomKeyThresholdSource for RedisCustomKeyThresholdSource {
    async fn fetch(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError> {
        let client = match self.client().await {
            Ok(client) => client,
            Err(e) => {
                metrics::counter!(FETCH_COUNTER, "result" => "connection_error").increment(1);
                warn!(key = %self.key, error = %e, "Failed to connect to custom-threshold Redis");
                return Err(e);
            }
        };

        let json_str = match client.get(self.key.clone()).await {
            Ok(s) => s,
            Err(CustomRedisError::NotFound) => {
                metrics::counter!(FETCH_COUNTER, "result" => "not_found").increment(1);
                return Ok(None);
            }
            Err(e) => {
                metrics::counter!(FETCH_COUNTER, "result" => "connection_error").increment(1);
                warn!(key = %self.key, error = %e, "Failed to fetch custom rate-limit thresholds from Redis");
                // Drop the (likely dead) connection so the next fetch reconnects.
                self.reset_client().await;
                return Err(e);
            }
        };

        match parse_thresholds(&json_str) {
            Ok(map) => {
                metrics::counter!(FETCH_COUNTER, "result" => "success").increment(1);
                Ok(Some(map))
            }
            Err(e) => {
                // Parse failures are a data problem, not a connection problem:
                // keep the connection and let ops fix the blob.
                metrics::counter!(FETCH_COUNTER, "result" => "parse_error").increment(1);
                warn!(key = %self.key, error = %e, "Failed to parse custom rate-limit thresholds from Redis");
                Err(e)
            }
        }
    }
}

#[cfg(test)]
pub mod testing {
    use super::*;

    /// Mock source for unit-testing the refresh path. Returns a fixed, cloneable
    /// result each `fetch`.
    pub struct MockCustomKeyThresholdSource {
        result: Mutex<Result<Option<HashMap<String, u64>>, CustomRedisError>>,
    }

    impl MockCustomKeyThresholdSource {
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

        /// Change what the next `fetch` returns (simulates a Redis-side update).
        pub async fn set_thresholds(&self, map: Option<HashMap<String, u64>>) {
            *self.result.lock().await = Ok(map);
        }
    }

    #[async_trait]
    impl CustomKeyThresholdSource for MockCustomKeyThresholdSource {
        async fn fetch(&self) -> Result<Option<HashMap<String, u64>>, CustomRedisError> {
            self.result.lock().await.clone()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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

    // --- RedisCustomKeyThresholdSource fetch/reconnect (via injected client) ---

    use common_redis::MockRedisClient;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Build a source whose client factory is driven by `make`, counting how many
    /// times a client is (re)built so tests can assert rebuild-vs-reuse.
    fn source_with<F>(key: &str, make: F) -> (RedisCustomKeyThresholdSource, Arc<AtomicUsize>)
    where
        F: Fn(usize) -> MockRedisClient + Send + Sync + 'static,
    {
        let builds = Arc::new(AtomicUsize::new(0));
        let builds_c = builds.clone();
        let make = Arc::new(make);
        let build: ClientBuilder = Arc::new(
            move || -> BoxFuture<'static, Result<Arc<dyn Client + Send + Sync>, CustomRedisError>> {
                let n = builds_c.fetch_add(1, Ordering::SeqCst);
                let make = make.clone();
                Box::pin(async move {
                    let client: Arc<dyn Client + Send + Sync> = Arc::new(make(n));
                    Ok(client)
                })
            },
        );
        (
            RedisCustomKeyThresholdSource::with_client_builder(key.to_string(), build),
            builds,
        )
    }

    #[tokio::test]
    async fn test_fetch_success_parses_and_reuses_client() {
        let (source, builds) = source_with("thresholds", |_| {
            MockRedisClient::new().get_ret("thresholds", Ok(r#"{"phc_abc": 1000}"#.to_string()))
        });

        let map = source.fetch().await.unwrap().unwrap();
        assert_eq!(map.get("phc_abc"), Some(&1000));

        // A healthy connection is cached: the second fetch does not rebuild.
        source.fetch().await.unwrap();
        assert_eq!(builds.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn test_fetch_not_found_returns_none_and_keeps_client() {
        let (source, builds) = source_with("k", |_| {
            MockRedisClient::new().get_ret("k", Err(CustomRedisError::NotFound))
        });

        assert!(source.fetch().await.unwrap().is_none());
        // NotFound is a normal "no config" answer, not a connection failure.
        assert!(source.fetch().await.unwrap().is_none());
        assert_eq!(builds.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn test_fetch_connection_error_resets_and_rebuilds() {
        // First build errors on GET (connection dead); second build succeeds.
        let (source, builds) = source_with("k", |n| {
            if n == 0 {
                MockRedisClient::new().get_ret("k", Err(CustomRedisError::Timeout))
            } else {
                MockRedisClient::new().get_ret("k", Ok(r#"{"phc": 5}"#.to_string()))
            }
        });

        assert!(source.fetch().await.is_err());
        let map = source.fetch().await.unwrap().unwrap();
        assert_eq!(map.get("phc"), Some(&5));
        // The dead connection was dropped and rebuilt on the retry.
        assert_eq!(builds.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn test_fetch_parse_error_keeps_client() {
        let (source, builds) = source_with("k", |_| {
            MockRedisClient::new().get_ret("k", Ok("not json".to_string()))
        });

        assert!(source.fetch().await.is_err());
        // A bad blob is a data problem, not a connection problem: no rebuild.
        assert!(source.fetch().await.is_err());
        assert_eq!(builds.load(Ordering::SeqCst), 1);
    }
}
