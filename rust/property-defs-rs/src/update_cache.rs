use crate::{
    metrics_consts::{CACHE_EVICTIONS, CACHE_HITS, CACHE_MISSES, UPDATES_CACHE},
    types::Update,
};
use quick_cache::{sync, DefaultHashBuilder, Lifecycle, UnitWeighter};

// Per-subcache eviction observer. quick_cache's built-in `stats` feature
// only tracks hits/misses on `get`/`get_key_value` paths (not `contains_key`/
// `insert`, which is what we use), so all cache hit/miss/eviction signal in
// this service comes from explicit metrics emitted here and in `contains_key`.
#[derive(Clone)]
struct EvictingLifecycle {
    cache_label: &'static str,
}

impl Lifecycle<Update, ()> for EvictingLifecycle {
    type RequestState = ();

    fn begin_request(&self) -> Self::RequestState {}

    fn on_evict(&self, _state: &mut Self::RequestState, _key: Update, _val: ()) {
        metrics::counter!(CACHE_EVICTIONS, &[("cache", self.cache_label)]).increment(1);
    }
}

type SubCache = sync::Cache<Update, (), UnitWeighter, DefaultHashBuilder, EvictingLifecycle>;

fn build_subcache(capacity: usize, label: &'static str) -> SubCache {
    sync::Cache::with(
        capacity,
        capacity as u64,
        UnitWeighter,
        DefaultHashBuilder::default(),
        EvictingLifecycle { cache_label: label },
    )
}

pub struct Cache {
    eventdefs: SubCache,
    eventprops: SubCache,
    propdefs: SubCache,
}

// TODO: next iter, try using unsync::Cache(s) here and manage sync access to each
// manually. This enables implementing new batch insert/remove APIs on this wrapper,
// since we rarely want to work with just one cache entry at a time in propdefs. I
// suspect small-batch updates would further reduce internal cache lock contention
// that can slow down our batch write threads, esp. when a write fails and we evict
impl Cache {
    pub fn new(
        eventdefs_capacity: usize,
        eventprops_capacity: usize,
        propdefs_capacity: usize,
    ) -> Self {
        Self {
            eventdefs: build_subcache(eventdefs_capacity, "eventdefs"),
            eventprops: build_subcache(eventprops_capacity, "eventprops"),
            propdefs: build_subcache(propdefs_capacity, "propdefs"),
        }
    }

    pub fn len(&self) -> usize {
        self.eventdefs.len() + self.eventprops.len() + self.propdefs.len()
    }

    pub fn eventdefs_len(&self) -> usize {
        self.eventdefs.len()
    }

    pub fn eventprops_len(&self) -> usize {
        self.eventprops.len()
    }

    pub fn propdefs_len(&self) -> usize {
        self.propdefs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.propdefs.is_empty() && self.eventdefs.is_empty() && self.eventprops.is_empty()
    }

    pub fn contains_key(&self, key: &Update) -> bool {
        let (found, label) = match key {
            Update::Event(_) => (self.eventdefs.contains_key(key), "eventdefs"),
            Update::EventProperty(_) => (self.eventprops.contains_key(key), "eventprops"),
            Update::Property(_) => (self.propdefs.contains_key(key), "propdefs"),
        };
        if found {
            metrics::counter!(CACHE_HITS, &[("cache", label)]).increment(1);
        } else {
            metrics::counter!(CACHE_MISSES, &[("cache", label)]).increment(1);
        }
        found
    }

    pub fn insert(&self, key: Update) {
        match key {
            Update::Event(_) => self.eventdefs.insert(key, ()),
            Update::EventProperty(_) => self.eventprops.insert(key, ()),
            Update::Property(_) => self.propdefs.insert(key, ()),
        }
    }

    // we don't return the retrieved KV since propdefs doesn't require it
    pub fn remove(&self, key: &Update) {
        let result = match key {
            Update::Event(_) => self.eventdefs.remove(key),
            Update::EventProperty(_) => self.eventprops.remove(key),
            Update::Property(_) => self.propdefs.remove(key),
        };

        if result.is_some() {
            metrics::counter!(UPDATES_CACHE, &[("action", "removed")]).increment(1);
        } else {
            metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")]).increment(1);
        }
    }
}
