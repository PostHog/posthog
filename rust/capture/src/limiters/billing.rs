use std::{collections::HashSet, ops::Sub, sync::Arc};

use crate::redis::Client;

/// Limit accounts by team ID if they hit a billing limit
///
/// We have an async celery worker that regularly checks on accounts + assesses if they are beyond
/// a billing limit. If this is the case, a key is set in redis.
///
/// Requirements
///
/// 1. Updates from the celery worker should be reflected in capture within a short period of time
/// 2. Capture should cope with redis being _totally down_, and fail open
/// 3. We should not hit redis for every single request
///
/// The solution here is to read from the cache until a time interval is hit, and then fetch new
/// data. The write requires taking a lock that stalls all readers, though so long as redis reads
/// stay fast we're ok.
///
/// Some small delay between an account being limited and the limit taking effect is acceptable.
/// However, ideally we should not allow requests from some pods but 429 from others.
use thiserror::Error;
use time::{Duration, OffsetDateTime};
use tokio::sync::RwLock;
use tracing::instrument;

// todo: fetch from env
const QUOTA_LIMITER_CACHE_KEY: &str = "@posthog/quota-limits/";

#[derive(Debug)]
pub enum QuotaResource {
    Events,
    Recordings,
}

impl QuotaResource {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Events => "events",
            Self::Recordings => "recordings",
        }
    }
}

#[derive(Error, Debug)]
pub enum LimiterError {
    #[error("updater already running - there can only be one")]
    UpdaterRunning,
}

#[derive(Clone)]
pub struct BillingLimiter {
    limited: Arc<RwLock<HashSet<String>>>,
    redis: Arc<dyn Client + Send + Sync>,
    interval: Duration,
    updated: Arc<RwLock<OffsetDateTime>>,
}

impl BillingLimiter {
    /// Create a new BillingLimiter.
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
    ) -> anyhow::Result<BillingLimiter> {
        let limited = Arc::new(RwLock::new(HashSet::new()));

        // Force an update immediately if we have any reasonable interval
        let updated = OffsetDateTime::from_unix_timestamp(0)?;
        let updated = Arc::new(RwLock::new(updated));

        Ok(BillingLimiter {
            interval,
            limited,
            updated,
            redis,
        })
    }

    #[instrument(skip_all)]
    async fn fetch_limited(
        client: &Arc<dyn Client + Send + Sync>,
        resource: QuotaResource,
    ) -> anyhow::Result<Vec<String>> {
        let now = time::OffsetDateTime::now_utc().unix_timestamp();

        client
            .zrangebyscore(
                format!("{QUOTA_LIMITER_CACHE_KEY}{}", resource.as_str()),
                now.to_string(),
                String::from("+Inf"),
            )
            .await
    }

    #[instrument(skip_all, fields(key = key))]
    pub async fn is_limited(&self, key: &str, resource: QuotaResource) -> bool {
        // hold the read lock to clone it, very briefly. clone is ok because it's very small 🤏
        // rwlock can have many readers, but one writer. the writer will wait in a queue with all
        // the readers, so we want to hold read locks for the smallest time possible to avoid
        // writers waiting for too long. and vice versa.
        let updated = {
            let updated = self.updated.read().await;
            *updated
        };

        let now = OffsetDateTime::now_utc();
        let since_update = now.sub(updated);

        // If an update is due, fetch the set from redis + cache it until the next update is due.
        // Otherwise, return a value from the cache
        //
        // This update will block readers! Keep it fast.
        if since_update > self.interval {
            // open the update lock to change the update, and prevent anyone else from doing so
            let mut updated = self.updated.write().await;
            *updated = OffsetDateTime::now_utc();

            let span = tracing::debug_span!("updating billing cache from redis");
            let _span = span.enter();

            // a few requests might end up in here concurrently, but I don't think a few extra will
            // be a big problem. If it is, we can rework the concurrency a bit.
            // On prod atm we call this around 15 times per second at peak times, and it usually
            // completes in <1ms.

            let set = Self::fetch_limited(&self.redis, resource).await;

            tracing::debug!("fetched set from redis, caching");

            if let Ok(set) = set {
                let set = HashSet::from_iter(set.iter().cloned());

                let mut limited = self.limited.write().await;
                *limited = set;

                tracing::debug!("updated cache from redis");

                limited.contains(key)
            } else {
                tracing::error!("failed to fetch from redis in time, failing open");
                // If we fail to fetch the set, something really wrong is happening. To avoid
                // dropping events that we don't mean to drop, fail open and accept data. Better
                // than angry customers :)
                //
                // TODO: Consider backing off our redis checks
                false
            }
        } else {
            let l = self.limited.read().await;

            l.contains(key)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use time::Duration;

    use crate::{
        limiters::billing::{BillingLimiter, QuotaResource},
        redis::MockRedisClient,
    };

    #[tokio::test]
    async fn test_dynamic_limited() {
        let client = MockRedisClient::new().zrangebyscore_ret(vec![String::from("banana")]);
        let client = Arc::new(client);

        let limiter = BillingLimiter::new(Duration::microseconds(1), client)
            .expect("Failed to create billing limiter");

        assert_eq!(
            limiter
                .is_limited("idk it doesn't matter", QuotaResource::Events)
                .await,
            false
        );

        assert_eq!(
            limiter
                .is_limited("some_org_hit_limits", QuotaResource::Events)
                .await,
            false
        );
        assert!(limiter.is_limited("banana", QuotaResource::Events).await);
    }
}
