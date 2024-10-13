use std::{collections::HashMap, sync::Arc, time::Instant};

use axum::async_trait;
use tokio::sync::Mutex;

use crate::{
    error::Error,
    metric_consts::{
        STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_HITS, STORE_CACHE_MISSES,
        STORE_CACHE_SIZE,
    },
};

use super::{SymbolSetRef, SymbolStore};

pub struct CachingStore {
    inner: Box<dyn SymbolStore>,
    cache: Mutex<CacheInner>,
}

impl CachingStore {
    pub fn new(inner: Box<dyn SymbolStore>, max_bytes: usize) -> Self {
        metrics::gauge!(STORE_CACHE_SIZE).set(max_bytes as f64);
        Self {
            inner,
            cache: Mutex::new(CacheInner {
                cached: Default::default(),
                max_bytes,
                held_bytes: 0,
            }),
        }
    }
}

#[async_trait]
impl SymbolStore for CachingStore {
    async fn fetch(&self, team_id: i32, r: SymbolSetRef) -> Result<Arc<Vec<u8>>, Error> {
        let mut cache = self.cache.lock().await;

        if let Some(cached) = cache.get(&r) {
            metrics::counter!(STORE_CACHE_HITS).increment(1);
            return Ok(cached);
        }
        metrics::counter!(STORE_CACHE_MISSES).increment(1);

        /*
        Implementation decision re: saving of frame resolution results:
        We don't cache failed symbol set lookups, which is a risk - for errors where we're
        failing at a parsing step (so we do the fetch and collect the body), we'll
        end up doing a LOT of work on every single frame emitting that setref, every
        time we see it.

        We could cache the error, with some short TTL - and that might get us 80% of
        the benefit, but it's complicated by how we save the results of frame resolution.

        We have talked about saving the entire resolved stack trace - so mapping from a
        "raw" stack to a resolved one in totality, and that's the most straightforward
        route, but /if/ we instead stored every, say, {team_id, setref, raw_frame, Option<resolved_frame>},
        we get some nice benefits - we can skip the resolving step for frames we've seen before,
        even if we're seeing them in a new stack, and if someone comes along and gives us
        a symbol set we didn't have before, rather than invalidating every resolution
        result that contained a frame referencing the new symbol set, we just invalidate
        the frames specifically, and re-resolve only them (not the full stack). The downside of this
        is, when we get a stack, rather than fetching one value from our store, we have
        to fetch N, but this isn't the end of the world I think.

        The link between save-per-stack and save-per-frame and this decision about caching failed
        symbol set lookups is that, if we save per-frame, it becomes very easy to simply cache failed
        lookups, with some short TTL (think seconds/minutes) - we can drop the failed symbol set
        lookup result fairly aggressively, because we know we're permanently (barring a user giving
        us a new symbol set) saving the failed frame resolve, and each set only contains symbols for
        so many frames. If instead we save per-stack, for every new stack that frame shows up in,
        we have to re-resolve it, so we'd want to be more complete in our approach to caching failed
        symbol set lookups. Basically, the more granular saving approach lets us be more confident about
        how often we'll be re-resolving the same frame, and that tells us how hard we need to try and
        handle the failed symbol set lookup case "perfectly".

        I'm leaning towards saving on a per-frame basis. We'd still be mapping to an error group
        based on the total stack trace, of course.
        */
        // We hold the cache lock across the underlying fetch, so that if two threads
        // are racing to fetch the same item, we don't end up doing the request/data transfer twice.
        let res = self.inner.fetch(team_id, r.clone()).await?;

        cache.insert(r, Arc::clone(&res));

        Ok(res)
    }
}

struct CacheInner {
    // We expect this cache to consist of few, but large, items.
    cached: HashMap<SymbolSetRef, CachedSymbolSet>,
    held_bytes: usize,
    max_bytes: usize,
}

// TODO - someone smarter than me should replace all this with a proper caching lib,
// but I'm too lazy, I uhh mean task focused, to go evaluate one right now.
impl CacheInner {
    fn insert(&mut self, key: SymbolSetRef, value: Arc<Vec<u8>>) {
        self.held_bytes += value.len();
        self.cached.insert(
            key,
            CachedSymbolSet {
                data: value,
                last_used: Instant::now(),
            },
        );

        self.evict();
    }

    fn get(&mut self, key: &SymbolSetRef) -> Option<Arc<Vec<u8>>> {
        self.cached.get_mut(key).map(|v| {
            v.last_used = Instant::now();
            Arc::clone(&v.data)
        })
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
            self.held_bytes -= to_remove_val.data.len();
            to_remove.push(to_remove_key.clone());
        }

        for key in to_remove {
            self.cached.remove(&key);
        }

        metrics::gauge!(STORE_CACHED_BYTES).set(self.held_bytes as f64);
    }
}

struct CachedSymbolSet {
    pub data: Arc<Vec<u8>>,
    pub last_used: Instant,
}
