use crate::{
    metrics_consts::{CACHE_EVICTIONS, CACHE_HITS, CACHE_MISSES, UPDATES_CACHE},
    types::Update,
};
use metrics::Counter;
use quick_cache::{sync, DefaultHashBuilder, Lifecycle, UnitWeighter};

// Per-subcache eviction observer. The `stats` feature of quick_cache is not
// enabled, so all cache hit/miss/eviction signal in this service comes from
// explicit metrics emitted here and in `contains_key`.
//
// Counter handles are resolved once at construction and reused: these paths run
// per update (and `on_evict` runs under the shard write lock), so a registry
// lookup per increment is measurable CPU. The metrics recorder must be installed
// before `Cache::new`, because a handle resolved earlier is a no-op forever.
#[derive(Clone)]
struct EvictingLifecycle {
    evictions: Counter,
}

impl Lifecycle<Update, ()> for EvictingLifecycle {
    type RequestState = ();

    fn begin_request(&self) -> Self::RequestState {}

    fn on_evict(&self, _state: &mut Self::RequestState, _key: Update, _val: ()) {
        self.evictions.increment(1);
    }
}

type SubCache = sync::Cache<Update, (), UnitWeighter, DefaultHashBuilder, EvictingLifecycle>;

struct SubCacheEntry {
    cache: SubCache,
    hits: Counter,
    misses: Counter,
}

fn build_subcache(capacity: usize, label: &'static str) -> SubCacheEntry {
    let cache = sync::Cache::with(
        capacity,
        capacity as u64,
        UnitWeighter,
        DefaultHashBuilder::default(),
        EvictingLifecycle {
            evictions: metrics::counter!(CACHE_EVICTIONS, &[("cache", label)]),
        },
    );
    SubCacheEntry {
        cache,
        hits: metrics::counter!(CACHE_HITS, &[("cache", label)]),
        misses: metrics::counter!(CACHE_MISSES, &[("cache", label)]),
    }
}

pub struct Cache {
    eventdefs: SubCacheEntry,
    eventprops: SubCacheEntry,
    propdefs: SubCacheEntry,
    removed: Counter,
    not_cached: Counter,
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
            removed: metrics::counter!(UPDATES_CACHE, &[("action", "removed")]),
            not_cached: metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")]),
        }
    }

    fn entry_for(&self, key: &Update) -> &SubCacheEntry {
        match key {
            Update::Event(_) => &self.eventdefs,
            Update::EventProperty(_) => &self.eventprops,
            Update::Property(_) => &self.propdefs,
        }
    }

    pub fn eventdefs_len(&self) -> usize {
        self.eventdefs.cache.len()
    }

    pub fn eventprops_len(&self) -> usize {
        self.eventprops.cache.len()
    }

    pub fn propdefs_len(&self) -> usize {
        self.propdefs.cache.len()
    }

    pub fn contains_key(&self, key: &Update) -> bool {
        let entry = self.entry_for(key);
        // `get` marks the entry referenced, which quick_cache's S3-FIFO eviction
        // uses to keep the working set resident. The `contains_key` of quick_cache
        // skips that marking, so every entry looks cold at eviction time and the
        // cache degrades to FIFO: live keys cycle out and each cycle costs a
        // useless definition upsert against Postgres.
        let found = entry.cache.get(key).is_some();
        if found {
            entry.hits.increment(1);
        } else {
            entry.misses.increment(1);
        }
        found
    }

    pub fn insert(&self, key: Update) {
        self.entry_for(&key).cache.insert(key, ());
    }

    // we don't return the retrieved KV since propdefs doesn't require it
    pub fn remove(&self, key: &Update) {
        let result = self.entry_for(key).cache.remove(key);

        if result.is_some() {
            self.removed.increment(1);
        } else {
            self.not_cached.increment(1);
        }
    }
}
