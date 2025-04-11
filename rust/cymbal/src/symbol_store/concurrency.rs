use std::{
    collections::HashMap,
    sync::{Arc, Weak},
};

use axum::async_trait;
use tokio::sync::{Mutex, OwnedMutexGuard};

use super::Provider;

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
    P::Ref: ToString + Send,
{
    type Ref = P::Ref;
    type Set = P::Set;
    type Err = P::Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
        let lock = self.acquire(format!("{}:{}", team_id, r.to_string())).await;
        let result = self.inner.lookup(team_id, r).await;
        drop(lock);
        result
    }
}
