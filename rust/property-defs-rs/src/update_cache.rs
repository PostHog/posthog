use std::sync::RwLock;

use crate::{metrics_consts::UPDATES_CACHE, types::Update};

use quick_cache::unsync;

pub struct Cache {
    lock_chunk_size: usize,
    eventdefs: RwLock<unsync::Cache<Update, ()>>,
    eventprops: RwLock<unsync::Cache<Update, ()>>,
    propdefs: RwLock<unsync::Cache<Update, ()>>,
}

impl Cache {
    pub fn new(capacity: usize, lock_chunk_size: usize) -> Self {
        Self {
            lock_chunk_size,
            eventdefs: RwLock::new(unsync::Cache::new(capacity)),
            eventprops: RwLock::new(unsync::Cache::new(capacity)),
            propdefs: RwLock::new(unsync::Cache::new(capacity)),
        }
    }

    pub fn len(&self) -> usize {
        self.eventdefs_len() + self.eventprops_len() + self.propdefs_len()
    }

    pub fn is_empty(&self) -> bool {
        self.propdefs_is_empty() && self.eventdefs_is_empty() && self.eventprops_is_empty()
    }

    pub fn contains_key(&self, key: &Update) -> bool {
        let result = match key {
            Update::Event(_) => {
                let cache = self.eventdefs.read().expect("eventdefs_contains_key: lock");
                cache.contains_key(key)
            }
            Update::EventProperty(_) => {
                let cache = self
                    .eventprops
                    .read()
                    .expect("eventprops_contains_key: lock");
                cache.contains_key(key)
            }
            Update::Property(_) => {
                let cache = self.propdefs.read().expect("propdefs_contains_key: lock");
                cache.contains_key(key)
            }
        };

        match result {
            true => metrics::counter!(UPDATES_CACHE, &[("action", "hit")]).increment(1),
            _ => metrics::counter!(UPDATES_CACHE, &[("action", "miss")]).increment(1),
        };

        result
    }

    pub fn insert_batch(&self, batch: &[Update]) {
        for chunk in batch[..].chunks(self.lock_chunk_size) {
            self.do_insert_batch(chunk)
        }
    }

    pub fn remove_batch(&self, batch: &[Update]) {
        for chunk in batch[..].chunks(self.lock_chunk_size) {
            self.do_remove_batch(chunk)
        }
    }

    pub fn insert(&self, key: Update) {
        match key {
            Update::Event(_) => {
                let mut cache = self.eventdefs.write().expect("eventdefs_insert: lock");
                cache.insert(key, ())
            }
            Update::EventProperty(_) => {
                let mut cache = self.eventprops.write().expect("eventprops_insert: lock");
                cache.insert(key, ())
            }
            Update::Property(_) => {
                let mut cache = self.propdefs.write().expect("propdefs_insert: lock");
                cache.insert(key, ())
            }
        }

        metrics::counter!(UPDATES_CACHE, &[("action", "inserted")]).increment(1);
    }

    // we don't return the retrieved KV since propdefs doesn't require it
    pub fn remove(&self, key: &Update) {
        let result = match key {
            Update::Event(_) => {
                let mut cache = self.eventdefs.write().expect("eventdefs_remove: lock");
                cache.remove(key)
            }
            Update::EventProperty(_) => {
                let mut cache = self.eventprops.write().expect("eventprops_remove: lock");
                cache.remove(key)
            }
            Update::Property(_) => {
                let mut cache = self.propdefs.write().expect("propdefs_remove: lock");
                cache.remove(key)
            }
        };

        if result.is_some() {
            metrics::counter!(UPDATES_CACHE, &[("action", "removed")]).increment(1);
        } else {
            metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")]).increment(1);
        }
    }

    //
    // Private helper methods
    //

    // Assumption: the chunk passed in was size-checked by the caller
    // and includes **only one type** of Update enum variant!
    fn do_insert_batch(&self, chunk: &[Update]) {
        if chunk.is_empty() {
            return;
        }

        let mut hits: u64 = 0;
        let mut misses: u64 = 0;

        match chunk[0] {
            Update::Event(_) => {
                let mut cache = self.eventdefs.write().expect("eventdefs_write: lock");
                for evt_def in chunk {
                    if cache.contains_key(evt_def) {
                        hits += 1
                    } else {
                        cache.insert(evt_def.clone(), ());
                        misses += 1
                    }
                }
            }
            Update::EventProperty(_) => {
                let mut cache = self.eventprops.write().expect("eventprops_write: lock");
                for evt_prop in chunk {
                    if cache.contains_key(evt_prop) {
                        hits += 1
                    } else {
                        cache.insert(evt_prop.clone(), ());
                        misses += 1
                    }
                }
            }
            Update::Property(_) => {
                let mut cache = self.propdefs.write().expect("propdefs_write: lock");
                for prop_def in chunk {
                    if cache.contains_key(prop_def) {
                        hits += 1
                    } else {
                        cache.insert(prop_def.clone(), ());
                        misses += 1
                    }
                }
            }
        }

        metrics::counter!(UPDATES_CACHE, &[("action", "cache_hit")]).increment(hits);
        metrics::counter!(UPDATES_CACHE, &[("action", "cache_miss")]).increment(misses);
        metrics::counter!(UPDATES_CACHE, &[("action", "inserted")]).increment(misses);
    }

    // Assumption: the chunk passed in was size-checked by the caller
    // and includes **only one type** of Update enum variant!
    fn do_remove_batch(&self, chunk: &[Update]) {
        if chunk.is_empty() {
            return;
        }

        let mut removed: u64 = 0;
        let mut not_found: u64 = 0;

        match chunk[0] {
            Update::Event(_) => {
                let mut cache = self.eventdefs.write().expect("eventdefs_write: lock");
                for evt_def in chunk {
                    if cache.remove(evt_def).is_some() {
                        removed += 1
                    } else {
                        not_found += 1
                    }
                }
            }
            Update::EventProperty(_) => {
                let mut cache = self.eventprops.write().expect("eventprops_write: lock");
                for evt_prop in chunk {
                    if cache.remove(evt_prop).is_some() {
                        removed += 1
                    } else {
                        not_found += 1
                    }
                }
            }
            Update::Property(_) => {
                let mut cache = self.propdefs.write().expect("propdefs_write: lock");
                for prop_def in chunk {
                    if cache.remove(prop_def).is_some() {
                        removed += 1
                    } else {
                        not_found += 1
                    }
                }
            }
        }

        metrics::counter!(UPDATES_CACHE, &[("action", "removed")]).increment(removed);
        metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")]).increment(not_found);
    }

    fn eventdefs_len(&self) -> usize {
        let cache = self.eventdefs.read().expect("eventdefs_len: lock");
        cache.len()
    }

    fn eventdefs_is_empty(&self) -> bool {
        let cache = self.eventdefs.read().expect("eventdefs_is_empty: lock");
        cache.is_empty()
    }

    fn eventprops_len(&self) -> usize {
        let cache = self.eventprops.read().expect("eventprops_len: lock");
        cache.len()
    }

    fn eventprops_is_empty(&self) -> bool {
        let cache = self.eventprops.read().expect("eventprops_is_empty: lock");
        cache.is_empty()
    }

    fn propdefs_len(&self) -> usize {
        let cache = self.propdefs.read().expect("propdefs_len: lock");
        cache.len()
    }

    fn propdefs_is_empty(&self) -> bool {
        let cache = self.propdefs.read().expect("propdefs_is_empty: lock");
        cache.is_empty()
    }
}
