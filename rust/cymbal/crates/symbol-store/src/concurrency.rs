use std::{
    collections::HashMap,
    sync::{Arc, Weak},
};

use async_trait::async_trait;
use tokio::sync::{Mutex, OwnedMutexGuard};

use super::{refs::SymbolSetCacheKey, Provider};

// Limits the number of concurrent lookups
// for a given symbol set to 1. Note this places
// no concurrency limit /across/ different symbol
// sets, and places no limit on the number of users
// using the returned symbol set concurrently. Designed
// to wrap the caching/saving layers, allowing us to
// ensure we only fetch any given symbol set from the
// outside world exactly once
pub struct AtMostOne<P> {
    pub inner: P,
    limiters: Mutex<HashMap<String, Weak<Mutex<()>>>>,
}

impl<P> AtMostOne<P> {
    pub fn new(inner: P) -> Self {
        Self {
            inner,
            limiters: Default::default(),
        }
    }

    // This needs to be async even though all it does is take a lock because
    // the returned owned guard can be (and is) held across an await point, so
    // if this was a sync mutex it'd block the executor. It so happens that the
    // std library Mutex doesn't provide lock_owned anyway, so we'd have to pull
    // in a new dependency if we wanted to write a sync version of this, but
    // that's secondary to it actually needing to be async
    pub async fn acquire(&self, key: impl ToString) -> OwnedMutexGuard<()> {
        let key = key.to_string();
        let mut state = self.limiters.lock().await;
        state.retain(|_, v| v.strong_count() > 0);
        let limiter = state.entry(key).or_default();

        if let Some(lock) = limiter.upgrade() {
            // If there's already a mutex in our shared state for this particular
            // source ref, drop the global lock, and wait for the underlying source
            // ref to be freed up
            drop(state);
            lock.lock_owned().await
        } else {
            // If there's no mutex in our shared state for this particular source ref,
            // create one, acquire it, put a Weak to it in the shared state, and return
            // the owning mutex guard (and therefore the underling Arc to the new mutex)
            let new = Arc::new(Mutex::new(()));
            *limiter = Arc::downgrade(&new);
            let acquired = new.lock_owned().await;
            drop(state);
            acquired
        }
    }
}

#[async_trait]
impl<P> Provider for AtMostOne<P>
where
    P: Provider,
    P::Ref: SymbolSetCacheKey + Send,
{
    type Ref = P::Ref;
    type Set = P::Set;
    type Err = P::Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
        let lock = self
            .acquire(format!("{}:{}", team_id, r.symbol_set_cache_key()))
            .await;
        let result = self.inner.lookup(team_id, r).await;
        drop(lock);
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::time::{timeout, Duration};

    // Verify that acquiring the same key twice serializes: the second acquire
    // blocks until the first guard is dropped.
    #[tokio::test]
    async fn same_key_serializes() {
        let at_most_one: Arc<AtMostOne<()>> = Arc::new(AtMostOne::new(()));

        // Acquire the lock for key "k"
        let guard1 = at_most_one.acquire("k").await;

        let at_most_one2 = at_most_one.clone();
        let counter = Arc::new(AtomicUsize::new(0));
        let counter2 = counter.clone();

        // Spawn a task that tries to acquire the same key
        let task = tokio::spawn(async move {
            let _guard = at_most_one2.acquire("k").await;
            counter2.fetch_add(1, Ordering::SeqCst);
        });

        // Give the spawned task time to start and block on the lock
        tokio::time::sleep(Duration::from_millis(10)).await;

        // The spawned task should still be blocked — counter still 0
        assert_eq!(counter.load(Ordering::SeqCst), 0);

        // Release the first guard
        drop(guard1);

        // Now the spawned task should complete
        timeout(Duration::from_millis(100), task)
            .await
            .expect("task timed out")
            .expect("task panicked");

        assert_eq!(counter.load(Ordering::SeqCst), 1);
    }

    // Verify that acquiring different keys does NOT block each other.
    #[tokio::test]
    async fn different_keys_do_not_block_each_other() {
        let at_most_one: Arc<AtMostOne<()>> = Arc::new(AtMostOne::new(()));

        // Hold key "a"
        let _guard_a = at_most_one.acquire("a").await;

        let at_most_one2 = at_most_one.clone();

        // Acquiring key "b" should succeed immediately even while "a" is held
        let result = timeout(Duration::from_millis(50), async move {
            at_most_one2.acquire("b").await
        })
        .await;

        assert!(
            result.is_ok(),
            "acquiring a different key blocked unexpectedly"
        );
    }

    // Acquiring the same key a second time after the first guard is dropped
    // should succeed immediately (the Weak ref has been cleaned up).
    #[tokio::test]
    async fn released_key_can_be_reacquired() {
        let at_most_one: Arc<AtMostOne<()>> = Arc::new(AtMostOne::new(()));

        {
            let _guard = at_most_one.acquire("x").await;
            // guard dropped here
        }

        let result = timeout(Duration::from_millis(50), at_most_one.acquire("x")).await;
        assert!(result.is_ok(), "re-acquiring released key blocked");
    }
}
