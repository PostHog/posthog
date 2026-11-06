//! Decoded Avro values, shaped like the JavaScript values avsc returns.

use std::collections::btree_map::Entry;
use std::collections::BTreeMap;
use std::sync::{Arc, OnceLock};

use hashbrown::HashTable;

use crate::js::is_array_index;
use crate::js::object::hash_str;

#[derive(Debug, Clone, PartialEq)]
pub enum AvroValue {
    Null,
    Boolean(bool),
    /// avsc reads `int` with the `long` varint reader and no range check.
    Int(i64),
    Long(i64),
    Float(f64),
    Double(f64),
    Bytes(Vec<u8>),
    String(String),
    Record(Vec<(Arc<str>, AvroValue)>),
    Enum(String),
    Fixed(Vec<u8>),
    Array(Vec<AvroValue>),
    /// Boxed so the common variants keep `AvroValue` at 32 bytes.
    Map(Box<AvroMap>),
}

impl AvroValue {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            AvroValue::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            AvroValue::Int(n) | AvroValue::Long(n) => Some(*n),
            _ => None,
        }
    }

    pub fn as_map(&self) -> Option<&AvroMap> {
        match self {
            AvroValue::Map(m) => Some(m),
            _ => None,
        }
    }

    pub fn as_bytes(&self) -> Option<&[u8]> {
        match self {
            AvroValue::Bytes(b) | AvroValue::Fixed(b) => Some(b),
            _ => None,
        }
    }

    pub fn is_null(&self) -> bool {
        matches!(self, AvroValue::Null)
    }
}

/// As the plain object avsc builds: a repeated key keeps its first position and takes the last value, and `__proto__` is not an own key.
///
/// A decoded `map<string>` in canonical form keeps its encoded bytes and decodes on first read. Any write drops the bytes, and the encoder copies the bytes while they are kept.
pub struct AvroMap {
    raw: Option<Box<[u8]>>,
    data: OnceLock<MapData>,
}

impl Default for AvroMap {
    fn default() -> Self {
        Self {
            raw: None,
            data: OnceLock::from(MapData::default()),
        }
    }
}

impl Clone for AvroMap {
    fn clone(&self) -> Self {
        Self {
            raw: self.raw.clone(),
            data: match self.data.get() {
                Some(data) => OnceLock::from(data.clone()),
                None => OnceLock::new(),
            },
        }
    }
}

impl std::fmt::Debug for AvroMap {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.data().fmt(f)
    }
}

impl PartialEq for AvroMap {
    fn eq(&self, other: &Self) -> bool {
        // Canonical bytes are equal exactly when the decoded entries are equal, in order.
        if let (Some(a), Some(b)) = (&self.raw, &other.raw) {
            return a == b;
        }
        self.data() == other.data()
    }
}

impl AvroMap {
    pub fn new() -> Self {
        Self::default()
    }

    pub(crate) fn from_canonical_string_map(raw: &[u8]) -> Self {
        Self {
            raw: Some(raw.into()),
            data: OnceLock::new(),
        }
    }

    pub(crate) fn canonical_bytes(&self) -> Option<&[u8]> {
        self.raw.as_deref()
    }

    fn data(&self) -> &MapData {
        self.data.get_or_init(|| {
            MapData::from_canonical_string_map(
                self.raw
                    .as_deref()
                    .expect("a map without data keeps its bytes"),
            )
        })
    }

    fn data_mut(&mut self) -> &mut MapData {
        self.data();
        self.raw = None;
        self.data.get_mut().expect("initialized above")
    }

    pub fn assign(&mut self, key: String, value: AvroValue) {
        self.data_mut().assign(key, value)
    }

    /// Unlike `assign`, this keeps a `__proto__` key, as object spread and `Object.fromEntries` do.
    pub fn define(&mut self, key: String, value: AvroValue) {
        self.data_mut().define(key, value)
    }

    pub fn get(&self, key: &str) -> Option<&AvroValue> {
        self.data().get(key)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    pub fn remove(&mut self, key: &str) -> Option<AvroValue> {
        self.data().get(key)?;
        self.data_mut().remove(key)
    }

    pub fn len(&self) -> usize {
        self.data().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &AvroValue)> + '_ {
        self.data().iter()
    }

    pub fn into_entries(mut self) -> impl Iterator<Item = (String, AvroValue)> {
        self.data();
        self.data.take().expect("initialized above").into_entries()
    }

    pub fn values_mut(&mut self) -> impl Iterator<Item = &mut AvroValue> + '_ {
        self.data_mut().values_mut()
    }

    pub fn iter_strings(&self) -> impl Iterator<Item = (&str, &str)> + '_ {
        self.iter().filter_map(|(k, v)| v.as_str().map(|s| (k, s)))
    }

    pub fn string_bytes_len(&self) -> usize {
        match (&self.raw, self.data.get()) {
            (Some(raw), None) => {
                let mut tap = super::decode::Tap::new(raw);
                let n = tap.read_long() as usize;
                let mut total = 0;
                for _ in 0..2 * n {
                    total += tap.read_bytes().map_or(0, <[u8]>::len);
                }
                total
            }
            _ => self.iter_strings().map(|(k, v)| k.len() + v.len()).sum(),
        }
    }

    pub fn from_strings<'a>(entries: impl IntoIterator<Item = (&'a str, &'a str)>) -> Self {
        let mut map = Self::new();
        for (k, v) in entries {
            map.assign(k.to_string(), AvroValue::String(v.to_string()));
        }
        map
    }
}

#[derive(Debug, Clone, Default)]
struct MapData {
    /// Array-index keys. A tree keeps a descending insert order from being quadratic.
    indexed: BTreeMap<u32, (String, AvroValue)>,
    named: Vec<(String, AvroValue)>,
    /// Built only for large maps, where a linear key search would be quadratic.
    named_index: Option<HashTable<usize>>,
}

const INDEX_THRESHOLD: usize = 16;

impl PartialEq for MapData {
    fn eq(&self, other: &Self) -> bool {
        self.indexed == other.indexed && self.named == other.named
    }
}

impl MapData {
    fn from_canonical_string_map(raw: &[u8]) -> Self {
        let mut tap = super::decode::Tap::new(raw);
        let n = tap.read_long() as usize;
        let mut named = Vec::with_capacity(n);
        for _ in 0..n {
            let key = tap.read_string().unwrap_or_default();
            let value = tap.read_string().unwrap_or_default();
            named.push((key, AvroValue::String(value)));
        }
        let mut data = Self {
            indexed: BTreeMap::new(),
            named,
            named_index: None,
        };
        if data.named.len() > INDEX_THRESHOLD {
            data.build_index();
        }
        data
    }

    fn assign(&mut self, key: String, value: AvroValue) {
        if key == "__proto__" {
            // Assignment sets the prototype instead of adding an own key.
            return;
        }
        self.define(key, value);
    }

    /// Unlike `assign`, this keeps a `__proto__` key, as object spread and `Object.fromEntries` do.
    fn define(&mut self, key: String, value: AvroValue) {
        if let Some(n) = is_array_index(&key) {
            match self.indexed.entry(n) {
                Entry::Occupied(mut slot) => slot.get_mut().1 = value,
                Entry::Vacant(slot) => {
                    slot.insert((key, value));
                }
            }
            return;
        }
        if let Some(i) = self.named_position(&key) {
            self.named[i].1 = value;
            return;
        }
        if let Some(index) = &mut self.named_index {
            let named = &self.named;
            index.insert_unique(hash_str(&key), named.len(), |&j| hash_str(&named[j].0));
        }
        self.named.push((key, value));
        if self.named_index.is_none() && self.named.len() > INDEX_THRESHOLD {
            self.build_index();
        }
    }

    fn named_position(&self, key: &str) -> Option<usize> {
        match &self.named_index {
            Some(index) => index
                .find(hash_str(key), |&i| self.named[i].0 == key)
                .copied(),
            None => self.named.iter().position(|(k, _)| k == key),
        }
    }

    fn build_index(&mut self) {
        let mut index = HashTable::with_capacity(self.named.len());
        for (i, (k, _)) in self.named.iter().enumerate() {
            index.insert_unique(hash_str(k), i, |&j| hash_str(&self.named[j].0));
        }
        self.named_index = Some(index);
    }

    fn get(&self, key: &str) -> Option<&AvroValue> {
        if let Some(n) = is_array_index(key) {
            return self.indexed.get(&n).map(|(_, v)| v);
        }
        self.named_position(key).map(|i| &self.named[i].1)
    }

    fn remove(&mut self, key: &str) -> Option<AvroValue> {
        if let Some(n) = is_array_index(key) {
            return self.indexed.remove(&n).map(|(_, v)| v);
        }
        let i = self.named_position(key)?;
        let (_, value) = self.named.remove(i);
        if self.named_index.is_some() {
            self.build_index();
        }
        Some(value)
    }

    fn len(&self) -> usize {
        self.indexed.len() + self.named.len()
    }

    fn iter(&self) -> impl Iterator<Item = (&str, &AvroValue)> + '_ {
        self.indexed
            .values()
            .map(|(k, v)| (k.as_str(), v))
            .chain(self.named.iter().map(|(k, v)| (k.as_str(), v)))
    }

    fn into_entries(self) -> impl Iterator<Item = (String, AvroValue)> {
        self.indexed.into_values().chain(self.named)
    }

    fn values_mut(&mut self) -> impl Iterator<Item = &mut AvroValue> + '_ {
        self.indexed
            .values_mut()
            .map(|(_, v)| v)
            .chain(self.named.iter_mut().map(|(_, v)| v))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assignment_semantics_match_a_plain_object() {
        let mut m = AvroMap::new();
        for (k, v) in [
            ("b", "1"),
            ("1", "2"),
            ("__proto__", "3"),
            ("dup", "x"),
            ("dup", "y"),
            ("0", "z"),
            ("4294967295", "big"),
            ("01", "lead"),
        ] {
            m.assign(k.to_string(), AvroValue::String(v.to_string()));
        }
        let entries: Vec<_> = m.iter_strings().collect();
        assert_eq!(
            entries,
            [
                ("0", "z"),
                ("1", "2"),
                ("b", "1"),
                ("dup", "y"),
                ("4294967295", "big"),
                ("01", "lead")
            ]
        );
    }
}
