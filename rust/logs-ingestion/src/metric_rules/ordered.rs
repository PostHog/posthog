//! A string-keyed map that iterates in insertion order, as a JavaScript `Map` does.

use std::collections::HashMap;

/// Label keys come from log content, so the hash is seeded per process.
#[derive(Debug, Clone)]
pub struct InsertionMap<V> {
    entries: Vec<(String, V)>,
    index: HashMap<String, usize, ahash::RandomState>,
}

impl<V> Default for InsertionMap<V> {
    fn default() -> Self {
        Self {
            entries: Vec::new(),
            index: HashMap::default(),
        }
    }
}

impl<V> InsertionMap<V> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn get(&self, key: &str) -> Option<&V> {
        self.index.get(key).map(|&i| &self.entries[i].1)
    }

    pub fn get_mut(&mut self, key: &str) -> Option<&mut V> {
        self.index.get(key).map(|&i| &mut self.entries[i].1)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.index.contains_key(key)
    }

    /// `map.set(key, value)`: a present key keeps its position.
    pub fn insert(&mut self, key: &str, value: V) -> &mut V {
        let i = match self.index.get(key) {
            Some(&i) => {
                self.entries[i].1 = value;
                i
            }
            None => {
                self.entries.push((key.to_string(), value));
                self.index.insert(key.to_string(), self.entries.len() - 1);
                self.entries.len() - 1
            }
        };
        &mut self.entries[i].1
    }

    pub fn get_or_insert_with(&mut self, key: &str, make: impl FnOnce() -> V) -> &mut V {
        if !self.index.contains_key(key) {
            self.insert(key, make());
        }
        let i = self.index[key];
        &mut self.entries[i].1
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &V)> + '_ {
        self.entries.iter().map(|(k, v)| (k.as_str(), v))
    }

    pub fn values(&self) -> impl Iterator<Item = &V> + '_ {
        self.entries.iter().map(|(_, v)| v)
    }
}
