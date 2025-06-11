use crate::types::Update;
use quick_cache::sync;

pub struct Cache {
    eventdefs: sync::Cache<Update, ()>,
    eventprops: sync::Cache<Update, ()>,
    propdefs: sync::Cache<Update, ()>,
}

impl Cache {
    pub fn new(capacity: usize) -> Self {
        Self {
            eventdefs: sync::Cache::new(capacity),
            eventprops: sync::Cache::new(capacity),
            propdefs: sync::Cache::new(capacity),
        }
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
        match key {
            Update::Event(_) => self.eventdefs.remove(key),
            Update::EventProperty(_) => self.eventprops.remove(key),
            Update::Property(_) => self.propdefs.remove(key),
        };
    }
}
