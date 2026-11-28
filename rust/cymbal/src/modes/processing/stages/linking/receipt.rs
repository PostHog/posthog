use std::{
    future::Future,
    sync::Arc,
    time::{Duration, Instant},
};

use moka::{future::Cache, Expiry};
use uuid::Uuid;

use crate::{error::UnhandledError, types::operator::TeamId};

// The sweep's inactivity cutoff must allow for the full interval between writes.
const RECEIPT_TTL: Duration = Duration::from_secs(3600);

type ReceiptKey = (TeamId, Uuid);

#[derive(Clone)]
pub(crate) struct EntryWithDeadline<T> {
    pub value: T,
    pub expires_at: Instant,
}

pub(crate) struct EntryDeadline;

impl<K, T> Expiry<K, EntryWithDeadline<T>> for EntryDeadline {
    fn expire_after_create(
        &self,
        _: &K,
        entry: &EntryWithDeadline<T>,
        inserted_at: Instant,
    ) -> Option<Duration> {
        Some(entry.expires_at.saturating_duration_since(inserted_at))
    }
}

pub(crate) struct IssueReceiptCache {
    entries: Cache<ReceiptKey, EntryWithDeadline<()>>,
    ttl: Duration,
}

impl IssueReceiptCache {
    pub(crate) fn new(capacity: u64) -> Self {
        Self::with_ttl(capacity, RECEIPT_TTL)
    }

    fn with_ttl(capacity: u64, ttl: Duration) -> Self {
        Self {
            entries: Cache::builder()
                .max_capacity(capacity)
                .expire_after(EntryDeadline)
                .build(),
            ttl,
        }
    }

    pub(super) async fn contains(&self, key: ReceiptKey) -> bool {
        self.entries.get(&key).await.is_some()
    }

    pub(super) async fn record_if_due<T>(
        &self,
        key: ReceiptKey,
        commit: impl Future<Output = Result<T, UnhandledError>>,
    ) -> Result<Option<T>, UnhandledError> {
        self.record_if_due_since(key, Instant::now(), commit).await
    }

    pub(super) async fn record_if_due_since<T>(
        &self,
        key: ReceiptKey,
        started_at: Instant,
        commit: impl Future<Output = Result<T, UnhandledError>>,
    ) -> Result<Option<T>, UnhandledError> {
        let mut committed = None;
        // Only the writer owns the transition result and can publish its reopen side effects.
        // A slow commit must not extend the window beyond the sweep's grace period.
        self.entries
            .try_get_with(key, async {
                committed = Some(commit.await?);
                Ok(EntryWithDeadline {
                    value: (),
                    expires_at: started_at + self.ttl,
                })
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
        assert_eq!(cache.ttl, Duration::from_secs(3600));
        assert_eq!(cache.entries.policy().time_to_idle(), None);
    }

    #[tokio::test]
    async fn a_slow_commit_does_not_extend_the_receipt_window() {
        let cache = IssueReceiptCache::new(10);
        let key = (1, Uuid::nil());
        let started_at = Instant::now() - RECEIPT_TTL;
        assert_eq!(
            cache
                .record_if_due_since(key, started_at, async { Ok(42) })
                .await
                .unwrap(),
            Some(42)
        );
        assert!(!cache.contains(key).await);
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
