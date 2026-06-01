//! SQL load + pure row→catalog transform. [`load_realtime_cohorts`] is the only DB touch;
//! [`build_catalog_from_rows`] is pure so the catalog logic is testable without Postgres.

use std::collections::HashMap;

use metrics::counter;
use serde_json::Value;
use sqlx::PgPool;
use tracing::warn;

use crate::config::TeamAllowlist;
use crate::filters::manager::FilterCatalog;
use crate::filters::reverse_index::TeamFiltersBuilder;
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::FILTER_CATALOG_COHORT_PARSE_ERRORS;

/// Realtime cohorts to load, mirroring the Node filter manager's predicate
/// (`realtime-supported-filter-manager-cdp.ts`).
pub const REALTIME_COHORTS_SQL: &str = "SELECT id, team_id, filters \
     FROM posthog_cohort \
     WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL";

/// One realtime cohort row; `filters` is the `jsonb` column decoded to a `Value`.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CohortRow {
    pub id: i32,
    pub team_id: i32,
    pub filters: Value,
}

pub async fn load_realtime_cohorts(pool: &PgPool) -> Result<Vec<CohortRow>, FilterError> {
    let rows = sqlx::query_as::<_, CohortRow>(REALTIME_COHORTS_SQL)
        .fetch_all(pool)
        .await?;
    Ok(rows)
}

/// Drop rows for teams outside `allowlist`, in place, before catalog building. Kept separate from
/// [`build_catalog_from_rows`] (which stays allowlist-agnostic so its tests need no scoping setup)
/// and DB-free so the gate is unit-testable. The shuffler already gates the firehose; this keeps the
/// catalog lean and scopes shadow output even for events injected straight into `cohort_stream_events`.
pub(crate) fn retain_allowlisted(rows: &mut Vec<CohortRow>, allowlist: &TeamAllowlist) {
    rows.retain(|row| allowlist.includes(row.team_id));
}

/// Group rows by team into a catalog. A cohort that fails to parse is counted, warned, and skipped
/// rather than poisoning the rest of the catalog.
pub fn build_catalog_from_rows(rows: Vec<CohortRow>) -> FilterCatalog {
    let mut builders: HashMap<TeamId, TeamFiltersBuilder> = HashMap::new();

    for row in rows {
        let team_id = TeamId(row.team_id);
        let cohort_id = CohortId(row.id);
        let builder = builders.entry(team_id).or_default();

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
            .map(|(team, builder)| (team, builder.freeze())),
    )
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::*;
    use serde_json::json;

    fn row(id: i32, team_id: i32, filters: Value) -> CohortRow {
        CohortRow {
            id,
            team_id,
            filters,
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
        let catalog = build_catalog_from_rows(vec![]);
        assert_eq!(catalog.team_count(), 0);
    }

    #[test]
    fn malformed_cohort_is_skipped_without_poisoning_the_team() {
        let rows = vec![
            row(1, 7, json!({ "bogus": true })),
            row(2, 7, behavioral_cohort()),
        ];
        let catalog = build_catalog_from_rows(rows);

        let team = catalog.team(TeamId(7)).expect("team present");
        assert!(team.cohorts.contains_key(&CohortId(2)));
        assert!(!team.cohorts.contains_key(&CohortId(1)));
        assert_eq!(team.unique_condition_hashes.len(), 1);
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
