use std::future::Future;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::Mutex;

/// A single-value TTL cache with single-flight refresh: the mutex is held
/// across the refresh, so concurrent callers wait for one in-flight refresh
/// and share its result instead of each triggering their own. Kafka topology
/// (topics, groups, partitions) changes rarely, and this also stops repeated
/// requests from multiplying broker-wide scans.
pub struct TtlCache<T> {
    ttl: Duration,
    inner: Mutex<Option<(Instant, Arc<T>)>>,
}

impl<T> TtlCache<T> {
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            inner: Mutex::new(None),
        }
    }

    /// Return the cached value if fresh, otherwise run `refresh` and cache
    /// its result. A failed refresh leaves any previous (stale) entry in
    /// place so the next caller retries.
    pub async fn get_or_refresh<F, Fut>(&self, refresh: F) -> anyhow::Result<Arc<T>>
    where
        F: FnOnce() -> Fut,
        Fut: Future<Output = anyhow::Result<T>>,
    {
        let mut guard = self.inner.lock().await;
        if let Some((refreshed_at, value)) = &*guard {
            if refreshed_at.elapsed() < self.ttl {
                return Ok(Arc::clone(value));
            }
        }
        let value = Arc::new(refresh().await?);
        *guard = Some((Instant::now(), Arc::clone(&value)));
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU32, Ordering};

    use super::*;

    #[tokio::test]
    async fn serves_cached_value_within_ttl_and_refreshes_after() {
        let cache = TtlCache::new(Duration::from_secs(60));
        let calls = AtomicU32::new(0);
        let refresh = || {
            calls.fetch_add(1, Ordering::SeqCst);
            async { Ok(42u32) }
        };

        assert_eq!(*cache.get_or_refresh(refresh).await.unwrap(), 42);
        assert_eq!(*cache.get_or_refresh(refresh).await.unwrap(), 42);
        assert_eq!(calls.load(Ordering::SeqCst), 1);

        let expired = TtlCache::new(Duration::ZERO);
        assert_eq!(*expired.get_or_refresh(refresh).await.unwrap(), 42);
        assert_eq!(*expired.get_or_refresh(refresh).await.unwrap(), 42);
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn failed_refresh_is_retried_by_next_caller() {
        let cache: TtlCache<u32> = TtlCache::new(Duration::from_secs(60));
        let result = cache
            .get_or_refresh(|| async { Err(anyhow::anyhow!("broker down")) })
            .await;
        assert!(result.is_err());
        assert_eq!(*cache.get_or_refresh(|| async { Ok(7) }).await.unwrap(), 7);
    }

    #[tokio::test]
    async fn concurrent_callers_share_one_refresh() {
        let cache: Arc<TtlCache<u32>> = Arc::new(TtlCache::new(Duration::from_secs(60)));
        let calls = Arc::new(AtomicU32::new(0));
        let tasks: Vec<_> = (0..8)
            .map(|_| {
                let cache = Arc::clone(&cache);
                let calls = Arc::clone(&calls);
                tokio::spawn(async move {
                    *cache
                        .get_or_refresh(|| async {
                            calls.fetch_add(1, Ordering::SeqCst);
                            tokio::time::sleep(Duration::from_millis(20)).await;
                            Ok(1u32)
                        })
                        .await
                        .unwrap()
                })
            })
            .collect();
        for task in tasks {
            assert_eq!(task.await.unwrap(), 1);
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
