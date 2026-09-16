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
//!
//! The range scan may also carry a key-presence filter, which drops a person whose latest blob is a
//! JSON object holding none of the keys the run's conditions read — a person the fold would prune
//! anyway, at the cost of transferring and decoding their whole property bag first. See
//! [`key_presence_predicate`] for why it admits every non-object blob.

use cohort_core::filters::TeamId;

use crate::clickhouse::sql::clickhouse_string_literal;
use crate::domain::{PersonRange, ProjectedKeys, UtcMillis};

/// The rendered ceiling one scan may reach, leaving about 2 KB of margin.
///
/// The `cohort_seeder` ClickHouse profile runs `readonly=2`, under which a query over 8192 bytes is
/// POSTed as `readonly=1` and fails with code 164. The profile lives in the infrastructure
/// repository, not here, so this constant cannot be derived — re-check it against the profile
/// rather than against this comment. Conservative in the safe direction: the `?` → `??` escaping in
/// [`clickhouse_string_literal`] is undone by the client's template parser, so the query that
/// reaches the server is never longer than the text measured here.
const MAX_RENDERED_SCAN_BYTES: usize = 6144;

/// What became of a run's key filter on one chunk, as a bounded metric label.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScanFilterOutcome {
    /// The scan drops object rows carrying none of the run's keys.
    KeyPresence,
    /// The run asked for no filter: the healer policy, or a condition the VM has to decide.
    None,
    /// The rendered filter would have pushed the query past the readonly ceiling.
    TooLong,
}

impl ScanFilterOutcome {
    pub const ALL: [Self; 3] = [Self::KeyPresence, Self::None, Self::TooLong];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::KeyPresence => "key_presence",
            Self::None => "none",
            Self::TooLong => "too_long",
        }
    }
}

/// The rendered person scan's inputs, constructed only from already-proven types.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonScanSpec {
    team_id: TeamId,
    scan_since_ms: i64,
    range: PersonRange,
    key_filter: Option<ProjectedKeys>,
    filter_outcome: ScanFilterOutcome,
}

impl PersonScanSpec {
    /// `key_filter` names the top-level `properties` keys a person must carry to be worth scanning;
    /// `None` scans the whole range.
    ///
    /// The size guard lives here rather than in the renderer, which renders once to measure and
    /// drops the filter if it does not fit. [`person_scan_sql`] then stays a pure rendering of a
    /// spec already proven to fit, at the cost of one extra render per chunk.
    pub fn new(
        team_id: TeamId,
        scan_since: UtcMillis,
        range: PersonRange,
        key_filter: Option<ProjectedKeys>,
    ) -> Self {
        let filter_outcome = match &key_filter {
            Some(_) => ScanFilterOutcome::KeyPresence,
            None => ScanFilterOutcome::None,
        };
        let spec = Self {
            team_id,
            scan_since_ms: scan_since.as_i64(),
            range,
            key_filter,
            filter_outcome,
        };
        if person_scan_sql(&spec).len() <= MAX_RENDERED_SCAN_BYTES {
            return spec;
        }
        Self {
            key_filter: None,
            filter_outcome: ScanFilterOutcome::TooLong,
            ..spec
        }
    }

    pub const fn filter_outcome(&self) -> ScanFilterOutcome {
        self.filter_outcome
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
        "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = {team} AND {outer_range} AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = {team} AND {prefilter_range}\n      AND recent._timestamp >= fromUnixTimestamp64Milli({since})\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli({since}){key_filter}\nSETTINGS optimize_aggregation_in_order = 1",
        team = spec.team_id.0,
        outer_range = range_predicate("p", spec.range),
        // The prefilter carries the same range, against its own table reference, so the primary key
        // prunes it too.
        prefilter_range = range_predicate("recent", spec.range),
        since = spec.scan_since_ms,
        key_filter = spec
            .key_filter
            .as_ref()
            .map(key_presence_predicate)
            .unwrap_or_default(),
    )
}

/// Drop object blobs carrying none of `keys`.
///
/// Costs two server-side JSON parses per surviving group, `JSONType` and `JSONExtractKeys`, against
/// the scan's `max_execution_time` budget. Cheap next to the transfer and per-row evaluation it
/// removes, but it is new ClickHouse work and belongs in the rollout measurement.
///
/// Every *non*-object blob is admitted, deliberately. `JSONType` reports `Null` for a missing,
/// empty, literal-`null` or malformed blob — and also for a well-formed document holding a number
/// ClickHouse cannot represent, which `serde_json` parses and whose keys the VM then reads. Dropping
/// the `Null` class would therefore drop genuine members, so the filter admits a strict superset of
/// what the seeder can emit and exactness stays with the VM.
///
/// The aggregate is spelled out twice rather than referencing the `properties` output alias: a bare
/// column name in `HAVING` binds to that alias, which is the mistake
/// `no_column_reference_can_resolve_to_the_output_alias` exists to catch. ClickHouse computes one
/// `argMax` state for the repeated expression.
fn key_presence_predicate(keys: &ProjectedKeys) -> String {
    let key_list = keys
        .iter()
        .map(clickhouse_string_literal)
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "\n   AND (JSONType(argMax(p.properties, p.version)) != 'Object' OR hasAny(JSONExtractKeys(argMax(p.properties, p.version)), [{key_list}]))"
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

    fn scan_spec(range: PersonRange, key_filter: Option<ProjectedKeys>) -> PersonScanSpec {
        PersonScanSpec::new(TeamId(2), SINCE, range, key_filter)
    }

    fn keys(names: &[&str]) -> ProjectedKeys {
        ProjectedKeys::new(names.iter().map(|name| (*name).to_owned()).collect())
            .expect("the test key sets are non-empty")
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
            person_scan_sql(&scan_spec(range(Uuid::nil(), Some(boundary_a)), None)),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('00000000-0000-0000-0000-000000000000') AND p.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('00000000-0000-0000-0000-000000000000') AND recent.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Interior band: both bounds present.
        assert_eq!(
            person_scan_sql(&scan_spec(range(boundary_a, Some(boundary_b)), None)),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND p.id < toUUID('7f000000-0000-0000-0000-000000000001') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND recent.id < toUUID('7f000000-0000-0000-0000-000000000001')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );

        // Last band: unbounded high.
        assert_eq!(
            person_scan_sql(&scan_spec(range(boundary_b, None), None)),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('7f000000-0000-0000-0000-000000000001') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('7f000000-0000-0000-0000-000000000001')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\nSETTINGS optimize_aggregation_in_order = 1"
        );
    }

    /// The filter is appended to the `HAVING` clause, before `SETTINGS`, and spells the aggregate
    /// out twice rather than naming the `properties` output alias. Frozen byte for byte because the
    /// predicate's exact text is what `tests/ch_person_key_filter.rs` measures against a real server.
    #[test]
    fn scan_sql_is_byte_frozen_with_the_key_presence_filter() {
        let boundary = Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap();
        assert_eq!(
            person_scan_sql(&scan_spec(
                range(Uuid::nil(), Some(boundary)),
                Some(keys(&["email", "plan"])),
            )),
            "SELECT toString(p.id) AS id, argMax(p.properties, p.version) AS properties\nFROM person AS p\nWHERE p.team_id = 2 AND p.id >= toUUID('00000000-0000-0000-0000-000000000000') AND p.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee') AND p.id IN (\n    SELECT recent.id FROM person AS recent\n    WHERE recent.team_id = 2 AND recent.id >= toUUID('00000000-0000-0000-0000-000000000000') AND recent.id < toUUID('01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee')\n      AND recent._timestamp >= fromUnixTimestamp64Milli(1780000000000)\n)\nGROUP BY p.id\nHAVING argMax(p.is_deleted, p.version) = 0 AND max(p._timestamp) >= fromUnixTimestamp64Milli(1780000000000)\n   AND (JSONType(argMax(p.properties, p.version)) != 'Object' OR hasAny(JSONExtractKeys(argMax(p.properties, p.version)), ['email', 'plan']))\nSETTINGS optimize_aggregation_in_order = 1"
        );
    }

    /// A key is customer text. The single quote is the one escape whose failure would be an
    /// injection rather than a wrong answer, and a bare `?` is swallowed by the client's own
    /// template parser before the SQL is sent.
    #[test]
    fn key_literals_are_escaped_for_both_the_server_and_the_client_template() {
        let rendered = person_scan_sql(&scan_spec(
            range(Uuid::nil(), None),
            Some(keys(&["quote' OR 1 = 1 --", "back\\slash", "why?fields"])),
        ));
        let predicate = rendered
            .split_once("OR hasAny(")
            .expect("the filter renders")
            .1;
        assert!(
            predicate.starts_with(
                "JSONExtractKeys(argMax(p.properties, p.version)), ['back\\\\slash', 'quote\\' OR 1 = 1 --', 'why??fields'])"
            ),
            "key literals escaped as: {predicate}"
        );
    }

    /// The `cohort_seeder` profile runs `readonly=2`, which refuses a query over 8192 bytes: a key
    /// list long enough to cross that must cost the filter, not every chunk of the run.
    #[test]
    fn an_oversized_key_list_drops_the_filter_rather_than_the_query() {
        let short = scan_spec(range(Uuid::nil(), None), Some(keys(&["email"])));
        assert_eq!(short.filter_outcome(), ScanFilterOutcome::KeyPresence);
        assert!(person_scan_sql(&short).contains("hasAny("));

        let long: Vec<String> = (0..500)
            .map(|index| format!("property_number_{index}"))
            .collect();
        let long = ProjectedKeys::new(long.into_iter().collect()).unwrap();
        let spec = scan_spec(range(Uuid::nil(), None), Some(long));
        assert_eq!(spec.filter_outcome(), ScanFilterOutcome::TooLong);
        let rendered = person_scan_sql(&spec);
        assert!(
            !rendered.contains("hasAny("),
            "the filter survived the guard"
        );
        assert!(rendered.len() <= MAX_RENDERED_SCAN_BYTES);

        assert_eq!(
            scan_spec(range(Uuid::nil(), None), None).filter_outcome(),
            ScanFilterOutcome::None
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
            for filter in [None, Some(keys(&["email", "plan"]))] {
                rendered.push(person_scan_sql(&scan_spec(range(Uuid::nil(), hi), filter)));
            }
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
