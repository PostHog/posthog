//! SQL load + pure row→catalog transform. [`load_realtime_cohorts`] is the only DB touch;
//! [`build_catalog_from_rows`] is pure so the catalog logic is testable without Postgres.

use std::collections::HashMap;

use chrono_tz::{Tz, UTC};
use metrics::counter;
use serde_json::Value;
use sqlx::PgPool;
use tracing::warn;

use crate::filters::catalog::FilterCatalog;
use crate::filters::reverse_index::TeamFiltersBuilder;
use crate::filters::{CohortId, FilterError, TeamId};
use crate::metrics::{
    FILTER_CATALOG_COHORT_PARSE_ERRORS, FILTER_CATALOG_INVALID_SHAPE_HASH,
    FILTER_CATALOG_TZ_FALLBACK,
};
use crate::seed::{BehavioralShapeHash, PersonShapeHash, ScopeKind, ShapeHashError};

/// Realtime cohorts to load, mirroring the Node filter manager's predicate, joined to
/// `posthog_team` for the team timezone the bucket variants use for calendar-day computation.
pub const REALTIME_COHORTS_SQL: &str = "SELECT c.id, c.team_id, c.filters, \
            c.behavioral_filters_shape_hash, c.person_filters_shape_hash, t.timezone \
     FROM posthog_cohort c \
     JOIN posthog_team t ON t.id = c.team_id \
     WHERE c.cohort_type = 'realtime' AND c.deleted = false AND c.filters IS NOT NULL";

/// One realtime cohort row; `filters` is the `jsonb` column decoded to a `Value`.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CohortRow {
    pub id: i32,
    pub team_id: i32,
    pub filters: Value,
    pub behavioral_filters_shape_hash: Option<String>,
    pub person_filters_shape_hash: Option<String>,
    /// `posthog_team.timezone` — a non-null IANA zone name (default `"UTC"`).
    pub timezone: String,
}

pub async fn load_realtime_cohorts(pool: &PgPool) -> Result<Vec<CohortRow>, FilterError> {
    let rows = sqlx::query_as::<_, CohortRow>(REALTIME_COHORTS_SQL)
        .fetch_all(pool)
        .await?;
    Ok(rows)
}

/// Group rows by team into a catalog. A cohort that fails to parse is counted, warned, and skipped
/// rather than poisoning the rest of the catalog.
pub fn build_catalog_from_rows(rows: Vec<CohortRow>, cascade_enabled: bool) -> FilterCatalog {
    let mut builders: HashMap<TeamId, (TeamFiltersBuilder, Tz)> = HashMap::new();

    for row in rows {
        let team_id = TeamId(row.team_id);
        let cohort_id = CohortId(row.id);
        // The timezone is a team-level column, so resolve it once on the team's first row.
        let (builder, _tz) = builders.entry(team_id).or_insert_with(|| {
            (
                TeamFiltersBuilder::default(),
                resolve_team_tz(&row.timezone, team_id),
            )
        });

        match builder.add_cohort(cohort_id, team_id, &row.filters) {
            Ok(()) => {
                let cohort = (cohort_id, team_id);
                if let Some(hash) = shape_guard(
                    row.behavioral_filters_shape_hash.as_deref(),
                    BehavioralShapeHash::parse,
                    ScopeKind::Behavioral,
                    cohort,
                ) {
                    builder.set_behavioral_shape_hash(cohort_id, hash);
                }
                if let Some(hash) = shape_guard(
                    row.person_filters_shape_hash.as_deref(),
                    PersonShapeHash::parse,
                    ScopeKind::PersonProperty,
                    cohort,
                ) {
                    builder.set_person_shape_hash(cohort_id, hash);
                }
            }
            Err(err) => {
                counter!(FILTER_CATALOG_COHORT_PARSE_ERRORS).increment(1);
                warn!(
                    cohort_id = cohort_id.0,
                    team_id = team_id.0,
                    error = %err,
                    "skipping cohort that failed to parse",
                );
            }
        }
    }

    FilterCatalog::from_teams(
        builders
            .into_iter()
            .map(|(team, (builder, tz))| (team, builder.freeze_with(tz, cascade_enabled))),
    )
}

/// One persisted shape-hash column as a reconcile guard, or `None` when there is nothing to guard
/// with. Python's canonical extractor returns an empty string for a cohort with no leaves of that
/// kind, so NULL and `""` are expected absences rather than malformed data; only a value that
/// fails the newtype's bounds is counted and warned.
fn shape_guard<T>(
    raw: Option<&str>,
    parse: fn(&str) -> Result<T, ShapeHashError>,
    kind: ScopeKind,
    (cohort_id, team_id): (CohortId, TeamId),
) -> Option<T> {
    let raw = raw.filter(|hash| !hash.is_empty())?;
    match parse(raw) {
        Ok(hash) => Some(hash),
        Err(error) => {
            counter!(FILTER_CATALOG_INVALID_SHAPE_HASH, "kind" => kind.as_str()).increment(1);
            warn!(
                cohort_id = cohort_id.0,
                team_id = team_id.0,
                kind = kind.as_str(),
                error = %error,
                "ignoring invalid persisted shape hash",
            );
            None
        }
    }
}

/// Resolve a team's `posthog_team.timezone`, falling back to UTC for an unrecognized zone. Counts
/// and logs the fallback with the offending `team_id`. The raw string goes only to the `warn!`,
/// never the (label-free) counter.
fn resolve_team_tz(raw: &str, team_id: TeamId) -> Tz {
    raw.parse::<Tz>().unwrap_or_else(|_| {
        counter!(FILTER_CATALOG_TZ_FALLBACK).increment(1);
        warn!(
            team_id = team_id.0,
            timezone = raw,
            "unrecognized team timezone; falling back to UTC",
        );
        UTC
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const SHAPE_HASH: &str = "persisted-authoritative-hash";

    fn row(id: i32, team_id: i32, filters: Value) -> CohortRow {
        row_with_tz(id, team_id, filters, "UTC")
    }

    fn row_with_tz(id: i32, team_id: i32, filters: Value, timezone: &str) -> CohortRow {
        CohortRow {
            id,
            team_id,
            filters,
            behavioral_filters_shape_hash: None,
            person_filters_shape_hash: None,
            timezone: timezone.to_string(),
        }
    }

    const PERSON_SHAPE_HASH: &str = "persisted-person-hash";

    /// A parseable cohort with its two guard columns set independently, so no assertion can pass
    /// while the loader reads the wrong one.
    fn row_with_guards(id: i32, behavioral: Option<&str>, person: Option<&str>) -> CohortRow {
        let mut row = row(id, 7, behavioral_cohort());
        row.behavioral_filters_shape_hash = behavioral.map(str::to_string);
        row.person_filters_shape_hash = person.map(str::to_string);
        row
    }

    fn behavioral_cohort() -> Value {
        json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "behavioral",
                    "value": "performed_event",
                    "key": "$pageview",
                    "time_value": 7,
                    "time_interval": "day",
                    "conditionHash": "0123456789abcdef",
                    "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
                }],
            }
        })
    }

    #[test]
    fn empty_rows_build_an_empty_catalog() {
        let catalog = build_catalog_from_rows(vec![], false);
        assert_eq!(catalog.team_count(), 0);
    }

    #[test]
    fn build_catalog_carries_only_valid_persisted_shape_hashes() {
        assert!(REALTIME_COHORTS_SQL.contains("c.behavioral_filters_shape_hash"));
        assert!(REALTIME_COHORTS_SQL.contains("c.person_filters_shape_hash"));
        let mut malformed = row(5, 7, json!({ "bogus": true }));
        malformed.behavioral_filters_shape_hash = Some(SHAPE_HASH.to_string());
        malformed.person_filters_shape_hash = Some(PERSON_SHAPE_HASH.to_string());
        let catalog = build_catalog_from_rows(
            vec![
                row_with_guards(1, Some(SHAPE_HASH), Some(PERSON_SHAPE_HASH)),
                row_with_guards(2, None, None),
                row_with_guards(3, Some(""), Some("")),
                row_with_guards(4, Some("non-ascii-é"), Some("non-ascii-é")),
                malformed,
                // A cohort with leaves of only one kind carries only that kind's guard.
                row_with_guards(6, Some(SHAPE_HASH), None),
                row_with_guards(7, None, Some(PERSON_SHAPE_HASH)),
            ],
            false,
        );

        let team = catalog.team(TeamId(7)).expect("team present");
        assert_eq!(
            team.behavioral_shape_hashes[&CohortId(1)].as_str(),
            SHAPE_HASH,
        );
        assert_eq!(
            team.person_shape_hashes[&CohortId(1)].as_str(),
            PERSON_SHAPE_HASH,
        );
        // NULL, empty (no leaves of that kind), invalid, and unparsed-cohort rows all carry no guard.
        for absent in [2, 3, 4, 5] {
            assert!(!team.behavioral_shape_hashes.contains_key(&CohortId(absent)));
            assert!(!team.person_shape_hashes.contains_key(&CohortId(absent)));
        }
        assert!(team.behavioral_shape_hashes.contains_key(&CohortId(6)));
        assert!(!team.person_shape_hashes.contains_key(&CohortId(6)));
        assert!(!team.behavioral_shape_hashes.contains_key(&CohortId(7)));
        assert!(team.person_shape_hashes.contains_key(&CohortId(7)));
        assert!(team.cohorts.contains_key(&CohortId(3)));
        assert!(
            team.cohorts.contains_key(&CohortId(4)),
            "only the bad hash is ignored"
        );
        assert!(
            !team.cohorts.contains_key(&CohortId(5)),
            "the malformed cohort is skipped"
        );
    }

    #[test]
    fn build_catalog_resolves_team_timezone_and_falls_back_to_utc() {
        use chrono_tz::America::New_York;
        let rows = vec![
            row_with_tz(1, 7, behavioral_cohort(), "America/New_York"),
            row_with_tz(2, 9, behavioral_cohort(), "not a real zone"),
        ];
        let catalog = build_catalog_from_rows(rows, false);
        assert_eq!(catalog.team(TeamId(7)).expect("team 7").timezone, New_York);
        assert_eq!(
            catalog.team(TeamId(9)).expect("team 9").timezone,
            UTC,
            "an unrecognized zone falls back to UTC",
        );
    }

    #[test]
    fn malformed_cohort_is_skipped_without_poisoning_the_team() {
        let rows = vec![
            row(1, 7, json!({ "bogus": true })),
            row(2, 7, behavioral_cohort()),
        ];
        let catalog = build_catalog_from_rows(rows, false);

        let team = catalog.team(TeamId(7)).expect("team present");
        assert!(team.cohorts.contains_key(&CohortId(2)));
        assert!(!team.cohorts.contains_key(&CohortId(1)));
        assert_eq!(team.unique_condition_hashes.len(), 1);
    }

    #[test]
    fn build_catalog_threads_the_cascade_gate_into_freeze() {
        use crate::eligibility::{CohortEligibility, ExcludedReason};

        let referrer = json!({
            "properties": {
                "type": "AND",
                "values": [{ "type": "cohort", "value": 2, "negation": false }],
            }
        });
        let rows = || vec![row(2, 7, behavioral_cohort()), row(1, 7, referrer.clone())];

        let off = build_catalog_from_rows(rows(), false);
        assert_eq!(
            off.team(TeamId(7)).unwrap().eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
            "gate off keeps the ref cohort excluded",
        );

        let on = build_catalog_from_rows(rows(), true);
        assert_eq!(
            on.team(TeamId(7)).unwrap().eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
            "gate on promotes the resolvable ref cohort",
        );
    }
}
