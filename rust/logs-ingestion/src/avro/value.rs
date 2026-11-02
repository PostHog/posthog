//! Decoded Avro values, shaped like the JavaScript values avsc returns.

use std::sync::Arc;

use crate::js::is_array_index;

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
    /// Fields in schema order. Names are shared with the schema.
    Record(Vec<(Arc<str>, AvroValue)>),
    Enum(String),
    Fixed(Vec<u8>),
    Array(Vec<AvroValue>),
    Map(AvroMap),
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

/// An Avro map as the plain JavaScript object avsc builds with `obj[key] = value`:
/// array-index keys first in numeric order, other keys in insertion order, a repeated key keeps
/// its first position and takes the last value, and a `__proto__` key is not an own property.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct AvroMap {
    indexed: Vec<(u32, String, AvroValue)>,
    named: Vec<(String, AvroValue)>,
}

impl AvroMap {
    pub fn new() -> Self {
        Self::default()
    }

    /// `obj[key] = value` on a plain object.
    pub fn assign(&mut self, key: String, value: AvroValue) {
        if key == "__proto__" {
            // Assignment sets the prototype instead of adding an own key.
            return;
        }
        self.define(key, value);
    }

    /// Defines an own property, as object spread and `Object.fromEntries` do. Unlike `assign`,
    /// this keeps a `__proto__` key.
    pub fn define(&mut self, key: String, value: AvroValue) {
        if let Some(n) = is_array_index(&key) {
            match self.indexed.binary_search_by_key(&n, |(k, _, _)| *k) {
                Ok(i) => self.indexed[i].2 = value,
                Err(i) => self.indexed.insert(i, (n, key, value)),
            }
            return;
        }
        if let Some(entry) = self.named.iter_mut().find(|(k, _)| *k == key) {
            entry.1 = value;
            return;
        }
        self.named.push((key, value));
    }

    pub fn get(&self, key: &str) -> Option<&AvroValue> {
        if let Some(n) = is_array_index(key) {
            return self
                .indexed
                .binary_search_by_key(&n, |(k, _, _)| *k)
                .ok()
                .map(|i| &self.indexed[i].2);
        }
        self.named.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    pub fn remove(&mut self, key: &str) -> Option<AvroValue> {
        if let Some(n) = is_array_index(key) {
            let i = self.indexed.binary_search_by_key(&n, |(k, _, _)| *k).ok()?;
            return Some(self.indexed.remove(i).2);
        }
        let i = self.named.iter().position(|(k, _)| k == key)?;
        Some(self.named.remove(i).1)
    }

    pub fn len(&self) -> usize {
        self.indexed.len() + self.named.len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Entries in own-property order.
    pub fn iter(&self) -> impl Iterator<Item = (&str, &AvroValue)> + '_ {
        self.indexed
            .iter()
            .map(|(_, k, v)| (k.as_str(), v))
            .chain(self.named.iter().map(|(k, v)| (k.as_str(), v)))
    }

    /// String values, which is what the log schemas' maps hold.
    pub fn iter_strings(&self) -> impl Iterator<Item = (&str, &str)> + '_ {
        self.iter().filter_map(|(k, v)| v.as_str().map(|s| (k, s)))
    }

    pub fn from_strings<'a>(entries: impl IntoIterator<Item = (&'a str, &'a str)>) -> Self {
        let mut map = Self::new();
        for (k, v) in entries {
            map.assign(k.to_string(), AvroValue::String(v.to_string()));
        }
        map
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
