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
    pub fn new(capacity: usize) -> Self {
        Self {
            eventdefs: sync::Cache::new(capacity),
            eventprops: sync::Cache::new(capacity),
            propdefs: sync::Cache::new(capacity),
        }
    }

    pub fn len(&self) -> usize {
        self.eventdefs.len() + self.eventprops.len() + self.propdefs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.propdefs.is_empty() && self.eventdefs.is_empty() && self.eventprops.is_empty()
    }

    pub fn contains_key(&self, key: &Update) -> bool {
        let result = match key {
            Update::Event(_) => self.eventdefs.contains_key(key),
            Update::EventProperty(_) => self.eventprops.contains_key(key),
            Update::Property(_) => self.propdefs.contains_key(key),
        };

        match result {
            true => metrics::counter!(UPDATES_CACHE, &[("action", "hit")]).increment(1),
            _ => metrics::counter!(UPDATES_CACHE, &[("action", "miss")]).increment(1),
        };

        result
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
