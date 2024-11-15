use std::{any::Any, collections::HashMap, sync::Arc, time::Instant};

use axum::async_trait;
use tokio::sync::{Mutex, OwnedMutexGuard};

use crate::{
    error::Error,
    metric_consts::{
        STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_HITS, STORE_CACHE_MISSES,
    },
};

use super::{saving::Saveable, Fetcher, Parser, Provider};

pub struct Caching<P> {
    inner: P,
    cache: Arc<Mutex<SymbolSetCache>>,
}

impl<P> Caching<P> {
    pub fn new(inner: P, cache: Arc<Mutex<SymbolSetCache>>) -> Self {
        Self { inner, cache }
    }
}

#[async_trait]
impl<P> Provider for Caching<P>
where
    P: Fetcher + Parser<Source = P::Fetched>,
    P::Ref: ToString + Send,
    P::Fetched: Countable + Send,
    P::Set: Any + Send + Sync,
{
    type Ref = P::Ref;
    type Set = P::Set;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error> {
        let mut cache = self.cache.lock().await;
        let cache_key = format!("{}:{}", team_id, r.to_string());
        if let Some(set) = cache.get(&cache_key) {
            metrics::counter!(STORE_CACHE_HITS).increment(1);
            return Ok(set);
        }
        metrics::counter!(STORE_CACHE_MISSES).increment(1);
        // Grab a lock specific to this cache key, so that we don't fetch the same thing multiple times,
        // but still let /other/ symbol sets be acquired (via cache or fetch) while we're fetching/parsing
        let ref_lock = cache.ref_lock(cache_key.clone()).await;
        drop(cache);

        // Do the fetch
        let found = self.inner.fetch(team_id, r).await?;
        let bytes = found.byte_count();
        let parsed = self.inner.parse(found).await?;

        let mut cache = self.cache.lock().await; // Re-acquire the cache-wide lock to insert, dropping the ref_lock
        drop(ref_lock);

        let parsed = Arc::new(parsed);
        cache.insert(cache_key, parsed.clone(), bytes);
        Ok(parsed)
    }
}

pub struct SymbolSetCache {
    // We expect this cache to consist of few, but large, items.
    // TODO - handle cases where two CachedSymbolSets have identical keys but different types
    cached: HashMap<String, CachedSymbolSet>,
    fetch_locks: HashMap<String, Arc<Mutex<()>>>,
    held_bytes: usize,
    max_bytes: usize,
}

impl SymbolSetCache {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            cached: HashMap::new(),
            held_bytes: 0,
            fetch_locks: HashMap::new(),
            max_bytes,
        }
    }

    // Acquire a lock that's specific to a symbol set reference, so that we can prevent
    // multiple fetches of the same symbol-set, while still letting concurrent fetches
    // of different symbol-sets happen.
    pub async fn ref_lock(&mut self, key: String) -> OwnedMutexGuard<()> {
        // This hashmap grows unboundedly, but I don't care, because it's like
        // 30 bytes per entry, and entries only get added as new symbol sets get
        // loaded. I someone is ever able to show me this leak on a graph, I'll
        // fix it
        let lock = self.fetch_locks.entry(key.clone()).or_default();
        lock.clone().lock_owned().await
    }

    pub fn insert<T>(&mut self, key: String, value: Arc<T>, bytes: usize)
    where
        T: Any + Send + Sync,
    {
        self.held_bytes += bytes;
        self.cached.insert(
            key,
            CachedSymbolSet {
                data: value,
                bytes,
                last_used: Instant::now(),
            },
        );

        self.evict();
    }

    pub fn get<T>(&mut self, key: &str) -> Option<Arc<T>>
    where
        T: Any + Send + Sync,
    {
        let held = self.cached.get_mut(key)?;
        held.last_used = Instant::now();
        held.data.clone().downcast().ok()
    }

    fn evict(&mut self) {
        if self.held_bytes <= self.max_bytes {
            metrics::gauge!(STORE_CACHED_BYTES).set(self.held_bytes as f64);
            return;
        }

        metrics::counter!(STORE_CACHE_EVICTIONS).increment(1);

        let mut vals: Vec<_> = self.cached.iter().collect();

        // Sort to oldest-last, then pop until we're below the water line
        vals.sort_unstable_by_key(|(_, v)| v.last_used);
        vals.reverse();

        // We're borrowing all these refs from the hashmap, so we collect here to
        // remove them in a separate pass.
        let mut to_remove = vec![];
        while self.held_bytes > self.max_bytes && !vals.is_empty() {
            // We can unwrap here because we know we're not empty from the line above (and
            // really, even the !empty check could be skipped - if held_bytes is non-zero, we
            // must have at least one element in vals)
            let (to_remove_key, to_remove_val) = vals.pop().unwrap();
            self.held_bytes -= to_remove_val.bytes;
            to_remove.push(to_remove_key.clone());
        }

        for key in to_remove {
            self.fetch_locks.remove(&key);
        }

        metrics::gauge!(STORE_CACHED_BYTES).set(self.held_bytes as f64);
    }
}

struct CachedSymbolSet {
    pub data: Arc<dyn Any + Send + Sync>,
    pub bytes: usize,
    pub last_used: Instant,
}

pub trait Countable {
    fn byte_count(&self) -> usize;
}

impl Countable for Vec<u8> {
    fn byte_count(&self) -> usize {
        self.len()
    }
}

impl Countable for Saveable {
    fn byte_count(&self) -> usize {
        self.data.len()
    }
}
