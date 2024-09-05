use metrics::gauge;
use std::time::Duration as StdDuration;
use std::{collections::HashSet, sync::Arc};
use time::{Duration, OffsetDateTime};
use tokio::sync::RwLock;
use tokio::task;
use tokio::time::interval;
use tracing::instrument;

use crate::redis::Client;

/// Limit events by checking if a value is present in Redis
///
/// We have an async celery worker that regularly checks on accounts + assesses if they are beyond
/// a billing limit. If this is the case, a key is set in redis.
///
/// For replay sessions we also check if too many events are coming in in ingestion for a single session
/// and set a redis key to redirect further events to overflow.
///
/// Requirements
///
/// 1. Updates from the celery worker should be reflected in capture within a short period of time
/// 2. Capture should cope with redis being _totally down_, and fail open
/// 3. We should not hit redis for every single request
///
/// The solution here is to read from the cache and update the set in a background thread.
/// We have to lock all readers briefly while we update the set, but we don't hold the lock
/// until we already have the response from redis so it should be very short.
///
/// Some small delay between an account being limited and the limit taking effect is acceptable.
/// However, ideally we should not allow requests from some pods but 429 from others.

// todo: fetch from env
pub const QUOTA_LIMITER_CACHE_KEY: &str = "@posthog/quota-limits/";
pub const OVERFLOW_LIMITER_CACHE_KEY: &str = "@posthog/capture-overflow/";

#[derive(Debug)]
pub enum QuotaResource {
    Events,
    Recordings,
}

impl QuotaResource {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Events => "events",
            Self::Recordings => "recordings",
        }
    }
}

#[derive(Clone)]
pub struct RedisLimiter {
    limited: Arc<RwLock<HashSet<String>>>,
    redis: Arc<dyn Client + Send + Sync>,
    key: String,
    interval: Duration,
}

impl RedisLimiter {
    /// Create a new RedisLimiter.
    ///
    /// This connects to a redis cluster - pass in a vec of addresses for the initial nodes.
    ///
    /// You can also initialize the limiter with a set of tokens to limit from the very beginning.
    /// This may be overridden by Redis, if the sets differ,
    ///
    /// Pass an empty redis node list to only use this initial set.
    pub fn new(
        interval: Duration,
        redis: Arc<dyn Client + Send + Sync>,
        limiter_cache_key: String,
        redis_key_prefix: Option<String>,
        resource: QuotaResource,
    ) -> anyhow::Result<RedisLimiter> {
        let limited = Arc::new(RwLock::new(HashSet::new()));
        let key_prefix = redis_key_prefix.unwrap_or_default();

        let limiter = RedisLimiter {
            interval,
            limited,
            redis: redis.clone(),
            key: format!("{key_prefix}{limiter_cache_key}{}", resource.as_str()),
        };

        // Spawn a background task to periodically fetch data from Redis
        limiter.spawn_background_update();

        Ok(limiter)
    }

    fn spawn_background_update(&self) {
        let limited = Arc::clone(&self.limited);
        let redis = Arc::clone(&self.redis);
        let interval_duration = StdDuration::from_nanos(self.interval.whole_nanoseconds() as u64);
        let key = self.key.clone();

        // Spawn a task to periodically update the cache from Redis
        task::spawn(async move {
            let mut interval = interval(interval_duration);
            loop {
                match RedisLimiter::fetch_limited(&redis, &key).await {
                    Ok(set) => {
                        let set = HashSet::from_iter(set.iter().cloned());
                        gauge!("capture_billing_limits_loaded_tokens",).set(set.len() as f64);

                        let mut limited_lock = limited.write().await;
                        *limited_lock = set;
                    }
                    Err(e) => {
                        tracing::error!("Failed to update cache from Redis: {:?}", e);
                    }
                }

                interval.tick().await;
            }
        });
    }

    #[instrument(skip_all)]
    async fn fetch_limited(
        client: &Arc<dyn Client + Send + Sync>,
        key: &String,
    ) -> anyhow::Result<Vec<String>> {
        let now = OffsetDateTime::now_utc().unix_timestamp();
        client
            .zrangebyscore(key.to_string(), now.to_string(), String::from("+Inf"))
            .await
    }

    #[instrument(skip_all, fields(value = value))]
    pub async fn is_limited(&self, value: &str) -> bool {
        let limited = self.limited.read().await;
        limited.contains(value)
    }
}

#[cfg(test)]
mod tests {
    use crate::limiters::redis::QUOTA_LIMITER_CACHE_KEY;
    use std::sync::Arc;
    use time::Duration;

    use crate::{
        limiters::redis::{QuotaResource, RedisLimiter},
        redis::MockRedisClient,
    };

    #[tokio::test]
    async fn test_dynamic_limited() {
        let client = MockRedisClient::new()
            .zrangebyscore_ret("@posthog/quota-limits/events", vec![String::from("banana")]);
        let client = Arc::new(client);

        let limiter = RedisLimiter::new(Duration::seconds(1), client, QUOTA_LIMITER_CACHE_KEY.to_string(), None, QuotaResource::Events)
            .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;

        assert!(!limiter.is_limited("not_limited").await);
        assert!(limiter.is_limited("banana").await);
    }

    #[tokio::test]
    async fn test_custom_key_prefix() {
        let client = MockRedisClient::new().zrangebyscore_ret(
            "prefix//@posthog/quota-limits/events",
            vec![String::from("banana")],
        );
        let client = Arc::new(client);

        // Default lookup without prefix fails
        let limiter = RedisLimiter::new(
            Duration::seconds(1),
            client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Events,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;
        assert!(!limiter.is_limited("banana").await);

        // Limiter using the correct prefix
        let prefixed_limiter = RedisLimiter::new(
            Duration::microseconds(1),
            client,
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            Some("prefix//".to_string()),
            QuotaResource::Events,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;

        assert!(!prefixed_limiter.is_limited("not_limited").await);
        assert!(prefixed_limiter.is_limited("banana").await);
    }
}
