use std::{future::Future, sync::Arc, time::Duration};

use moka::future::Cache;
use uuid::Uuid;

use crate::{error::UnhandledError, types::operator::TeamId};

// The sweep's inactivity cutoff must allow for the full interval between writes.
const RECEIPT_TTL: Duration = Duration::from_secs(3600);

type ReceiptKey = (TeamId, Uuid);

pub(crate) struct IssueReceiptCache(Cache<ReceiptKey, ()>);

impl IssueReceiptCache {
    pub(crate) fn new(capacity: u64) -> Self {
        Self::with_ttl(capacity, RECEIPT_TTL)
    }

    fn with_ttl(capacity: u64, ttl: Duration) -> Self {
        Self(
            Cache::builder()
                .max_capacity(capacity)
                .time_to_live(ttl)
                .build(),
        )
    }

    pub(super) async fn contains(&self, key: ReceiptKey) -> bool {
        self.0.get(&key).await.is_some()
    }

    pub(super) async fn record_if_due<T>(
        &self,
        key: ReceiptKey,
        commit: impl Future<Output = Result<T, UnhandledError>>,
    ) -> Result<Option<T>, UnhandledError> {
        let mut committed = None;
        // Only the writer owns the transition result and can publish its reopen side effects.
        self.0
            .try_get_with(key, async {
                committed = Some(commit.await?);
                Ok(())
            })
            .await
            .map_err(|error: Arc<UnhandledError>| UnhandledError::Other(error.to_string()))?;
        Ok(committed)
    }
}

#[cfg(test)]
mod tests {
    use std::pin::pin;

    use tokio::sync::oneshot;

    use super::*;

    #[tokio::test]
    async fn caches_one_successful_receipt_for_concurrent_callers() {
        let cache = IssueReceiptCache::new(10);
        let key = (1, Uuid::nil());
        let (commit, committed) = oneshot::channel();
        let mut writer = pin!(cache.record_if_due(key, async {
            committed.await.unwrap();
            Ok(42)
        }));
        assert!(futures::poll!(&mut writer).is_pending());
        let mut waiter = pin!(cache.record_if_due::<()>(key, async {
            panic!("the waiter must not write a duplicate receipt");
        }));
        assert!(futures::poll!(&mut waiter).is_pending());
        assert!(!cache.contains(key).await);
        commit.send(()).unwrap();
        assert_eq!(writer.await.unwrap(), Some(42));
        assert_eq!(waiter.await.unwrap(), None);
        assert!(cache.contains(key).await);
        assert_eq!(
            cache.0.policy().time_to_live(),
            Some(Duration::from_secs(3600))
        );
        assert_eq!(cache.0.policy().time_to_idle(), None);
    }

    #[tokio::test]
    async fn failed_write_and_expired_receipt_do_not_suppress_the_next_write() {
        let key = (1, Uuid::nil());
        let cache = IssueReceiptCache::new(10);
        let failed = cache
            .record_if_due::<()>(key, async { Err(sqlx::Error::PoolClosed.into()) })
            .await;
        assert!(failed.is_err());
        assert!(!cache.contains(key).await);
        assert_eq!(
            cache.record_if_due(key, async { Ok(42) }).await.unwrap(),
            Some(42)
        );

        let cache = IssueReceiptCache::with_ttl(10, Duration::ZERO);
        for value in [1, 2] {
            assert_eq!(
                cache.record_if_due(key, async { Ok(value) }).await.unwrap(),
                Some(value)
            );
        }
    }
}
