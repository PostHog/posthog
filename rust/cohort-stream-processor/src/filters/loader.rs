//! SQL load + pure row→catalog transform. [`load_realtime_cohorts`] is the only DB touch;
//! [`build_catalog_from_rows`] is pure so the catalog logic is testable without Postgres.

use std::collections::HashMap;

use chrono_tz::{Tz, UTC};
use common_types::cohort::TeamAllowlist;
use metrics::counter;
use serde_json::Value;
use sqlx::PgPool;
use tracing::warn;

use crate::filters::manager::FilterCatalog;
use crate::filters::reverse_index::TeamFiltersBuilder;
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::{
    FILTER_CATALOG_COHORT_PARSE_ERRORS, FILTER_CATALOG_TZ_FALLBACK,
};

/// Realtime cohorts to load, mirroring the Node filter manager's predicate, joined to
/// `posthog_team` for the team timezone the bucket variants use for calendar-day computation.
pub const REALTIME_COHORTS_SQL: &str = "SELECT c.id, c.team_id, c.filters, t.timezone \
     FROM posthog_cohort c \
     JOIN posthog_team t ON t.id = c.team_id \
     WHERE c.cohort_type = 'realtime' AND c.deleted = false AND c.filters IS NOT NULL";

/// One realtime cohort row; `filters` is the `jsonb` column decoded to a `Value`.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CohortRow {
    pub id: i32,
    pub team_id: i32,
    pub filters: Value,
    /// `posthog_team.timezone` — a non-null IANA zone name (default `"UTC"`).
    pub timezone: String,
}

pub async fn load_realtime_cohorts(pool: &PgPool) -> Result<Vec<CohortRow>, FilterError> {
    let rows = sqlx::query_as::<_, CohortRow>(REALTIME_COHORTS_SQL)
        .fetch_all(pool)
        .await?;
    Ok(rows)
}

/// Drop rows for teams outside `allowlist`, in place, before catalog building. Kept separate from
/// [`build_catalog_from_rows`] (which stays allowlist-agnostic) and DB-free for unit testability.
/// Keeps the catalog lean and scopes shadow output for events injected directly into the stream.
pub(crate) fn retain_allowlisted(rows: &mut Vec<CohortRow>, allowlist: &TeamAllowlist) {
    rows.retain(|row| allowlist.includes(row.team_id));
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

        if let Err(err) = builder.add_cohort(cohort_id, team_id, &row.filters) {
            counter!(FILTER_CATALOG_COHORT_PARSE_ERRORS).increment(1);
            warn!(
                cohort_id = cohort_id.0,
                team_id = team_id.0,
                error = %err,
                "skipping cohort that failed to parse",
            );
        }
    }

    FilterCatalog::from_teams(
        builders
            .into_iter()
            .map(|(team, (builder, tz))| (team, builder.freeze_with(tz, cascade_enabled))),
    )
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
    use std::collections::HashSet;

    use super::*;
    use serde_json::json;

    fn row(id: i32, team_id: i32, filters: Value) -> CohortRow {
        row_with_tz(id, team_id, filters, "UTC")
    }

    fn row_with_tz(id: i32, team_id: i32, filters: Value, timezone: &str) -> CohortRow {
        CohortRow {
            id,
            team_id,
            filters,
            timezone: timezone.to_string(),
        }
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
        use crate::stage2::{CohortEligibility, ExcludedReason};

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

    #[test]
    fn retain_allowlisted_keeps_only_in_scope_rows() {
        let mut rows = vec![
            row(1, 2, behavioral_cohort()),
            row(2, 7, behavioral_cohort()),
        ];
        retain_allowlisted(&mut rows, &TeamAllowlist::Only(HashSet::from([2])));
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].team_id, 2);
    }

    #[test]
    fn retain_allowlisted_all_keeps_everything() {
        let mut rows = vec![
            row(1, 2, behavioral_cohort()),
            row(2, 7, behavioral_cohort()),
        ];
        retain_allowlisted(&mut rows, &TeamAllowlist::All);
        assert_eq!(rows.len(), 2);
    }

    #[test]
    fn retain_allowlisted_empty_scope_drops_everything() {
        let mut rows = vec![row(1, 2, behavioral_cohort())];
        retain_allowlisted(&mut rows, &TeamAllowlist::Only(HashSet::new()));
        assert!(rows.is_empty());
    }
}
