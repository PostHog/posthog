use crate::{metrics_consts::UPDATES_CACHE, types::Update};
use quick_cache::sync;

pub struct Cache {
    eventdefs: sync::Cache<Update, ()>,
    eventprops: sync::Cache<Update, ()>,
    propdefs: sync::Cache<Update, ()>,
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
            eventdefs: sync::Cache::new(eventdefs_capacity),
            eventprops: sync::Cache::new(eventprops_capacity),
            propdefs: sync::Cache::new(propdefs_capacity),
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

    pub fn eventdefs_hits(&self) -> u64 {
        self.eventdefs.hits()
    }

    pub fn eventdefs_misses(&self) -> u64 {
        self.eventdefs.misses()
    }

    pub fn eventprops_hits(&self) -> u64 {
        self.eventprops.hits()
    }

    pub fn eventprops_misses(&self) -> u64 {
        self.eventprops.misses()
    }

    pub fn propdefs_hits(&self) -> u64 {
        self.propdefs.hits()
    }

    pub fn propdefs_misses(&self) -> u64 {
        self.propdefs.misses()
    }

    pub fn is_empty(&self) -> bool {
        self.propdefs.is_empty() && self.eventdefs.is_empty() && self.eventprops.is_empty()
    }

    pub fn contains_key(&self, key: &Update) -> bool {
        match key {
            Update::Event(_) => self.eventdefs.contains_key(key),
            Update::EventProperty(_) => self.eventprops.contains_key(key),
            Update::Property(_) => self.propdefs.contains_key(key),
        }
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
