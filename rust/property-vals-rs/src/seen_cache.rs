use quick_cache::{sync, DefaultHashBuilder, Lifecycle, UnitWeighter};

use crate::metrics_consts::{SEEN_CACHE_EVICTED, SEEN_CACHE_HITS, SEEN_CACHE_MISSES};
use crate::types::TupleKey;

#[derive(Clone)]
struct EvictingLifecycle {
    worker: &'static str,
}

impl Lifecycle<TupleKey, ()> for EvictingLifecycle {
    type RequestState = ();

    fn begin_request(&self) -> Self::RequestState {}

    fn on_evict(&self, _state: &mut Self::RequestState, _key: TupleKey, _val: ()) {
        metrics::counter!(SEEN_CACHE_EVICTED, "worker" => self.worker).increment(1);
    }
}

type Inner = sync::Cache<TupleKey, (), UnitWeighter, DefaultHashBuilder, EvictingLifecycle>;

/// Bounded "already emitted" set for emit-once at the merger. Holds the most
/// recently seen tuples up to `capacity`: a tuple still resident is suppressed
/// (it is already in ClickHouse within the cache horizon), and one that has
/// aged out is re-emitted, with the AggregatingMergeTree absorbing the
/// duplicate. Memory is bounded by `capacity`, not by total tuple cardinality.
pub struct SeenCache {
    cache: Inner,
    worker: &'static str,
}

impl SeenCache {
    pub fn new(capacity: usize, worker: &'static str) -> Self {
        let cache = sync::Cache::with(
            capacity,
            capacity as u64,
            UnitWeighter,
            DefaultHashBuilder::default(),
            EvictingLifecycle { worker },
        );
        Self { cache, worker }
    }

    /// On a hit, returns true (the caller suppresses the tuple) and refreshes
    /// the entry's recency so hot tuples stay resident. On a miss, inserts the
    /// tuple and returns false (the caller emits it).
    pub fn seen_or_insert(&self, key: &TupleKey) -> bool {
        if self.cache.get(key).is_some() {
            metrics::counter!(SEEN_CACHE_HITS, "worker" => self.worker).increment(1);
            true
        } else {
            metrics::counter!(SEEN_CACHE_MISSES, "worker" => self.worker).increment(1);
            self.cache.insert(key.clone(), ());
            false
        }
    }

    /// Undo an insert when the produce that would have persisted the tuple
    /// failed, so the next flush re-emits it instead of suppressing it.
    pub fn forget(&self, key: &TupleKey) {
        self.cache.remove(key);
    }
}
