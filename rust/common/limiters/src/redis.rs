use chrono::Utc;
use common_redis::{Client, CustomRedisError};
use dashmap::DashMap;
use metrics::gauge;
use std::sync::Arc;
use std::time::Duration;
use strum::Display;
use tokio::task;
use tokio::time::interval;

/// Limit resources by checking if a value is present in Redis
///
/// We have an async celery worker that regularly checks on accounts + assesses if they are beyond
/// a billing limit. If this is the case, a key is set in redis.
///
/// For replay sessions we also check if too many events are coming in in ingestion for a single session
/// and set a redis key to redirect further events to overflow.
///
/// For feature flag evaluations we still return a 200 response, but add an entry to the response body
/// to indicate that the flag evaluation was quota-limited.
///
/// Requirements
///
/// 1. Updates from the celery worker should be reflected in capture within a short period of time
/// 2. Quota limited services should cope with redis being _totally down_, and fail open
/// 3. We should not hit redis for every single request
///
/// The solution here is to read from the cache and update the set in a background thread.
/// We have to lock all readers briefly while we update the set, but we don't hold the lock
/// until we already have the response from redis so it should be very short.
///
/// Some small delay between an account being limited and the limit taking effect is acceptable.
/// However, ideally we should not allow requests from some pods but 429 from others.
// todo: fetch from env
// due to historical reasons we use different suffixes for quota limits and overflow
// hopefully we can unify these in the future
pub const QUOTA_LIMITER_CACHE_KEY: &str = "@posthog/quota-limits/";
pub const OVERFLOW_LIMITER_CACHE_KEY: &str = "@posthog/capture-overflow/";

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum QuotaResource {
    Events,
    Exceptions,
    Recordings,
    Replay,
    FeatureFlags,
    Surveys,
    LLMEvents,
}

impl QuotaResource {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Events => "events",
            Self::Exceptions => "exceptions",
            Self::Recordings => "recordings",
            Self::Replay => "replay",
            Self::FeatureFlags => "feature_flag_requests",
            Self::Surveys => "survey_responses",
            Self::LLMEvents => "llm_events",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Display)]
pub enum ServiceName {
    SessionReplay,
    FeatureFlags,
    Capture,
    Cymbal,
}

impl ServiceName {
    pub fn as_string(&self) -> String {
        match self {
            ServiceName::SessionReplay => "session_replay".to_string(),
            ServiceName::FeatureFlags => "feature_flags".to_string(),
            ServiceName::Capture => "capture".to_string(),
            ServiceName::Cymbal => "cymbal".to_string(),
        }
    }
}

pub(crate) fn limiter_key(
    redis_key_prefix: Option<String>,
    limiter_cache_key: &str,
    resource: &QuotaResource,
) -> String {
    let key_prefix = redis_key_prefix.unwrap_or_default();
    format!("{key_prefix}{limiter_cache_key}{}", resource.as_str())
}

#[derive(Clone)]
pub struct RedisLimiter {
    limited: Arc<DashMap<String, bool>>,
    redis: Arc<dyn Client + Send + Sync>,
    key: String,
    interval: Duration,
    service_name: ServiceName,
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
        service_name: ServiceName,
    ) -> anyhow::Result<RedisLimiter> {
        let limited = Arc::new(DashMap::new());

        let limiter = RedisLimiter {
            limited,
            redis: redis.clone(),
            key: limiter_key(redis_key_prefix, &limiter_cache_key, &resource),
            interval,
            service_name,
        };

        // Spawn a background task to periodically fetch data from Redis
        limiter.spawn_background_update();

        Ok(limiter)
    }

    fn spawn_background_update(&self) {
        let limited = Arc::clone(&self.limited);
        let redis = Arc::clone(&self.redis);
        let interval_duration = self.interval;
        let key = self.key.clone();
        let cache_key: Arc<str> = Arc::from(key.as_str());
        let service_name = self.service_name.as_string();

        // Spawn a task to periodically update the cache from Redis
        task::spawn(async move {
            let mut interval = interval(interval_duration);
            let mut last_success_at = 0.0;
            loop {
                // Resolved per pass: feature-flags installs its recorder after it builds limiters.
                let last_success = gauge!(
                    format!("{service_name}_billing_limits_last_success_timestamp_seconds"),
                    "cache_key" => cache_key.clone(),
                );
                match RedisLimiter::fetch_limited(&redis, &key).await {
                    Ok(set) => {
                        gauge!(
                            format!("{}_billing_limits_loaded_tokens", service_name),
                            "cache_key" => key.clone(),
                        )
                        .set(set.len() as f64);

                        limited.clear();
                        for item in set {
                            limited.insert(item, true);
                        }

                        last_success_at = Utc::now().timestamp() as f64;
                    }
                    Err(e) => {
                        tracing::warn!("Failed to update cache from Redis: {:?}", e);
                    }
                }
                last_success.set(last_success_at);

                interval.tick().await;
            }
        });
    }

    pub(crate) async fn fetch_limited(
        client: &Arc<dyn Client + Send + Sync>,
        key: &String,
    ) -> anyhow::Result<Vec<String>, CustomRedisError> {
        let now = Utc::now().timestamp();
        client
            .zrangebyscore(key.to_string(), now.to_string(), String::from("+Inf"))
            .await
    }

    pub async fn is_limited(&self, value: &str) -> bool {
        self.limited.get(value).is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::{OVERFLOW_LIMITER_CACHE_KEY, QUOTA_LIMITER_CACHE_KEY};
    use crate::redis::{QuotaResource, RedisLimiter, ServiceName};
    use chrono::Utc;
    use common_redis::{CustomRedisError, MockRedisClient};
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use std::{sync::Arc, time::Duration};

    #[tokio::test]
    async fn test_dynamic_limited() {
        let client = MockRedisClient::new().zrangebyscore_ret(
            "@posthog/capture-overflow/replay",
            vec![String::from("banana")],
        );
        let client = Arc::new(client);

        let limiter = RedisLimiter::new(
            Duration::from_secs(1),
            client,
            OVERFLOW_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Replay,
            ServiceName::Capture,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;

        assert!(!limiter.is_limited("not_limited").await);
        assert!(limiter.is_limited("banana").await);
    }

    #[tokio::test(start_paused = true)]
    async fn a_failed_refresh_keeps_the_last_set_and_success_time() {
        let client = MockRedisClient::new()
            .zrangebyscore_ret("@posthog/quota-limits/events", vec![String::from("banana")])
            .zrangebyscore_error_from_call(1, CustomRedisError::Timeout);
        let before = Utc::now().timestamp() as f64;
        let limiter = RedisLimiter::new(
            Duration::from_secs(1),
            Arc::new(client.clone()),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Events,
            ServiceName::Capture,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(Duration::from_millis(500)).await;
        let after = Utc::now().timestamp() as f64;
        let reads_before_install = client.get_calls().len();
        assert!(
            reads_before_install > 0,
            "the first refresh must run before the recorder exists"
        );

        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        tokio::time::sleep(Duration::from_millis(2000)).await;

        assert!(
            client.get_calls().len() > reads_before_install,
            "a refresh must fail after the install"
        );
        assert!(limiter.is_limited("banana").await);
        let gauge_name = "capture_billing_limits_last_success_timestamp_seconds";
        let last_success = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find_map(|(key, _, _, value)| (key.key().name() == gauge_name).then_some(value));
        assert!(
            matches!(last_success, Some(DebugValue::Gauge(timestamp)) if (before..=after).contains(&timestamp.into_inner()))
        );
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
            Duration::from_secs(1),
            client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::Events,
            ServiceName::Capture,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;
        assert!(!limiter.is_limited("banana").await);

        // Limiter using the correct prefix
        let prefixed_limiter = RedisLimiter::new(
            Duration::from_micros(1),
            client,
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            Some("prefix//".to_string()),
            QuotaResource::Events,
            ServiceName::Capture,
        )
        .expect("Failed to create billing limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;

        assert!(!prefixed_limiter.is_limited("not_limited").await);
        assert!(prefixed_limiter.is_limited("banana").await);
    }

    #[tokio::test]
    async fn test_feature_flag_limiter() {
        let client = MockRedisClient::new().zrangebyscore_ret(
            "@posthog/quota-limits/feature_flag_requests",
            vec![String::from("banana")],
        );
        let client = Arc::new(client);

        let limiter = RedisLimiter::new(
            Duration::from_secs(1),
            client,
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            None,
            QuotaResource::FeatureFlags,
            ServiceName::FeatureFlags,
        )
        .expect("Failed to create feature flag limiter");
        tokio::time::sleep(std::time::Duration::from_millis(30)).await;

        assert!(!limiter.is_limited("not_limited").await);
        assert!(limiter.is_limited("banana").await);
    }
}
