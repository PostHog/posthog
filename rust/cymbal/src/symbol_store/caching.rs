use std::{any::Any, collections::HashMap, sync::Arc, time::Instant};

use axum::async_trait;
use sourcemap::SourceMap;
use tokio::sync::Mutex;

use crate::{
    error::Error,
    metric_consts::{
        STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_HITS, STORE_CACHE_MISSES,
        STORE_CACHE_SIZE,
    },
};

use super::SymbolProvider;

pub struct CachingProvider<P> {
    cache: Arc<Mutex<CacheInner>>,
    provider: P,
}

impl<P> CachingProvider<P> {
    pub fn new(max_bytes: usize, provider: P, shared: Arc<Mutex<CacheInner>>) -> Self {
        metrics::gauge!(STORE_CACHE_SIZE).set(max_bytes as f64);
        Self {
            cache: shared,
            provider,
        }
    }
}

#[async_trait]
impl<P> SymbolProvider for CachingProvider<P>
where
    P: SymbolProvider,
    P::Ref: ToString + Send,
    P::Set: Cacheable,
{
    type Ref = P::Ref;
    type Set = P::Set;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error> {
        let key = r.to_string();
        let mut cache = self.cache.lock().await;
        if let Some(res) = cache.get::<Self::Set>(&key) {
            metrics::counter!(STORE_CACHE_HITS).increment(1);
            return Ok(res);
        }
        let res = self.provider.fetch(team_id, r).await?;
        cache.insert(key, res.clone(), res.bytes());
        metrics::counter!(STORE_CACHE_MISSES).increment(1);
        Ok(res)
    }
}

pub struct CacheInner {
    // We expect this cache to consist of few, but large, items.
    // TODO - handle cases where two CachedSymbolSets have identical keys but different types
    cached: HashMap<String, CachedSymbolSet>,
    held_bytes: usize,
    max_bytes: usize,
}

impl CacheInner {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            cached: HashMap::new(),
            held_bytes: 0,
            max_bytes,
        }
    }
}

impl CacheInner {
    fn insert<T>(&mut self, key: String, value: Arc<T>, bytes: usize)
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

    fn get<T>(&mut self, key: &str) -> Option<Arc<T>>
    where
        T: Any + Send + Sync,
    {
        let held = self.cached.get_mut(key).map(|v| {
            v.last_used = Instant::now();
            v
        })?;

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
            // We can unwrap here because we know we're not empty from the line above
            let (to_remove_key, to_remove_val) = vals.pop().unwrap();
            self.held_bytes -= to_remove_val.bytes;
            to_remove.push(to_remove_key.clone());
        }

        for key in to_remove {
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

pub trait Cacheable: Any + Send + Sync {
    fn bytes(&self) -> usize;
}

impl Cacheable for Vec<u8> {
    fn bytes(&self) -> usize {
        self.len()
    }
}

impl Cacheable for SourceMap {
    fn bytes(&self) -> usize {
        // This is an extremely expensive way to get the size of a sourcemap, but we're more-or-less ok with that,
        // since we only call it when we add an item to the cache, which should be rare.
        let mut data = vec![];
        self.to_writer(&mut data).unwrap();
        data.len()
    }
}
