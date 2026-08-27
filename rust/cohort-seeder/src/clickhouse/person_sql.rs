//! ClickHouse person-scan SQL: the byte-frozen renderers for the boundary and range scans over the
//! `person` table. Depends on `domain`; never on `store`.
//!
//! Both queries read the ReplacingMergeTree's latest row per person (`GROUP BY p.id` + `argMax(…,
//! version)`) with `team_id` equality-fixed. Range predicates are defined in ClickHouse's UUID
//! order. Every column reference is table-qualified because the output alias is itself named `id`:
//! ClickHouse binds a bare `id` in `WHERE`, `GROUP BY`, or `ORDER BY` to that alias rather than to
//! the column, so an unqualified `id >= toUUID(…)` compares `String` against `UUID` (no supertype,
//! so the query cannot execute) and an unqualified `ORDER BY id` streams boundaries in text order
//! while the range predicates read them back in UUID order. The horizon appears twice on purpose:
//! the `p.id IN (…)` prefilter keeps the `_timestamp` minmax skip index usable (a bare `HAVING`
//! would decompress every historical version of every person), while the `HAVING` clause states the
//! update-recency semantics against the group — `argMax` still sees all versions of the surviving
//! ids. That prefilter is the one unbounded structure here: the boundary query's set spans a whole
//! team, so the client caps it with `max_bytes_in_set`. `optimize_aggregation_in_order = 1` keeps
//! the streaming aggregation bounded; the client's external-group-by spill guard backstops a silent
//! optimizer fallback. Only the boundary query orders its output — the range scan's fold is
//! order-independent, and an unneeded `ORDER BY` would materialize the whole chunk result.

use cohort_core::filters::TeamId;

use crate::domain::{PersonRange, UtcMillis};

/// The rendered person scan's inputs, constructed only from already-proven types.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonScanSpec {
    team_id: TeamId,
    scan_since_ms: i64,
    range: PersonRange,
}

impl PersonScanSpec {
    pub fn new(team_id: TeamId, scan_since: UtcMillis, range: PersonRange) -> Self {
        Self {
            team_id,
            scan_since_ms: scan_since.as_i64(),
            range,
        }
    }
}

pub fn person_boundaries_sql(team_id: TeamId, scan_since: UtcMillis) -> String {
    format!(
        "SELECT toString(p.id) AS id\nFROM person AS p\nWHERE p.team_id = {team} AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = {team} AND recent._timestamp >= fromUnixTimestamp64Milli({since})\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli({since})\nORDER BY p.id\nSETTINGS optimize_aggregation_in_order = 1",
        team = team_id.0,
        since = scan_since.as_i64(),
    )
}

pub fn person_scan_sql(spec: &PersonScanSpec) -> String {
    format!(
        "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = {team} AND {outer_range} AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = {team} AND {prefilter_range}\n      AND recent._timestamp >= fromUnixTimestamp64Milli({since})\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli({since})\nSETTINGS optimize_aggregation_in_order = 1",
        team = spec.team_id.0,
        outer_range = range_predicate("p", spec.range),
        // The prefilter carries the same range, against its own table reference, so the primary key
        // prunes it too.
        prefilter_range = range_predicate("recent", spec.range),
        since = spec.scan_since_ms,
    )
}

/// One table reference's range predicate. `lo` is always rendered, because band 0 carries the nil
/// UUID and `id >= nil` is a tautology under any byte ordering, so the predicate shape stays
/// uniform across bands.
fn range_predicate(table: &str, range: PersonRange) -> String {
    let hi_predicate = range
        .hi()
        .map(|hi| format!(" AND {table}.id < toUUID('{hi}')"))
        .unwrap_or_default();
    format!(
        "{table}.id >= toUUID('{lo}'){hi}",
        lo = range.lo(),
        hi = hi_predicate,
    )
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    const SINCE: UtcMillis = UtcMillis::new(1_780_000_000_000);

    fn range(lo: Uuid, hi: Option<Uuid>) -> PersonRange {
        PersonRange::new(lo, hi).unwrap()
    }

    #[test]
    fn boundaries_sql_is_byte_frozen() {
        assert_eq!(
            person_boundaries_sql(TeamId(2), SINCE),
            "SELECT toString(p.id) AS id\nFROM person AS p\nWHERE p.team_id = 2 AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nORDER BY p.id\nSETTINGS optimize_aggregation_in_order = 1"
        );
    }

    #[test]
    fn scan_sql_is_byte_frozen_for_every_range_shape() {
        let boundary_a = Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap();
        let boundary_b = Uuid::parse_str("7f000000-0000-0000-0000-000000000001").unwrap();

        // Band 0: nil lo (tautology) with a bounded hi.
        assert_eq!(
            person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(Uuid::nil(), Some(boundary_a)),
            )),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('00000000-0000-0000-0000-000000000000') AND p.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('00000000-0000-0000-0000-000000000000') AND recent.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Interior band: both bounds present.
        assert_eq!(
            person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(boundary_a, Some(boundary_b)),
            )),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND p.id < toUUID('7f000000-0000-0000-0000-000000000001') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND recent.id < toUUID('7f000000-0000-0000-0000-000000000001')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Last band: unbounded high.
        assert_eq!(
            person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(boundary_b, None)
            )),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('7f000000-0000-0000-0000-000000000001') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('7f000000-0000-0000-0000-000000000001')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );
    }

    /// The byte-frozen tests above compare each query against a copy of itself, so they accept any
    /// SQL the renderer emits, including SQL no ClickHouse can execute. This one states the property
    /// that made the shipped query unexecutable: an unqualified column reference binds to the
    /// `AS id` output alias, turning `id >= toUUID(…)` into `String >= UUID` (no supertype) and
    /// `ORDER BY id` into a text-ordered boundary stream the UUID-ordered range predicates cannot
    /// tile.
    #[test]
    fn no_column_reference_can_resolve_to_the_output_alias() {
        let boundary = Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap();
        let mut rendered = vec![person_boundaries_sql(TeamId(2), SINCE)];
        // Both predicate shapes: a bounded range and the final unbounded one.
        for hi in [Some(boundary), None] {
            rendered.push(person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(Uuid::nil(), hi),
            )));
        }

        for sql in &rendered {
            assert_eq!(
                unqualified_column_references(sql),
                Vec::<&str>::new(),
                "unqualified column reference in:\n{sql}"
            );
        }
    }

    const PERSON_COLUMNS: [&str; 6] = [
        "id",
        "team_id",
        "properties",
        "version",
        "is_deleted",
        "_timestamp",
    ];

    /// Every `person` column name in `sql` that is neither `<table>.`-prefixed nor the `AS <name>`
    /// alias being defined, so it resolves against the query's scope instead of a named table.
    fn unqualified_column_references(sql: &str) -> Vec<&str> {
        let mut identifiers = Vec::new();
        let mut start = None;
        for (index, character) in sql.char_indices() {
            match (start, character.is_ascii_alphanumeric() || character == '_') {
                (None, true) => start = Some(index),
                (Some(begin), false) => {
                    identifiers.push((begin, index));
                    start = None;
                }
                _ => {}
            }
        }
        if let Some(begin) = start {
            identifiers.push((begin, sql.len()));
        }

        identifiers
            .into_iter()
            .filter(|(begin, end)| {
                PERSON_COLUMNS.contains(&&sql[*begin..*end])
                    && !sql[..*begin].ends_with('.')
                    && !sql[..*begin].ends_with("AS ")
            })
            .map(|(begin, end)| &sql[begin..end])
            .collect()
    }
}
