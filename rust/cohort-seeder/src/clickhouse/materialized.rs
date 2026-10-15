//! Finds the materialized columns a behavioral scan's row filter and projection can read instead of
//! the `properties` blob.
//!
//! A column qualifies only when its stored default expression on the data table is exactly the
//! trim-quotes extraction the filter would otherwise evaluate. A typed `JSONExtract` column reads
//! different values for the same row, such as an empty value for a boolean that HogVM equality can
//! match. The column must also exist on the distributed `events` table the scan reads.

use std::collections::{BTreeSet, HashMap};
use std::iter;

use clickhouse::Row;
use serde::Deserialize;

use super::client::ClickHouseClient;
use super::sql::{clickhouse_string_literal, fits_client_get};
use crate::domain::MaterializedColumns;

/// Only the data table's columns carry the default expressions.
const EVENTS_DATA_TABLE: &str = "sharded_events";

impl MaterializedColumns {
    pub async fn lookup(
        client: &ClickHouseClient,
        keys: &BTreeSet<&str>,
    ) -> Result<Self, clickhouse::error::Error> {
        let key_by_expression: HashMap<String, &str> = keys
            .iter()
            .map(|key| (trim_quotes_extraction(key), *key))
            .collect();
        let mut expressions = key_by_expression
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>();
        expressions.sort_unstable();
        let mut rows = Vec::new();
        for batch in lookup_batches(&expressions) {
            rows.extend(
                client
                    .query(&lookup_sql(&batch))
                    .fetch_all::<ColumnRow>()
                    .await?,
            );
        }
        // Rows are sorted by name, so every chunk picks the same column for a key.
        Ok(rows
            .into_iter()
            .filter_map(|row| Some((*key_by_expression.get(&row.expression)?, row.name)))
            .collect())
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

/// Each batch fits a GET, because the `cohort_seeder` profile refuses the POST form.
fn lookup_batches<'a>(expressions: &'a [&'a str]) -> impl Iterator<Item = Vec<&'a str>> + 'a {
    let mut pending = expressions.iter().copied().peekable();
    iter::from_fn(move || {
        let mut batch = vec![pending.next()?];
        while let Some(expression) = pending
            .next_if(|next| fits_client_get(&lookup_sql(&[batch.as_slice(), &[*next]].concat())))
        {
            batch.push(expression);
        }
        Some(batch)
    })
}

fn lookup_sql(expressions: &[&str]) -> String {
    let mut literals = expressions
        .iter()
        .map(|expression| clickhouse_string_literal(expression))
        .collect::<Vec<_>>();
    literals.sort();
    format!(
        "SELECT name, default_expression AS expression\nFROM system.columns\nWHERE database = currentDatabase() AND table = '{EVENTS_DATA_TABLE}'\n  AND type = 'String' AND default_kind IN ('DEFAULT', 'MATERIALIZED')\n  AND default_expression IN ({})\n  AND name IN (SELECT name FROM system.columns WHERE database = currentDatabase() AND table = 'events' AND type = 'String')\nORDER BY name",
        literals.join(", "),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_long_lookup_is_split_into_queries_that_each_fit_a_get() {
        let expressions = (0..300)
            .map(|index| trim_quotes_extraction(&format!("$feature/a-long-flag-name-{index:03}")))
            .collect::<Vec<_>>();
        let mut sorted = expressions.iter().map(String::as_str).collect::<Vec<_>>();
        sorted.sort_unstable();

        let batches = lookup_batches(&sorted).collect::<Vec<_>>();
        assert!(
            batches.len() > 1,
            "the keys fit one query, so nothing was split"
        );
        for batch in &batches {
            assert!(fits_client_get(&lookup_sql(batch)));
        }
        assert_eq!(batches.concat(), sorted);
    }

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
