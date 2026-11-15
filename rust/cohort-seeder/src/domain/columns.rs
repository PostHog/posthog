//! Domain layer: materialized columns verified to hold a `properties` key's trim-quotes value.

use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ColumnName(String);

impl ColumnName {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for ColumnName {
    fn from(name: String) -> Self {
        Self(name)
    }
}

impl From<&str> for ColumnName {
    fn from(name: &str) -> Self {
        Self(name.to_owned())
    }
}

/// Property key to verified column name.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MaterializedColumns(HashMap<String, ColumnName>);

impl MaterializedColumns {
    pub fn column_for(&self, key: &str) -> Option<&ColumnName> {
        self.0.get(key)
    }

    pub fn covers<'k>(&self, keys: impl IntoIterator<Item = &'k str>) -> bool {
        keys.into_iter().all(|key| self.0.contains_key(key))
    }
}

/// The first column given for a key wins.
impl<K: Into<String>, C: Into<ColumnName>> FromIterator<(K, C)> for MaterializedColumns {
    fn from_iter<I: IntoIterator<Item = (K, C)>>(pairs: I) -> Self {
        let mut columns = HashMap::new();
        for (key, column) in pairs {
            columns.entry(key.into()).or_insert_with(|| column.into());
        }
        Self(columns)
    }
}
