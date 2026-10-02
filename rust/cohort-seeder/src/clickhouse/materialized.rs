//! Finds the materialized columns a behavioral scan's row filter can read instead of the
//! `properties` blob.
//!
//! A column qualifies only when its stored default expression on the data table is exactly the
//! trim-quotes extraction the filter would otherwise evaluate. A typed `JSONExtract` column reads
//! different values for the same row, such as an empty value for a boolean that HogVM equality can
//! match. The column must also exist on the distributed `events` table the scan reads.

use std::collections::{BTreeSet, HashMap};

use clickhouse::Row;
use serde::Deserialize;

use super::client::ClickHouseClient;
use super::sql::clickhouse_string_literal;

/// Only the data table's columns carry the default expressions.
const EVENTS_DATA_TABLE: &str = "sharded_events";

/// Property key to verified column name.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MaterializedColumns(HashMap<String, String>);

impl MaterializedColumns {
    pub fn column_for(&self, key: &str) -> Option<&str> {
        self.0.get(key).map(String::as_str)
    }

    pub async fn lookup(
        client: &ClickHouseClient,
        keys: &BTreeSet<&str>,
    ) -> Result<Self, clickhouse::error::Error> {
        if keys.is_empty() {
            return Ok(Self::default());
        }
        let expected: HashMap<String, &str> = keys
            .iter()
            .map(|key| (trim_quotes_extraction(key), *key))
            .collect();
        let rows = client
            .query(&lookup_sql(expected.keys()))
            .fetch_all::<ColumnRow>()
            .await?;
        let mut columns = HashMap::new();
        for row in rows {
            // Rows are sorted by name, so every chunk picks the same column for a key.
            if let Some(key) = expected.get(&row.expression) {
                columns
                    .entry((*key).to_owned())
                    .or_insert_with(|| row.name.clone());
            }
        }
        Ok(Self(columns))
    }
}

impl FromIterator<(String, String)> for MaterializedColumns {
    fn from_iter<I: IntoIterator<Item = (String, String)>>(pairs: I) -> Self {
        Self(pairs.into_iter().collect())
    }
}

#[derive(Debug, Row, Deserialize)]
struct ColumnRow {
    name: String,
    expression: String,
}

/// The materializer's default expression for a non-nullable property column, as ClickHouse stores
/// it. Only `'` and `\` are escaped, so a key holding another character ClickHouse escapes finds no
/// column and the filter reads the blob.
fn trim_quotes_extraction(key: &str) -> String {
    let escaped = key.replace('\\', "\\\\").replace('\'', "\\'");
    format!("replaceRegexpAll(JSONExtractRaw(properties, '{escaped}'), '^\"|\"$', '')")
}

fn lookup_sql<'a>(expressions: impl Iterator<Item = &'a String>) -> String {
    let mut expressions = expressions
        .map(|expression| clickhouse_string_literal(expression))
        .collect::<Vec<_>>();
    expressions.sort();
    format!(
        "SELECT name, default_expression AS expression\nFROM system.columns\nWHERE database = currentDatabase() AND table = '{EVENTS_DATA_TABLE}'\n  AND type = 'String' AND default_kind IN ('DEFAULT', 'MATERIALIZED')\n  AND default_expression IN ({})\n  AND name IN (SELECT name FROM system.columns WHERE database = currentDatabase() AND table = 'events' AND type = 'String')\nORDER BY name",
        expressions.join(", "),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_expected_expression_is_the_stored_materializer_text() {
        assert_eq!(
            trim_quotes_extraction("$feature_flag"),
            r#"replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^"|"$', '')"#
        );
        assert_eq!(
            trim_quotes_extraction(r"it's\here"),
            r#"replaceRegexpAll(JSONExtractRaw(properties, 'it\'s\\here'), '^"|"$', '')"#
        );
    }
}
