//! SQL load + pure row→catalog transform (TDD §2.7).
//!
//! [`load_realtime_cohorts`] is the only DB touch; [`build_catalog_from_rows`] is a pure
//! function (the unit-testable seam) so the catalog logic is exercised without Postgres.

use std::collections::HashMap;

use metrics::counter;
use serde_json::Value;
use sqlx::PgPool;
use tracing::warn;

use crate::filters::manager::FilterCatalog;
use crate::filters::reverse_index::TeamFiltersBuilder;
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::FILTER_CATALOG_COHORT_PARSE_ERRORS;

/// Realtime cohorts to load. Mirrors the Node filter manager's predicate
/// (`realtime-supported-filter-manager-cdp.ts`): `cohort_type='realtime'`, not deleted, with a
/// non-null `filters`.
pub const REALTIME_COHORTS_SQL: &str = "SELECT id, team_id, filters \
     FROM posthog_cohort \
     WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL";

/// One realtime cohort row. `filters` is the `jsonb` column, decoded straight to a `Value`
/// (sqlx 0.8 + the `json` feature).
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CohortRow {
    pub id: i32,
    pub team_id: i32,
    pub filters: Value,
}

/// Load every realtime cohort from `posthog_cohort`.
pub async fn load_realtime_cohorts(pool: &PgPool) -> Result<Vec<CohortRow>, FilterError> {
    let rows = sqlx::query_as::<_, CohortRow>(REALTIME_COHORTS_SQL)
        .fetch_all(pool)
        .await?;
    Ok(rows)
}

/// Pure transform from rows to a catalog — the unit-testable seam (hand-built rows, no DB).
/// Cohorts are grouped by team; a cohort that fails to parse is counted, warned, and skipped,
/// never poisoning the rest of the catalog (D-4).
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
        // First cohort has no `properties` → parse error → skipped; the second still loads.
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
}
