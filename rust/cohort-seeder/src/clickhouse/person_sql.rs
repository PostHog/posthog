//! ClickHouse person-scan SQL: the byte-frozen renderers for the boundary and range scans over the
//! `person` table. Depends on `domain`; never on `store`.
//!
//! Both queries read the ReplacingMergeTree's latest row per person (`GROUP BY id` + `argMax(…,
//! version)`) with `team_id` equality-fixed. Range predicates are defined in ClickHouse's UUID
//! order. The horizon appears twice on purpose: the `id IN (…)` prefilter keeps the `_timestamp`
//! minmax skip index usable (a bare `HAVING` would decompress every historical version of every
//! person), while the `HAVING` clause states the update-recency semantics against the group —
//! `argMax` still sees all versions of the surviving ids. That prefilter is the one unbounded
//! structure here: the boundary query's set spans a whole team, so the client caps it with
//! `max_bytes_in_set`. `optimize_aggregation_in_order = 1` keeps the streaming aggregation
//! bounded; the client's external-group-by spill guard backstops a silent optimizer fallback. Only
//! the boundary query orders its output — the range scan's fold is order-independent, and an
//! unneeded `ORDER BY` would materialize the whole chunk result.

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
        "SELECT toString(id) AS id\nFROM person\nWHERE team_id = {team} AND id IN (\n    SELECT id FROM person\n    WHERE team_id = {team} AND _timestamp >= fromUnixTimestamp64Milli({since})\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli({since})\nORDER BY id\nSETTINGS optimize_aggregation_in_order = 1",
        team = team_id.0,
        since = scan_since.as_i64(),
    )
}

pub fn person_scan_sql(spec: &PersonScanSpec) -> String {
    // `lo` is always rendered — band 0 carries the nil UUID, a tautology under any byte ordering —
    // so the predicate shape is uniform across bands. The prefilter carries the same range so the
    // primary key prunes it too.
    let hi_predicate = spec
        .range
        .hi()
        .map(|hi| format!(" AND id < toUUID('{hi}')"))
        .unwrap_or_default();
    format!(
        "SELECT toString(id) AS id, argMax(properties, version) AS properties\nFROM person\nWHERE team_id = {team} AND id >= toUUID('{lo}'){hi} AND id IN (\n    SELECT id FROM person\n    WHERE team_id = {team} AND id >= toUUID('{lo}'){hi}\n      AND _timestamp >= fromUnixTimestamp64Milli({since})\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli({since})\nSETTINGS optimize_aggregation_in_order = 1",
        team = spec.team_id.0,
        lo = spec.range.lo(),
        hi = hi_predicate,
        since = spec.scan_since_ms,
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
            "SELECT toString(id) AS id\nFROM person\nWHERE team_id = 2 AND id IN (\n    SELECT id FROM person\n    WHERE team_id = 2 AND _timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nORDER BY id\nSETTINGS optimize_aggregation_in_order = 1"
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
            "SELECT toString(id) AS id, argMax(properties, version) AS properties\nFROM person\nWHERE team_id = 2 AND id >= toUUID('00000000-0000-0000-0000-000000000000') AND id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND id IN (\n    SELECT id FROM person\n    WHERE team_id = 2 AND id >= toUUID('00000000-0000-0000-0000-000000000000') AND id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee')\n      AND _timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Interior band: both bounds present.
        assert_eq!(
            person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(boundary_a, Some(boundary_b)),
            )),
            "SELECT toString(id) AS id, argMax(properties, version) AS properties\nFROM person\nWHERE team_id = 2 AND id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND id < toUUID('7f000000-0000-0000-0000-000000000001') AND id IN (\n    SELECT id FROM person\n    WHERE team_id = 2 AND id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND id < toUUID('7f000000-0000-0000-0000-000000000001')\n      AND _timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Last band: unbounded high.
        assert_eq!(
            person_scan_sql(&PersonScanSpec::new(
                TeamId(2),
                SINCE,
                range(boundary_b, None)
            )),
            "SELECT toString(id) AS id, argMax(properties, version) AS properties\nFROM person\nWHERE team_id = 2 AND id >= toUUID('7f000000-0000-0000-0000-000000000001') AND id IN (\n    SELECT id FROM person\n    WHERE team_id = 2 AND id >= toUUID('7f000000-0000-0000-0000-000000000001')\n      AND _timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY id\nHAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );
    }
}
