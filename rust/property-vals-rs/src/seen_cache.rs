use quick_cache::{sync, DefaultHashBuilder, Lifecycle, Weighter};

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

#[derive(Clone)]
struct TupleKeyWeighter;

impl Weighter<TupleKey, ()> for TupleKeyWeighter {
    fn weight(&self, key: &TupleKey, _val: &()) -> u64 {
        key.approx_bytes() as u64
    }
}

const ESTIMATED_ENTRY_BYTES: u64 = 256;

type Inner = sync::Cache<TupleKey, (), TupleKeyWeighter, DefaultHashBuilder, EvictingLifecycle>;

pub struct SeenCache {
    cache: Inner,
    worker: &'static str,
}

impl SeenCache {
    pub fn new(max_bytes: u64, worker: &'static str) -> Self {
        let cache = sync::Cache::with(
            (max_bytes / ESTIMATED_ENTRY_BYTES).max(1) as usize,
            max_bytes,
            TupleKeyWeighter,
            DefaultHashBuilder::default(),
            EvictingLifecycle { worker },
        );
        Self { cache, worker }
    }

    pub fn seen(&self, key: &TupleKey) -> bool {
        if self.cache.get(key).is_some() {
            metrics::counter!(SEEN_CACHE_HITS, "worker" => self.worker).increment(1);
            true
        } else {
            metrics::counter!(SEEN_CACHE_MISSES, "worker" => self.worker).increment(1);
            false
        }
    }

    pub fn insert(&self, key: &TupleKey) {
        self.cache.insert(key.clone(), ());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::PropertyType;

    fn tuple(value: String) -> TupleKey {
        TupleKey {
            team_id: 2,
            property_type: PropertyType::Event,
            property_key: "$current_url".to_string(),
            property_value: value,
        }
    }

    #[test]
    fn byte_budget_bounds_retention_not_entry_count() {
        let entry_bytes = tuple("x".repeat(1000)).approx_bytes() as u64;
        let cache = SeenCache::new(entry_bytes * 100, "test");

        let keys: Vec<TupleKey> = (0..1000).map(|i| tuple(format!("{i:0>1000}"))).collect();
        for key in &keys {
            cache.insert(key);
        }

        let retained = keys.iter().filter(|k| cache.seen(k)).count();
        assert!(
            retained <= 100,
            "byte budget of 100 entries retained {retained}"
        );
    }
}
