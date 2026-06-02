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
