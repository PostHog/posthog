use std::{
    collections::HashMap,
    sync::{Arc, Weak},
};

use axum::async_trait;
use tokio::sync::{Mutex, OwnedMutexGuard};

use crate::error::Error;

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
    state: Mutex<Inner>,
}

impl<P> AtMostOne<P> {
    pub fn new(inner: P) -> Self {
        Self {
            inner,
            state: Default::default(),
        }
    }

    pub async fn acquire(&self, key: impl ToString) -> OwnedMutexGuard<()> {
        let key = key.to_string();
        let mut state = self.state.lock().await;
        let limiter = state.limiters.entry(key).or_insert_with(|| Weak::new());

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

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error> {
        let lock = self.acquire(r.to_string()).await;
        let result = self.inner.lookup(team_id, r).await;
        drop(lock);
        result
    }
}

#[derive(Default)]
struct Inner {
    pub limiters: HashMap<String, Weak<Mutex<()>>>,
}
