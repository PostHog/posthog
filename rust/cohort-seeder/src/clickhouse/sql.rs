//! ClickHouse scan planning: the `Vacuous`-vs-`Scan` parse and the byte-frozen SQL renderer. Depends
//! on `domain` (the proven range/band/event-name inputs) and `cohort-core`; never on `store`.

use std::num::NonZeroU32;

use cohort_core::filters::TeamId;

use crate::domain::{
    BandSpec, BlobSource, ChunkProjection, ColumnPlan, EventNameSet, ProjectedKeys, ScalarColumn,
    SeedDomain,
};

/// The rendered scan's inputs, proven complete: constructed only by [`plan_scan`] from already-proven
/// types, so [`scan_sql`] never re-validates. Fields stay private — the SQL text is the only output.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScanSpec {
    team_id: TeamId,
    day_start_ms: i64,
    day_end_ms: i64,
    s_chunk_ms: i64,
    event_names: Vec<String>,
    band: u32,
    num_bands: NonZeroU32,
}

/// Whether a chunk has anything to scan. `plan_scan` collapses the empty-domain and empty-event-name
/// cases into [`ScanPlan::Vacuous`], so the scanner treats "nothing to do" as a parse, not a check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ScanPlan {
    Vacuous,
    Scan(ScanSpec),
}

/// Parse a claimed chunk into a scan plan. Takes the resolved `EventNameSet` by reference (already
/// sorted and deduplicated), so no set is rebuilt. An empty domain or empty event set is vacuous.
pub fn plan_scan(
    team_id: TeamId,
    domain: &SeedDomain,
    event_names: &EventNameSet,
    band: BandSpec,
) -> ScanPlan {
    if domain.is_empty() || event_names.is_empty() {
        return ScanPlan::Vacuous;
    }
    let range = domain.utc_range();
    ScanPlan::Scan(ScanSpec {
        team_id,
        day_start_ms: range.start().as_i64(),
        day_end_ms: range.end().as_i64(),
        s_chunk_ms: domain.s_chunk().0,
        event_names: event_names.as_slice().to_vec(),
        band: band.band(),
        num_bands: band.num_bands(),
    })
}

/// Render one chunk's scan.
///
/// The projection is a separate parameter rather than a [`ScanSpec`] field: the spec is what
/// `plan_scan` proved about the chunk's range and event names, while the projection is derived from
/// the conditions active on it. Keeping them apart lets one spec render both forms, which is what
/// the shadow compare needs to scan the same rows twice.
///
/// The column list is the same eight columns in the same order whatever the projection, so the row
/// decoder's positional read never has to know which arm ran.
pub fn scan_sql(spec: &ScanSpec, projection: &ChunkProjection) -> String {
    let select_list = match projection {
        ChunkProjection::FullColumns => render_select_list(&ColumnPlan::full()),
        ChunkProjection::Projected(plan) => render_select_list(plan),
    };
    let event_names = spec
        .event_names
        .iter()
        .map(|name| clickhouse_string_literal(name))
        .collect::<Vec<_>>()
        .join(", ");
    let band_predicate = if spec.num_bands.get() > 1 {
        format!(
            "\n  AND cityHash64(toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)))\n      % {} = {}",
            spec.num_bands, spec.band
        )
    } else {
        String::new()
    };

    format!(
        "SELECT {}\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = {}\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = {}\n  AND e.timestamp >= fromUnixTimestamp64Milli({})\n  AND e.timestamp < fromUnixTimestamp64Milli({})\n  AND e.event IN ({})\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli({}){}",
        select_list,
        spec.team_id.0,
        spec.team_id.0,
        spec.day_start_ms,
        spec.day_end_ms,
        event_names,
        spec.s_chunk_ms,
        band_predicate,
    )
}

/// The eight-column select list. `event`, `timestamp`, `distinct_id`, and the override-resolved
/// `person_id` are always selected: the fold places the row in its day by timestamp, the accumulator
/// keys on the person, and the event name decides which conditions run.
fn render_select_list(plan: &ColumnPlan) -> String {
    format!(
        "{}, e.event, {}, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       {}, {}",
        match plan.uuid {
            ScalarColumn::Keep => "toString(e.uuid) AS uuid".to_string(),
            ScalarColumn::Empty => "'' AS uuid".to_string(),
        },
        render_blob("e.properties", "properties", &plan.properties),
        render_blob(
            "e.person_properties",
            "person_properties",
            &plan.person_properties
        ),
        match plan.elements_chain {
            ScalarColumn::Keep => "e.elements_chain".to_string(),
            ScalarColumn::Empty => "'' AS elements_chain".to_string(),
        },
    )
}

/// A JSON blob column, selected whole, replaced by an empty literal, or rebuilt from the keys the
/// chunk reads. An empty literal is what the row decoder lifts to "absent", which the globals
/// builder reads as `{}` without parsing anything.
///
/// Not parsing is also a behavior change, and it is the reason [`BlobSource::Empty`] is not just a
/// cheaper [`BlobSource::Keys`]. A row whose blob is malformed fails the globals build today and
/// is dropped as a skipped row. Once the column is an empty literal there is nothing to parse, so
/// the same row evaluates on its other globals. The live processor still parses the whole Kafka
/// payload and still drops it, so a seeded history counts events live evaluation never will. This
/// is the same class of over-count as the deep-nesting divergence pinned in
/// `tests/ch_rebuild_equivalence.rs`, and it is wider: it covers every malformed blob, not only
/// the ones past `serde_json`'s recursion limit. [`BlobSource::Keys`] does not share it, because
/// the rebuild passes a non-object through verbatim and the parse fails exactly as before.
fn render_blob(column: &str, alias: &str, source: &BlobSource) -> String {
    match source {
        BlobSource::Full => column.to_string(),
        BlobSource::Empty => format!("'' AS {alias}"),
        BlobSource::Keys(keys) => format!("{} AS {alias}", rebuild_expr(column, keys)),
    }
}

/// Rebuild a JSON object from its top-level entries, keeping only `keys` and their values.
///
/// Not byte-identical to the original: `JSONExtractKeysAndValuesRaw` re-serializes what it
/// extracts, recursively, so string escapes are decoded and re-escaped and float-variant numbers
/// re-print shortest-form (`1.0` to `1`, `1e3` to `1000`). Integer digits survive exactly. The
/// materialized `mat_*` columns cannot even promise that much, because they strip quotes, so a
/// string and a number become indistinguishable.
///
/// The float re-print is only safe once HogVM compares numbers numerically. Until then `Num`
/// equality is variant-exact, so `Float(100.0)` and `Integer(100)` are different values, and a
/// re-printed token flips any condition that compares against a whole number: `== 100` starts
/// matching a row it missed, and `!= 100` stops matching one it caught. So this rebuild must not
/// reach production before that change does. The `ch_rebuild_equivalence` corpus encodes the
/// post-change semantics, which is what its oracle blurs.
///
/// Anything that is not a JSON object passes through verbatim: malformed text, non-object roots,
/// and any document holding a number ClickHouse cannot represent. `JSONType` reports `Null` for
/// them all, and the untouched blob then reaches the same parse, or the same parse failure and
/// skipped-row metric, it reaches today.
pub fn rebuild_expr(column: &str, keys: &ProjectedKeys) -> String {
    let key_list = keys
        .iter()
        .map(clickhouse_string_literal)
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "if(JSONType({column}) != 'Object', {column}, concat('{{', arrayStringConcat(arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), arrayFilter(kv -> kv.1 IN ({key_list}), JSONExtractKeysAndValuesRaw({column}))), ','), '}}'))"
    )
}

fn clickhouse_string_literal(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('\'');
    for character in value.chars() {
        match character {
            '\\' => escaped.push_str("\\\\"),
            '\'' => escaped.push_str("\\'"),
            '`' => escaped.push_str("\\`"),
            // Client-side, not server-side: the `clickhouse` crate's template parser treats every
            // bare `?` as a bind placeholder — even inside string literals — and fails the query
            // with "unbound query argument". `??` collapses back to a literal `?` before the SQL
            // reaches the server.
            '?' => escaped.push_str("??"),
            '\0' => escaped.push_str("\\0"),
            '\u{0007}' => escaped.push_str("\\a"),
            '\u{0008}' => escaped.push_str("\\b"),
            '\t' => escaped.push_str("\\t"),
            '\n' => escaped.push_str("\\n"),
            '\u{000B}' => escaped.push_str("\\v"),
            '\u{000C}' => escaped.push_str("\\f"),
            '\r' => escaped.push_str("\\r"),
            character if character.is_control() => {
                let mut bytes = [0; 4];
                for byte in character.encode_utf8(&mut bytes).as_bytes() {
                    escaped.push_str(&format!("\\x{byte:02X}"));
                }
            }
            character => escaped.push(character),
        }
    }
    escaped.push('\'');
    escaped
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use chrono_tz::UTC;

    use super::*;
    use crate::domain::{Boundary, SChunkMs, SeedDomain, UtcMillis};

    /// The rendered scan for a spec, wide.
    fn full_sql(spec: &ScanSpec) -> String {
        scan_sql(spec, &ChunkProjection::FullColumns)
    }

    fn keys(names: &[&str]) -> ProjectedKeys {
        ProjectedKeys::new(
            names
                .iter()
                .map(|name| (*name).to_owned())
                .collect::<BTreeSet<_>>(),
        )
        .expect("the test key sets are non-empty")
    }

    /// The three wide goldens pin the whole query, so the projected cases assert only the part that
    /// varies. Extracted rather than re-rendered, so a change to the surrounding SQL cannot slip
    /// past by matching on a substring the test built the same way the code did.
    fn select_list_of(sql: &str) -> &str {
        sql.strip_prefix("SELECT ")
            .and_then(|rest| rest.split_once("\nFROM events AS e"))
            .map(|(select_list, _)| select_list)
            .expect("every rendered scan opens with its select list")
    }

    fn unbanded_spec() -> ScanSpec {
        spec(vec!["purchase".to_string()], BandSpec::new(0, 1).unwrap())
    }

    fn domain() -> SeedDomain {
        SeedDomain::new(
            1,
            Boundary::new(UtcMillis::new(2 * 86_400_000), UTC),
            UTC,
            SChunkMs(200_000_000),
        )
        .unwrap()
    }

    fn spec(event_names: Vec<String>, band: BandSpec) -> ScanSpec {
        match plan_scan(TeamId(2), &domain(), &EventNameSet::new(event_names), band) {
            ScanPlan::Scan(spec) => spec,
            ScanPlan::Vacuous => panic!("expected a scannable plan"),
        }
    }

    #[test]
    fn unbanded_scan_sql_pins_tenant_time_cutoff_and_override_semantics() {
        let spec = spec(
            vec!["purchase".to_string(), "$pageview".to_string()],
            BandSpec::new(0, 1).unwrap(),
        );
        assert_eq!(
            full_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('$pageview', 'purchase')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)"
        );
    }

    #[test]
    fn banded_scan_sql_hashes_the_resolved_person() {
        let spec = spec(vec!["purchase".to_string()], BandSpec::new(3, 8).unwrap());
        assert_eq!(
            full_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('purchase')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)\n  AND cityHash64(toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)))\n      % 8 = 3"
        );
    }

    #[test]
    fn scan_sql_escapes_hostile_event_names_as_literals() {
        let spec = spec(
            vec![
                "quote' OR 1 = 1 --".to_string(),
                "slash\\name\nnext".to_string(),
            ],
            BandSpec::new(0, 1).unwrap(),
        );
        assert_eq!(
            full_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('quote\\' OR 1 = 1 --', 'slash\\\\name\\nnext')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)"
        );
    }

    /// A `?` in an event name is a client-side hazard, not a server-side one: the `clickhouse`
    /// crate's template parser turns every bare `?` into a bind placeholder (and `?fields` into a
    /// struct-fields expansion) even inside string literals, failing the whole scan with
    /// "unbound query argument". Doubling each `?` renders the literal the server actually sees.
    #[test]
    fn scan_sql_doubles_question_marks_so_the_client_never_sees_a_placeholder() {
        let spec = spec(
            vec!["converted?".to_string(), "why?fields".to_string()],
            BandSpec::new(0, 1).unwrap(),
        );
        let sql = full_sql(&spec);
        assert!(sql.contains("e.event IN ('converted??', 'why??fields')"));
        let unescaped_placeholders = sql
            .char_indices()
            .filter(|(_, character)| *character == '?')
            .filter(|(index, _)| {
                !sql[index + 1..].starts_with('?') && (*index == 0 || !sql[..*index].ends_with('?'))
            })
            .count();
        assert_eq!(unescaped_placeholders, 0, "a lone `?` survived escaping");
    }

    /// A chunk whose conditions read nothing but the always-kept columns. Every narrowable column
    /// becomes an empty literal, so ClickHouse reads none of them — this is the shape the whole
    /// change exists to produce.
    #[test]
    fn a_chunk_reading_no_narrowable_column_selects_four_empty_literals() {
        let projection = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Empty,
            elements_chain: ScalarColumn::Empty,
            properties: BlobSource::Empty,
            person_properties: BlobSource::Empty,
        });
        assert_eq!(
            select_list_of(&scan_sql(&unbanded_spec(), &projection)),
            "'' AS uuid, e.event, '' AS properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       '' AS person_properties, '' AS elements_chain"
        );
    }

    /// The mixed shape production will mostly render: one blob rebuilt from named keys, the other
    /// needed whole because some condition hands the object somewhere.
    #[test]
    fn a_mixed_plan_rebuilds_one_blob_and_keeps_the_other_whole() {
        let projection = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Keep,
            elements_chain: ScalarColumn::Empty,
            properties: BlobSource::Keys(keys(&["plan", "utm_source"])),
            person_properties: BlobSource::Full,
        });
        assert_eq!(
            select_list_of(&scan_sql(&unbanded_spec(), &projection)),
            "toString(e.uuid) AS uuid, e.event, if(JSONType(e.properties) != 'Object', e.properties, concat('{', arrayStringConcat(arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), arrayFilter(kv -> kv.1 IN ('plan', 'utm_source'), JSONExtractKeysAndValuesRaw(e.properties))), ','), '}')) AS properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, '' AS elements_chain"
        );
    }

    /// The mirror image, which is what proves each blob rebuilds from its own column under its own
    /// alias. A rebuild that read `e.properties` for both, or aliased both as `properties`, still
    /// matches the case above and its golden.
    #[test]
    fn the_person_blob_rebuilds_from_its_own_column_and_alias() {
        let projection = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Keep,
            elements_chain: ScalarColumn::Empty,
            properties: BlobSource::Full,
            person_properties: BlobSource::Keys(keys(&["email", "plan"])),
        });
        assert_eq!(
            select_list_of(&scan_sql(&unbanded_spec(), &projection)),
            "toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       if(JSONType(e.person_properties) != 'Object', e.person_properties, concat('{', arrayStringConcat(arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), arrayFilter(kv -> kv.1 IN ('email', 'plan'), JSONExtractKeysAndValuesRaw(e.person_properties))), ','), '}')) AS person_properties, '' AS elements_chain"
        );
    }

    /// Property keys are customer-defined, so they reach the SQL through the same escaping the
    /// event names use — a quote would otherwise close the literal and the rest of the key would
    /// parse as SQL. The `?` doubling matters as much here: an unescaped one never reaches
    /// ClickHouse at all, because the client reads it as a bind placeholder and fails the query.
    #[test]
    fn projected_keys_are_escaped_like_every_other_literal() {
        let projection = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Empty,
            elements_chain: ScalarColumn::Keep,
            properties: BlobSource::Keys(keys(&[
                "quote' OR 1 = 1 --",
                "slash\\key\nnext",
                "converted?",
                "$feature/flag",
            ])),
            person_properties: BlobSource::Empty,
        });
        let sql = scan_sql(&unbanded_spec(), &projection);
        assert!(
            sql.contains(
                "kv.1 IN ('$feature/flag', 'converted??', 'quote\\' OR 1 = 1 --', 'slash\\\\key\\nnext')"
            ),
            "{sql}"
        );
        assert_eq!(
            select_list_of(&sql).matches("'' AS uuid").count(),
            1,
            "{sql}"
        );
        assert!(select_list_of(&sql).ends_with("e.elements_chain"), "{sql}");
    }

    /// The wide arm and the plan that keeps every column render the same text, which is what makes
    /// the frozen strings above a contract over both. Without this, the fallback could drift into a
    /// second, untested spelling of today's scan.
    #[test]
    fn the_full_columns_arm_renders_exactly_the_all_columns_plan() {
        let spec = unbanded_spec();
        assert_eq!(
            scan_sql(&spec, &ChunkProjection::FullColumns),
            scan_sql(&spec, &ChunkProjection::Projected(ColumnPlan::full()))
        );
    }
}
