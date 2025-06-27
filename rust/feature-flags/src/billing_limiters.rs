use limiters::redis::{QuotaResource, RedisLimiter, ServiceName};
use std::sync::Arc;
use std::time::Duration;

/// Feature flags specific billing limiter that always uses QuotaResource::FeatureFlags
///
/// This type wrapper ensures you can't accidentally create a feature flags limiter
/// with the wrong quota resource type. It always uses QuotaResource::FeatureFlags.
#[derive(Clone)]
pub struct FeatureFlagsLimiter {
    inner: RedisLimiter,
}

impl FeatureFlagsLimiter {
    pub fn new(
        ttl: Duration,
        redis_client: Arc<dyn common_redis::Client + Send + Sync>,
        cache_key: String,
        cache_prefix: Option<String>,
    ) -> Result<Self, anyhow::Error> {
        let inner = RedisLimiter::new(
            ttl,
            redis_client,
            cache_key,
            cache_prefix,
            QuotaResource::FeatureFlags,
            ServiceName::FeatureFlags,
        )?;
        Ok(Self { inner })
    }

    pub async fn is_limited(&self, token: &str) -> bool {
        self.inner.is_limited(token).await
    }
}

/// Session replay specific billing limiter that always uses QuotaResource::Recordings
///
/// This type wrapper ensures you can't accidentally create a session replay limiter
/// with the wrong quota resource type. It always uses QuotaResource::Recordings.
#[derive(Clone)]
pub struct SessionReplayLimiter {
    inner: RedisLimiter,
}

impl SessionReplayLimiter {
    pub fn new(
        ttl: Duration,
        redis_client: Arc<dyn common_redis::Client + Send + Sync>,
        cache_key: String,
        cache_prefix: Option<String>,
    ) -> Result<Self, anyhow::Error> {
        let inner = RedisLimiter::new(
            ttl,
            redis_client,
            cache_key,
            cache_prefix,
            QuotaResource::Recordings,
            ServiceName::FeatureFlags,
        )?;
        Ok(Self { inner })
    }

    pub async fn is_limited(&self, token: &str) -> bool {
        self.inner.is_limited(token).await
    }
}
