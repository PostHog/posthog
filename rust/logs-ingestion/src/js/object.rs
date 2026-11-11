//! Own-property key order: array-index keys first in numeric order, then insertion order. The flatten picks survivors from that order.

use std::collections::BTreeMap;
use std::sync::LazyLock;

use hashbrown::HashTable;

use super::{JsString, JsValue};

/// Keys are sender-controlled, so the hash is seeded per process.
static KEY_HASHER: LazyLock<ahash::RandomState> = LazyLock::new(ahash::RandomState::new);

pub(crate) fn hash_key(key: &JsString) -> u64 {
    KEY_HASHER.hash_one(key.bytes_wtf8())
}

pub(crate) fn hash_str(key: &str) -> u64 {
    KEY_HASHER.hash_one(key.as_bytes())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JsKey<'a> {
    Index(u32),
    Named(&'a JsString),
}

impl JsKey<'_> {
    pub fn utf8_byte_len(&self) -> usize {
        match self {
            JsKey::Index(n) => itoa::Buffer::new().format(*n).len(),
            JsKey::Named(k) => k.utf8_byte_len(),
        }
    }

    pub fn push_onto(&self, out: &mut JsString) {
        match self {
            JsKey::Index(n) => out.push_str(itoa::Buffer::new().format(*n)),
            JsKey::Named(k) => out.push_js(k),
        }
    }

    pub fn to_js_string(&self) -> JsString {
        let mut out = JsString::new();
        self.push_onto(&mut out);
        out
    }
}

/// A canonical array index: an integer from 0 to 2^32 - 2 written without a sign or leading zero.
pub fn is_array_index(key: &str) -> Option<u32> {
    let bytes = key.as_bytes();
    if bytes.is_empty() || bytes.len() > 10 || !bytes.iter().all(u8::is_ascii_digit) {
        return None;
    }
    if bytes.len() > 1 && bytes[0] == b'0' {
        return None;
    }
    let n: u64 = key.parse().ok()?;
    if n < u32::MAX as u64 {
        Some(n as u32)
    } else {
        None
    }
}

#[derive(Debug, Clone, Default)]
pub struct JsObject {
    /// Array-index keys. A tree keeps a descending insert order from being quadratic.
    indexed: BTreeMap<u32, JsValue>,
    named: Vec<(JsString, JsValue)>,
    /// Built only for large objects, where a linear key search would be quadratic.
    named_index: Option<HashTable<usize>>,
}

const INDEX_THRESHOLD: usize = 16;

impl JsObject {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.indexed.len() + self.named.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn named_position(&self, key: &JsString) -> Option<usize> {
        match &self.named_index {
            Some(index) => index
                .find(hash_key(key), |&i| self.named[i].0 == *key)
                .copied(),
            None => self.named.iter().position(|(k, _)| k == key),
        }
    }

    fn build_index(&mut self) {
        let mut index = HashTable::with_capacity(self.named.len());
        for (i, (k, _)) in self.named.iter().enumerate() {
            index.insert_unique(hash_key(k), i, |&j| hash_key(&self.named[j].0));
        }
        self.named_index = Some(index);
    }

    fn index_key(key: &JsString) -> Option<u32> {
        key.as_str().and_then(is_array_index)
    }

    /// `obj[key] = value` on an own data property: an existing key keeps its position.
    pub fn insert(&mut self, key: JsString, value: JsValue) {
        if let Some(n) = Self::index_key(&key) {
            self.indexed.insert(n, value);
            return;
        }
        if let Some(i) = self.named_position(&key) {
            self.named[i].1 = value;
            return;
        }
        if let Some(index) = &mut self.named_index {
            let named = &self.named;
            index.insert_unique(hash_key(&key), named.len(), |&j| hash_key(&named[j].0));
        }
        self.named.push((key, value));
        if self.named_index.is_none() && self.named.len() > INDEX_THRESHOLD {
            self.build_index();
        }
    }

    pub fn insert_str(&mut self, key: &str, value: JsValue) {
        self.insert(JsString::from(key), value)
    }

    pub fn get(&self, key: &str) -> Option<&JsValue> {
        if let Some(n) = is_array_index(key) {
            return self.indexed.get(&n);
        }
        let key = JsString::from(key);
        self.named_position(&key).map(|i| &self.named[i].1)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    pub fn remove(&mut self, key: &str) -> Option<JsValue> {
        if let Some(n) = is_array_index(key) {
            return self.indexed.remove(&n);
        }
        let key = JsString::from(key);
        let i = self.named_position(&key)?;
        let (_, value) = self.named.remove(i);
        if self.named_index.is_some() {
            self.build_index();
        }
        Some(value)
    }

    pub fn iter(&self) -> impl Iterator<Item = (JsString, &JsValue)> + '_ {
        self.indexed
            .iter()
            .map(|(k, v)| (JsString::from(k.to_string()), v))
            .chain(self.named.iter().map(|(k, v)| (k.clone(), v)))
    }

    pub fn entries(&self) -> impl Iterator<Item = (JsKey<'_>, &JsValue)> + '_ {
        self.indexed
            .iter()
            .map(|(k, v)| (JsKey::Index(*k), v))
            .chain(self.named.iter().map(|(k, v)| (JsKey::Named(k), v)))
    }

    pub fn keys(&self) -> impl Iterator<Item = JsString> + '_ {
        self.iter().map(|(k, _)| k)
    }
}

impl PartialEq for JsObject {
    fn eq(&self, other: &Self) -> bool {
        self.indexed == other.indexed && self.named == other.named
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(o: &JsObject) -> Vec<String> {
        o.keys().map(|k| k.to_string()).collect()
    }

    #[test]
    fn index_keys_come_first_in_numeric_order() {
        let mut o = JsObject::new();
        for k in [
            "b",
            "10",
            "a",
            "2",
            "01",
            "4294967295",
            "4294967294",
            "-1",
            "0",
        ] {
            o.insert_str(k, JsValue::Null);
        }
        assert_eq!(
            keys(&o),
            [
                "0",
                "2",
                "10",
                "4294967294",
                "b",
                "a",
                "01",
                "4294967295",
                "-1"
            ]
        );
    }

    #[test]
    fn reinsert_keeps_position_and_remove_works() {
        let mut o = JsObject::new();
        o.insert_str("x", JsValue::Number(1.0));
        o.insert_str("y", JsValue::Number(2.0));
        o.insert_str("x", JsValue::Number(3.0));
        assert_eq!(keys(&o), ["x", "y"]);
        assert_eq!(o.get("x"), Some(&JsValue::Number(3.0)));
        o.remove("x");
        o.insert_str("x", JsValue::Null);
        assert_eq!(keys(&o), ["y", "x"]);
    }

    #[test]
    fn large_objects_keep_order_with_the_index() {
        let mut o = JsObject::new();
        for i in 0..100 {
            o.insert_str(&format!("k{}", 99 - i), JsValue::Number(i as f64));
        }
        o.insert_str("k50", JsValue::Null);
        assert_eq!(o.len(), 100);
        assert_eq!(keys(&o)[0], "k99");
        assert_eq!(o.get("k50"), Some(&JsValue::Null));
        o.remove("k99");
        assert_eq!(keys(&o)[0], "k98");
        assert!(o.contains_key("k0"));
    }
}
