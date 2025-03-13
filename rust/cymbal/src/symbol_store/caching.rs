use std::{any::Any, collections::HashMap, sync::Arc, time::Instant};

use axum::async_trait;
use tokio::sync::Mutex;

use crate::metric_consts::{
    STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_EVICTION_RUNS, STORE_CACHE_HITS,
    STORE_CACHE_MISSES,
};

use super::{saving::Saveable, Fetcher, Parser, Provider};

// This is a type-specific symbol provider layer, designed to
// wrap some inner provider and provide a type-safe caching layer
pub struct Caching<P> {
    inner: P,
    cache: Arc<Mutex<SymbolSetCache>>, // This inner cache is shared across providers
}

impl<P> Caching<P>
// This where clause exists exclusively to give more obvious compiler errors in cases where
// the passed P doesn't cause Provider to be implemented for this Caching<P> - for example,
// if the P's P::Ref doesn't implement ToString
where
    P: Fetcher + Parser<Source = P::Fetched, Err = <P as Fetcher>::Err>,
    P::Ref: ToString + Send,
    P::Fetched: Countable + Send,
    P::Set: Any + Send + Sync,
{
    pub fn new(inner: P, cache: Arc<Mutex<SymbolSetCache>>) -> Self {
        Self { inner, cache }
    }
}

#[async_trait]
impl<P> Provider for Caching<P>
where
    P: Fetcher + Parser<Source = P::Fetched, Err = <P as Fetcher>::Err>,
    P::Ref: ToString + Send,
    P::Fetched: Countable + Send,
    P::Set: Any + Send + Sync,
{
    type Ref = P::Ref;
    type Set = P::Set;
    type Err = <P as Fetcher>::Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
        let mut cache = self.cache.lock().await;
        let cache_key = format!("{}:{}", team_id, r.to_string());
        if let Some(set) = cache.get(&cache_key) {
            metrics::counter!(STORE_CACHE_HITS).increment(1);
            return Ok(set);
        }
        metrics::counter!(STORE_CACHE_MISSES).increment(1);
        drop(cache);

        // Do the fetch, not holding the lock across it to allow
        // concurrent fetches to occur (de-duping fetches is
        // up to the caller of `lookup`, since relying on the
        // cache to do it means assuming the caching layer is
        // the outer layer, which is not something the interface
        // guarentees)
        let found = self.inner.fetch(team_id, r).await?;
        let bytes = found.byte_count();
        let parsed = self.inner.parse(found).await?;

        let mut cache = self.cache.lock().await; // Re-acquire the cache-wide lock to insert, dropping the ref_lock

        let parsed = Arc::new(parsed);
        cache.insert(cache_key, parsed.clone(), bytes);
        Ok(parsed)
    }
}

// This is a cache shared across multiple symbol set providers, through the `Caching` above,
// such that two totally different "layers" can share an underlying "pool" of cache space. This
// is injected into the `Caching` layer at construct time, to allow this sharing across multiple
// provider layer "stacks" within the catalog.
pub struct SymbolSetCache {
    // We expect this cache to consist of few, but large, items.
    // TODO - handle cases where two CachedSymbolSets have identical keys but different types
    cached: HashMap<String, CachedSymbolSet>,
    held_bytes: usize,
    max_bytes: usize,
}

impl SymbolSetCache {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            cached: HashMap::new(),
            held_bytes: 0,
            max_bytes,
        }
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

        metrics::counter!(STORE_CACHE_EVICTION_RUNS).increment(1);

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
            metrics::counter!(STORE_CACHE_EVICTIONS).increment(1);
            self.cached.remove(&key);
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
