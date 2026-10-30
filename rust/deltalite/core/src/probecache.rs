//! Process-wide cache of the primary-key hashes of data files, for the upsert probe.
//!
//! The probe decides, for each candidate file of a touched partition, whether the file
//! holds any key of the batch. Without a cache that costs a footer read and a PK-column
//! read per file on every upsert, so on object storage the probe grows with the number of
//! files in the table, not with the batch. A Delta data file never changes after it is
//! written, so the keys a file holds can be kept for as long as the process lives.
//!
//! Each entry is the sorted, deduplicated 64-bit hashes of the file's matchable PK tuples
//! (no NULL component), encoded exactly as [`crate::pkset::PkSet`] encodes them. A file is
//! a candidate when its hashes and the batch's hashes have a common value. A matching key
//! always gives equal hashes, so the cache never skips a file that holds a key. A hash
//! collision can only add a file to the rewrite set, and a rewrite of a file without
//! matches copies every row unchanged, so the table content stays correct.
//!
//! Entries are keyed by the table URL plus the URL-decoded file path, and carry a
//! signature of the PK columns and their types. A PK type change after schema evolution
//! changes the encoding, so an entry with another signature counts as a miss. An upsert
//! evicts the entries of the files it removes after its commit lands; files that another
//! writer removes are never asked for again and age out of the LRU order.

use std::collections::hash_map::DefaultHasher;
use std::collections::{BTreeMap, HashMap};
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use arrow_schema::DataType;

/// Environment variable for the byte cap of the process-wide cache; `0` turns it off.
pub const PROBE_CACHE_BYTES_ENV: &str = "DELTALITE_PROBE_CACHE_BYTES";
/// Default byte cap of the process-wide cache.
pub const DEFAULT_PROBE_CACHE_BYTES: usize = 128 * 1024 * 1024;

/// Fixed bookkeeping cost charged per entry on top of its key and hashes.
const ENTRY_OVERHEAD_BYTES: usize = 128;
/// Reservations for in-flight key collection grow in steps of this size, so a collector
/// touches the shared counter once per step instead of once per batch.
const RESERVE_STEP_BYTES: usize = 64 * 1024;

/// Counters and sizes of a [`ProbeCache`].
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ProbeCacheStats {
    pub entries: usize,
    pub bytes: usize,
    pub max_bytes: usize,
    /// Lookups that found an entry with the right signature.
    pub hits: u64,
    /// Lookups that found no usable entry.
    pub misses: u64,
    /// Entries stored, by a probe or by an upsert that wrote the file.
    pub inserts: u64,
    /// Entries dropped to stay under the byte cap.
    pub evictions: u64,
}

struct Entry {
    signature: u64,
    hashes: Arc<[u64]>,
    tick: u64,
    bytes: usize,
}

#[derive(Default)]
struct Inner {
    map: HashMap<String, Entry>,
    /// Least recently used first.
    order: BTreeMap<u64, String>,
    tick: u64,
    bytes: usize,
}

impl Inner {
    fn remove(&mut self, key: &str) -> bool {
        match self.map.remove(key) {
            Some(e) => {
                self.order.remove(&e.tick);
                self.bytes -= e.bytes;
                true
            }
            None => false,
        }
    }

    fn evict_to(&mut self, max_bytes: usize) -> u64 {
        let mut evicted = 0;
        while self.bytes > max_bytes {
            let Some((_, key)) = self.order.pop_first() else {
                break;
            };
            if let Some(e) = self.map.remove(&key) {
                self.bytes -= e.bytes;
                evicted += 1;
            }
        }
        evicted
    }
}

/// A byte-capped LRU map from data file to the PK hashes the file holds.
pub struct ProbeCache {
    inner: Mutex<Inner>,
    max_bytes: AtomicUsize,
    /// Bytes reserved by collectors that are still reading or writing a file. Kept apart
    /// from `inner.bytes` and capped at a quarter of `max_bytes`, so the memory of the
    /// cache feature stays under 1.25 x `max_bytes` whatever the concurrency.
    collecting: AtomicUsize,
    hits: AtomicU64,
    misses: AtomicU64,
    inserts: AtomicU64,
    evictions: AtomicU64,
}

impl std::fmt::Debug for ProbeCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ProbeCache")
            .field("stats", &self.stats())
            .finish()
    }
}

impl ProbeCache {
    /// A cache that holds at most `max_bytes`; `0` stores nothing.
    pub fn new(max_bytes: usize) -> Self {
        Self {
            inner: Mutex::new(Inner::default()),
            max_bytes: AtomicUsize::new(max_bytes),
            collecting: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            inserts: AtomicU64::new(0),
            evictions: AtomicU64::new(0),
        }
    }

    /// The process-wide cache, sized from [`PROBE_CACHE_BYTES_ENV`] on first use.
    pub fn global() -> &'static Arc<ProbeCache> {
        static GLOBAL: OnceLock<Arc<ProbeCache>> = OnceLock::new();
        GLOBAL.get_or_init(|| Arc::new(ProbeCache::new(max_bytes_from_env())))
    }

    pub fn max_bytes(&self) -> usize {
        self.max_bytes.load(Ordering::Relaxed)
    }

    /// Change the byte cap, evicting least recently used entries down to it.
    pub fn set_max_bytes(&self, max_bytes: usize) {
        self.max_bytes.store(max_bytes, Ordering::Relaxed);
        let evicted = self.lock().evict_to(max_bytes);
        self.evictions.fetch_add(evicted, Ordering::Relaxed);
    }

    pub fn enabled(&self) -> bool {
        self.max_bytes() > 0
    }

    /// Largest entry the cache accepts. A file with more keys than this is probed on every
    /// upsert, so that one huge file cannot push every other entry out.
    pub fn max_entry_bytes(&self) -> usize {
        self.max_bytes() / 8
    }

    pub fn clear(&self) {
        let mut inner = self.lock();
        inner.map.clear();
        inner.order.clear();
        inner.bytes = 0;
    }

    pub fn stats(&self) -> ProbeCacheStats {
        let inner = self.lock();
        ProbeCacheStats {
            entries: inner.map.len(),
            bytes: inner.bytes,
            max_bytes: self.max_bytes(),
            hits: self.hits.load(Ordering::Relaxed),
            misses: self.misses.load(Ordering::Relaxed),
            inserts: self.inserts.load(Ordering::Relaxed),
            evictions: self.evictions.load(Ordering::Relaxed),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        // A panic while the lock is held leaves the map consistent (every mutation is a
        // few map operations), so a poisoned lock is still safe to use.
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// The sorted key hashes of `key`, when an entry with `signature` exists.
    pub(crate) fn get(&self, key: &str, signature: u64) -> Option<Arc<[u64]>> {
        if !self.enabled() {
            return None;
        }
        let mut inner = self.lock();
        inner.tick += 1;
        let tick = inner.tick;
        let found = match inner.map.get_mut(key) {
            Some(e) if e.signature == signature => {
                let old = e.tick;
                e.tick = tick;
                Some((old, e.hashes.clone()))
            }
            _ => None,
        };
        match found {
            Some((old, hashes)) => {
                inner.order.remove(&old);
                inner.order.insert(tick, key.to_string());
                drop(inner);
                self.hits.fetch_add(1, Ordering::Relaxed);
                Some(hashes)
            }
            None => {
                drop(inner);
                self.misses.fetch_add(1, Ordering::Relaxed);
                None
            }
        }
    }

    /// Store the key hashes of a file. `hashes` need not be sorted or unique.
    pub(crate) fn insert(&self, key: String, signature: u64, mut hashes: Vec<u64>) {
        if !self.enabled() {
            return;
        }
        hashes.sort_unstable();
        hashes.dedup();
        // The key is held twice: once in `map` and once in `order`.
        let bytes = hashes.len() * 8 + 2 * key.len() + ENTRY_OVERHEAD_BYTES;
        let mut inner = self.lock();
        // Read the cap under the lock: `set_max_bytes` evicts under it too, so a cap lowered
        // concurrently is never missed by this insertion.
        let max_bytes = self.max_bytes();
        if max_bytes == 0 || bytes > max_bytes / 8 {
            return;
        }
        inner.remove(&key);
        inner.tick += 1;
        let tick = inner.tick;
        inner.order.insert(tick, key.clone());
        inner.map.insert(
            key,
            Entry {
                signature,
                hashes: hashes.into(),
                tick,
                bytes,
            },
        );
        inner.bytes += bytes;
        let evicted = inner.evict_to(max_bytes);
        drop(inner);
        self.inserts.fetch_add(1, Ordering::Relaxed);
        self.evictions.fetch_add(evicted, Ordering::Relaxed);
    }

    /// Drop the entries of files that a commit removed from the table.
    pub(crate) fn remove_all<'a>(&self, keys: impl IntoIterator<Item = &'a str>) {
        let mut inner = self.lock();
        for k in keys {
            inner.remove(k);
        }
    }

    /// Reserve `bytes` more for in-flight collection. Never waits: when the pool is full
    /// the collector gives up and its file is simply not cached.
    fn try_reserve(&self, bytes: usize) -> bool {
        let limit = self.max_bytes() / 4;
        self.collecting
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |cur| {
                let next = cur.checked_add(bytes)?;
                (next <= limit).then_some(next)
            })
            .is_ok()
    }

    fn release(&self, bytes: usize) {
        self.collecting.fetch_sub(bytes, Ordering::AcqRel);
    }

    /// A collector for the key hashes of one file; `None` when the cache is off.
    pub(crate) fn collector(self: &Arc<Self>) -> Option<KeyCollector> {
        self.enabled().then(|| KeyCollector {
            cache: self.clone(),
            hashes: Vec::new(),
            reserved: 0,
            abandoned: false,
        })
    }
}

/// Collects the key hashes of one file while it is read or written. It holds a share of
/// the cache's in-flight pool for the hashes it keeps, and gives up (keeping nothing)
/// once the file would make an entry larger than the cache accepts, or the pool is full.
pub(crate) struct KeyCollector {
    cache: Arc<ProbeCache>,
    hashes: Vec<u64>,
    reserved: usize,
    abandoned: bool,
}

impl KeyCollector {
    /// The buffer to append the hashes of `additional` more rows to, or `None` when the
    /// collector gave up.
    pub(crate) fn reserve(&mut self, additional: usize) -> Option<&mut Vec<u64>> {
        if self.abandoned {
            return None;
        }
        let need_len = self.hashes.len() + additional;
        let max_entry = self.cache.max_entry_bytes();
        if need_len * 8 > max_entry {
            self.abandon();
            return None;
        }
        if need_len > self.hashes.capacity() {
            // Grow the buffer here, geometrically and with an exact capacity, so that the
            // pool is charged for the allocation itself and not just the rows in it.
            let target_len = need_len
                .max(self.hashes.capacity() * 2)
                .max(RESERVE_STEP_BYTES.min(max_entry / 8) / 8)
                .min(max_entry / 8);
            let target_bytes = target_len * 8;
            if target_bytes > self.reserved {
                let step = target_bytes - self.reserved;
                if !self.cache.try_reserve(step) {
                    self.abandon();
                    return None;
                }
                self.reserved += step;
            }
            self.hashes.reserve_exact(target_len - self.hashes.len());
        }
        Some(&mut self.hashes)
    }

    fn abandon(&mut self) {
        self.abandoned = true;
        self.hashes = Vec::new();
        self.cache.release(self.reserved);
        self.reserved = 0;
    }

    /// What was collected, still holding its share of the pool; `None` if it gave up.
    pub(crate) fn finish(mut self) -> Option<CollectedKeys> {
        if self.abandoned {
            return None;
        }
        let reserved = std::mem::take(&mut self.reserved);
        Some(CollectedKeys {
            cache: self.cache.clone(),
            hashes: std::mem::take(&mut self.hashes),
            reserved,
        })
    }

    /// Store what was collected as the entry for `key`. Does nothing if it gave up.
    pub(crate) fn store(self, key: String, signature: u64) {
        if let Some(keys) = self.finish() {
            keys.store(key, signature);
        }
    }
}

impl Drop for KeyCollector {
    fn drop(&mut self) {
        self.cache.release(self.reserved);
    }
}

/// The finished key hashes of one file, waiting to be stored (for a written file, until
/// its commit lands).
pub(crate) struct CollectedKeys {
    cache: Arc<ProbeCache>,
    hashes: Vec<u64>,
    reserved: usize,
}

impl CollectedKeys {
    pub(crate) fn store(mut self, key: String, signature: u64) {
        let hashes = std::mem::take(&mut self.hashes);
        self.cache.insert(key, signature, hashes);
    }
}

impl Drop for CollectedKeys {
    fn drop(&mut self) {
        self.cache.release(self.reserved);
    }
}

fn max_bytes_from_env() -> usize {
    match std::env::var(PROBE_CACHE_BYTES_ENV) {
        Ok(v) => match v.trim().parse::<usize>() {
            Ok(n) => n,
            Err(_) => {
                tracing::warn!(var = PROBE_CACHE_BYTES_ENV, value = %v, "invalid value, using default");
                DEFAULT_PROBE_CACHE_BYTES
            }
        },
        Err(_) => DEFAULT_PROBE_CACHE_BYTES,
    }
}

/// Cache key of a data file: the table URL and the URL-decoded path relative to it.
pub(crate) fn file_key(table_url: &str, decoded_path: &str) -> String {
    let mut key = String::with_capacity(table_url.len() + 1 + decoded_path.len());
    key.push_str(table_url);
    key.push('\n');
    key.push_str(decoded_path);
    key
}

/// Signature of the key encoding: the PK columns, their table types, and the partition
/// column (a PK on the partition column takes its value from the file's path).
pub(crate) fn key_signature(
    primary_keys: &[String],
    pk_types: &[DataType],
    partition_col: Option<&str>,
) -> u64 {
    let mut h = DefaultHasher::new();
    primary_keys.hash(&mut h);
    for t in pk_types {
        format!("{t:?}").hash(&mut h);
    }
    partition_col.hash(&mut h);
    h.finish()
}

/// Hash of one row-encoded PK tuple.
pub(crate) fn hash_key(encoded: &[u8]) -> u64 {
    let mut h = DefaultHasher::new();
    h.write(encoded);
    h.finish()
}

/// Whether two sorted slices share a value.
pub(crate) fn sorted_intersect(a: &[u64], b: &[u64]) -> bool {
    let (small, large) = if a.len() <= b.len() { (a, b) } else { (b, a) };
    if small.is_empty() {
        return false;
    }
    // Binary search wins when one side is much smaller; a merge walk otherwise.
    let log_large = usize::BITS - large.len().leading_zeros();
    if small.len().saturating_mul(log_large as usize) < small.len() + large.len() {
        return small.iter().any(|v| large.binary_search(v).is_ok());
    }
    let (mut i, mut j) = (0, 0);
    while i < small.len() && j < large.len() {
        match small[i].cmp(&large[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => return true,
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry_bytes(n_hashes: usize, key: &str) -> usize {
        n_hashes * 8 + 2 * key.len() + ENTRY_OVERHEAD_BYTES
    }

    #[test]
    fn get_needs_the_same_signature() {
        let c = ProbeCache::new(1 << 20);
        c.insert("t\na".into(), 1, vec![3, 1, 2, 3]);
        assert_eq!(c.get("t\na", 1).as_deref(), Some(&[1u64, 2, 3][..]));
        assert!(c.get("t\na", 2).is_none());
        assert!(c.get("t\nb", 1).is_none());
        let s = c.stats();
        assert_eq!((s.hits, s.misses, s.entries), (1, 2, 1));
    }

    #[test]
    fn eviction_drops_the_least_recently_used_entry() {
        let one = entry_bytes(10, "t\nk0");
        let c = ProbeCache::new(one * 8);
        for i in 0..8 {
            c.insert(format!("t\nk{i}"), 0, (0..10).collect());
        }
        assert!(c.get("t\nk0", 0).is_some());
        c.insert("t\nk8".into(), 0, (0..10).collect());
        assert!(c.get("t\nk1", 0).is_none());
        assert!(c.get("t\nk0", 0).is_some());
        assert!(c.get("t\nk8", 0).is_some());
        assert_eq!(c.stats().bytes, one * 8);
        assert_eq!(c.stats().evictions, 1);

        c.set_max_bytes(one * 2);
        assert_eq!(c.stats().entries, 2);
        assert!(c.get("t\nk0", 0).is_some());
        assert!(c.get("t\nk8", 0).is_some());
    }

    #[test]
    fn an_entry_above_an_eighth_of_the_cap_is_not_stored() {
        let c = ProbeCache::new(8 * entry_bytes(100, "t\na"));
        c.insert("t\na".into(), 0, (0..101).collect());
        assert_eq!(c.stats().entries, 0);
        c.insert("t\na".into(), 0, (0..100).collect());
        assert_eq!(c.stats().entries, 1);
    }

    #[test]
    fn a_zero_cap_stores_and_collects_nothing() {
        let c = Arc::new(ProbeCache::new(0));
        c.insert("t\na".into(), 0, vec![1]);
        assert!(c.get("t\na", 0).is_none());
        assert!(c.collector().is_none());
    }

    #[test]
    fn collectors_give_up_when_the_in_flight_pool_is_full_and_release_on_drop() {
        // Pool = max/4 = 16 steps; one entry = max/8 = 8 steps.
        let c = Arc::new(ProbeCache::new(64 * RESERVE_STEP_BYTES));
        let rows_per_entry = c.max_entry_bytes() / 8;
        let mut a = c.collector().unwrap();
        let mut b = c.collector().unwrap();
        let mut late = c.collector().unwrap();
        assert!(a.reserve(rows_per_entry).is_some());
        assert!(b.reserve(rows_per_entry).is_some());
        assert!(late.reserve(1).is_none());
        assert!(late.finish().is_none());
        drop(a);
        let mut late = c.collector().unwrap();
        assert!(late.reserve(1).is_some());
        // Past the entry cap the collector gives up and keeps nothing.
        assert!(late.reserve(rows_per_entry + 1).is_none());
        let mut kept = c.collector().unwrap();
        kept.reserve(1).unwrap().push(7);
        let kept = kept.finish().unwrap();
        drop(b);
        drop(late);
        assert!(c.collecting.load(Ordering::Acquire) > 0);
        kept.store("t\na".into(), 0);
        assert_eq!(c.collecting.load(Ordering::Acquire), 0);
        assert_eq!(c.get("t\na", 0).as_deref(), Some(&[7u64][..]));
    }

    #[test]
    fn a_collector_is_charged_for_its_whole_allocation() {
        let c = Arc::new(ProbeCache::new(1 << 24));
        let mut k = c.collector().unwrap();
        for _ in 0..3 {
            k.reserve(8192)
                .unwrap()
                .extend(std::iter::repeat_n(1, 8192));
            assert!(k.hashes.capacity() * 8 <= k.reserved);
        }
        assert_eq!(c.collecting.load(Ordering::Acquire), k.reserved);
    }

    #[test]
    fn remove_all_frees_the_bytes() {
        let c = ProbeCache::new(1 << 20);
        c.insert("t\na".into(), 0, vec![1, 2]);
        c.insert("t\nb".into(), 0, vec![1]);
        c.remove_all(["t\na", "t\nmissing"]);
        assert_eq!(c.stats().entries, 1);
        assert_eq!(c.stats().bytes, entry_bytes(1, "t\nb"));
    }

    #[test]
    fn sorted_intersect_matches_a_naive_check() {
        let cases: Vec<(Vec<u64>, Vec<u64>)> = vec![
            (vec![], vec![1, 2]),
            (vec![5], vec![1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]),
            (vec![7], vec![1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]),
            (
                (0..50).map(|v| v * 2).collect(),
                (0..50).map(|v| v * 2 + 1).collect(),
            ),
            ((0..50).map(|v| v * 2).collect(), vec![1, 3, 98]),
            (vec![u64::MAX], vec![0, u64::MAX]),
        ];
        for (a, b) in cases {
            let naive = a.iter().any(|v| b.contains(v));
            assert_eq!(sorted_intersect(&a, &b), naive, "{a:?} {b:?}");
            assert_eq!(sorted_intersect(&b, &a), naive, "{b:?} {a:?}");
        }
    }
}
