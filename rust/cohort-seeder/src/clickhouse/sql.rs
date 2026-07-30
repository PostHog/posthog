//! ClickHouse scan planning: the `Vacuous`-vs-`Scan` parse and the byte-frozen SQL renderer. Depends
//! on `domain` (the proven range/band/event-name inputs) and `cohort-core`; never on `store`.

use std::num::NonZeroU32;

use cohort_core::filters::TeamId;

use crate::domain::{BandSpec, EventNameSet, SeedDomain};

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

pub fn scan_sql(spec: &ScanSpec) -> String {
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
        "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = {}\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = {}\n  AND e.timestamp >= fromUnixTimestamp64Milli({})\n  AND e.timestamp < fromUnixTimestamp64Milli({})\n  AND e.event IN ({})\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli({}){}",
        spec.team_id.0,
        spec.team_id.0,
        spec.day_start_ms,
        spec.day_end_ms,
        event_names,
        spec.s_chunk_ms,
        band_predicate,
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
    use chrono_tz::UTC;

    use super::*;
    use crate::domain::{Boundary, SChunkMs, SeedDomain, UtcMillis};

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
            scan_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('$pageview', 'purchase')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)"
        );
    }

    #[test]
    fn banded_scan_sql_hashes_the_resolved_person() {
        let spec = spec(vec!["purchase".to_string()], BandSpec::new(3, 8).unwrap());
        assert_eq!(
            scan_sql(&spec),
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
            scan_sql(&spec),
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
        let sql = scan_sql(&spec);
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
}
