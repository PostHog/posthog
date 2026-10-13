//! Cross-message dedup of the refs the ML mirror produces to the scrub and fetch topics.
//!
//! The cache lives outside the V8 heap, because hundreds of thousands of small entries held there
//! add marking work to every major GC.

use std::num::NonZeroUsize;
use std::sync::{Mutex, MutexGuard};

use lru::LruCache;
use sha2::{Digest, Sha256};

/// A ghost hit means a cache of twice the capacity would still have held the ref. Sampling one
/// eviction in this many keeps the ghost list near 6% of the cache's own memory.
const GHOST_SAMPLE_RATE: u32 = 16;

/// A truncated SHA-256. At a million live entries the chance of any collision is near 2^-88.
pub type DedupKey = [u8; 16];

fn digest(parts: &[&[u8]]) -> DedupKey {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    let full = hasher.finalize();
    let mut key = [0u8; 16];
    key.copy_from_slice(&full[..16]);
    key
}

pub fn image_ref_key(reference: &str) -> DedupKey {
    digest(&[reference.as_bytes()])
}

/// A transport URL dedups per ref, per URL and per time bucket. A new bucket makes the URL
/// eligible again, so a mutable image is recrawled before its crawl history expires.
pub fn transport_url_key(reference: &str, url: &str, time_bucket: u64) -> DedupKey {
    digest(&[
        reference.as_bytes(),
        b"\0",
        url.as_bytes(),
        b"\0",
        &time_bucket.to_le_bytes(),
    ])
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct DedupStats {
    pub entries: u64,
    pub evictions: u64,
    /// Sampled misses on a ref that a cache of twice the capacity would still have held.
    pub would_hit: u64,
    pub would_miss: u64,
}

struct State {
    cache: LruCache<DedupKey, ()>,
    ghost: LruCache<DedupKey, ()>,
    evictions: u64,
    would_hit: u64,
    would_miss: u64,
}

impl State {
    fn probe_miss(&mut self, key: &DedupKey) {
        if !is_sampled(key) {
            return;
        }
        // pop, not get: a ghost entry that renewed its own recency would score would_hit forever.
        if self.ghost.pop(key).is_some() {
            self.would_hit += 1;
        } else {
            self.would_miss += 1;
        }
    }

    fn claim(&mut self, key: DedupKey) -> bool {
        if self.cache.get(&key).is_some() {
            return false;
        }
        self.probe_miss(&key);
        if let Some((evicted, ())) = self.cache.push(key, ()) {
            self.evictions += 1;
            if is_sampled(&evicted) {
                self.ghost.put(evicted, ());
            }
        }
        true
    }
}

fn is_sampled(key: &DedupKey) -> bool {
    u32::from_le_bytes([key[0], key[1], key[2], key[3]]).is_multiple_of(GHOST_SAMPLE_RATE)
}

/// An LRU of refs already produced. A capacity of 0 disables dedup, so every ref produces.
pub struct RefDedupCache {
    state: Option<Mutex<State>>,
}

impl RefDedupCache {
    pub fn new(capacity: usize) -> Self {
        let state = NonZeroUsize::new(capacity).map(|capacity| {
            let ghost_capacity = NonZeroUsize::new(capacity.get() / GHOST_SAMPLE_RATE as usize)
                .unwrap_or(NonZeroUsize::MIN);
            Mutex::new(State {
                cache: LruCache::new(capacity),
                ghost: LruCache::new(ghost_capacity),
                evictions: 0,
                would_hit: 0,
                would_miss: 0,
            })
        });
        Self { state }
    }

    fn lock(&self) -> Option<MutexGuard<'_, State>> {
        // A poisoned lock only means another thread panicked mid-update, and the LRU is still valid.
        self.state.as_ref().map(|state| {
            state
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
        })
    }

    /// Keeps the items whose key is not cached, without marking them, and returns how many it
    /// dropped. A cached key gets renewed recency, so a ref that keeps recurring stays cached.
    pub fn retain_absent<T>(&self, items: &mut Vec<T>, key_of: impl Fn(&T) -> DedupKey) -> usize {
        if self.state.is_none() {
            return 0;
        }
        // The event loop's claims wait on this lock, so the hashing happens before it is taken.
        let keys: Vec<DedupKey> = items.iter().map(key_of).collect();
        let absent: Vec<bool> = match self.lock() {
            Some(mut state) => keys
                .iter()
                .map(|key| state.cache.get(key).is_none())
                .collect(),
            None => return 0,
        };
        let before = items.len();
        let mut absent = absent.into_iter();
        items.retain(|_| absent.next().unwrap_or(true));
        before - items.len()
    }

    pub fn claim(&self, keys: &[DedupKey]) -> Vec<bool> {
        match self.lock() {
            Some(mut state) => keys.iter().map(|key| state.claim(*key)).collect(),
            None => vec![true; keys.len()],
        }
    }

    pub fn release(&self, keys: &[DedupKey]) {
        if let Some(mut state) = self.lock() {
            for key in keys {
                state.cache.pop(key);
            }
        }
    }

    pub fn stats(&self) -> DedupStats {
        self.lock()
            .map_or_else(DedupStats::default, |state| DedupStats {
                entries: state.cache.len() as u64,
                evictions: state.evictions,
                would_hit: state.would_hit,
                would_miss: state.would_miss,
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(n: u32) -> DedupKey {
        image_ref_key(&format!("image:1:{n}"))
    }

    #[test]
    fn claims_a_key_once_until_released() {
        let cache = RefDedupCache::new(10);
        assert_eq!(cache.claim(&[key(1), key(1)]), vec![true, false]);
        assert_eq!(cache.claim(&[key(1)]), vec![false]);
        cache.release(&[key(1)]);
        assert_eq!(cache.claim(&[key(1)]), vec![true]);
    }

    #[test]
    fn retain_absent_filters_without_marking() {
        let cache = RefDedupCache::new(10);
        cache.claim(&[key(1)]);
        let mut items = vec![1, 2, 3];
        assert_eq!(cache.retain_absent(&mut items, |n| key(*n)), 1);
        assert_eq!(items, vec![2, 3]);
        assert_eq!(cache.claim(&[key(2)]), vec![true]);
    }

    #[test]
    fn evicts_the_least_recently_used_key() {
        let cache = RefDedupCache::new(2);
        cache.claim(&[key(1), key(2)]);
        let mut renewed = vec![1];
        cache.retain_absent(&mut renewed, |n| key(*n));
        cache.claim(&[key(3)]);
        assert_eq!(cache.claim(&[key(1), key(2)]), vec![false, true]);
        assert_eq!(cache.stats().evictions, 2);
    }

    #[test]
    fn zero_capacity_produces_every_ref() {
        let cache = RefDedupCache::new(0);
        assert_eq!(cache.claim(&[key(1), key(1)]), vec![true, true]);
        let mut items = vec![1];
        assert_eq!(cache.retain_absent(&mut items, |n| key(*n)), 0);
        assert_eq!(cache.stats(), DedupStats::default());
    }

    #[test]
    fn a_sampled_miss_on_a_recent_eviction_scores_would_hit_once() {
        let sampled = (0..).map(key).find(is_sampled).unwrap();
        let fillers: Vec<DedupKey> = (100_000..)
            .map(key)
            .filter(|k| !is_sampled(k))
            .take(16)
            .collect();
        let cache = RefDedupCache::new(16);
        cache.claim(&[sampled]);
        cache.claim(&fillers);
        cache.claim(&[sampled]);
        cache.release(&[sampled]);
        cache.claim(&[sampled]);
        let stats = cache.stats();
        assert_eq!(stats.would_hit, 1);
        assert_eq!(stats.would_miss, 2);
    }

    #[test]
    fn transport_url_keys_differ_by_time_bucket() {
        assert_ne!(
            transport_url_key("imageurl:a", "https://example.com/a.png", 1),
            transport_url_key("imageurl:a", "https://example.com/a.png", 2)
        );
    }
}
