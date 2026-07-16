use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
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

/// Redis-backed source. Reads a single key holding the plain JSON blob (UTF-8, no
/// compression), mirroring the event-restrictions repository format.
///
/// `MultiplexedConnection` does not self-heal (only `ConnectionManager` does), so
/// this source owns reconnect itself: it builds its client lazily and drops it on
/// a connection failure, rebuilding on the next `fetch`. A Redis outage at
/// startup or mid-run therefore leaves the limiter on its current thresholds and
/// recovers automatically once Redis is reachable again.
pub struct RedisCustomKeyThresholdSource {
    redis_url: String,
    key: String,
    response_timeout: Option<Duration>,
    connection_timeout: Option<Duration>,
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
        Self {
            redis_url,
            key,
            response_timeout,
            connection_timeout,
            client: Mutex::new(None),
        }
    }

    /// Return the current client, building one if needed. The client is UTF-8 /
    /// uncompressed to match the JSON blob Django writes.
    async fn client(&self) -> Result<Arc<dyn Client + Send + Sync>, CustomRedisError> {
        let mut guard = self.client.lock().await;
        if let Some(client) = guard.as_ref() {
            return Ok(Arc::clone(client));
        }
        let client: Arc<dyn Client + Send + Sync> = Arc::new(
            RedisClient::with_config(
                self.redis_url.clone(),
                CompressionConfig::disabled(),
                RedisValueFormat::Utf8,
                self.response_timeout,
                self.connection_timeout,
            )
            .await?,
        );
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
}
