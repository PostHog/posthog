//! Whether a trim-quotes materialized column decides a `properties` key like the blob.

use std::collections::BTreeMap;
use std::ops::BitAnd;
use std::str::FromStr;

use hogvm::Num;
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Exactness {
    Exact,
    Inexact,
}

impl Exactness {
    /// The column retypes JSON-looking strings and reads absent keys as `""`, so only a literal
    /// neither can equal is exact.
    pub fn of_literal(literal: &str) -> Self {
        let lowercase = literal.to_lowercase();
        let retyped = literal.is_empty()
            || Num::from_str(literal).is_ok()
            || serde_json::from_str::<Value>(literal).is_ok()
            || lowercase == "true"
            || lowercase == "false";
        if retyped {
            Self::Inexact
        } else {
            Self::Exact
        }
    }
}

impl BitAnd for Exactness {
    type Output = Self;

    fn bitand(self, other: Self) -> Self {
        match (self, other) {
            (Self::Exact, Self::Exact) => Self::Exact,
            (Self::Exact | Self::Inexact, Self::Inexact) | (Self::Inexact, Self::Exact) => {
                Self::Inexact
            }
        }
    }
}

/// Collecting keeps a key exact only while every read of it is.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ColumnExactness(BTreeMap<String, Exactness>);

impl ColumnExactness {
    pub fn get(&self, key: &str) -> Option<Exactness> {
        self.0.get(key).copied()
    }

    pub fn exact_keys(&self) -> impl Iterator<Item = &str> {
        self.0
            .iter()
            .filter(|(_, exactness)| **exactness == Exactness::Exact)
            .map(|(key, _)| key.as_str())
    }
}

impl<K: Into<String>> FromIterator<(K, Exactness)> for ColumnExactness {
    fn from_iter<I: IntoIterator<Item = (K, Exactness)>>(reads: I) -> Self {
        let mut by_key = BTreeMap::new();
        for (key, exactness) in reads {
            by_key
                .entry(key.into())
                .and_modify(|seen: &mut Exactness| *seen = *seen & exactness)
                .or_insert(exactness);
        }
        Self(by_key)
    }
}

impl FromIterator<ColumnExactness> for ColumnExactness {
    fn from_iter<I: IntoIterator<Item = ColumnExactness>>(maps: I) -> Self {
        maps.into_iter().flat_map(|map| map.0).collect()
    }
}
