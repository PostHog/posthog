//! Runs the cohort loads against the tables Django creates. It fails instead of skipping without a
//! database, because CI builds `test_posthog` before the Rust tests.

use cohort_core::filters::{
    load_realtime_cohort_teams, load_realtime_cohorts, load_realtime_cohorts_for_teams, CohortRow,
};
use sqlx::postgres::PgPoolOptions;

const DEFAULT_TEST_DATABASE_URL: &str = "postgres://posthog:posthog@localhost:5432/test_posthog";

fn team_and_cohort_ids(rows: Vec<CohortRow>) -> Vec<(i32, i32)> {
    let mut ids: Vec<(i32, i32)> = rows.into_iter().map(|row| (row.team_id, row.id)).collect();
    ids.sort_unstable();
    ids
}

#[tokio::test]
async fn every_load_selects_only_realtime_cohorts_that_are_on() {
    let url =
        std::env::var("DATABASE_URL").unwrap_or_else(|_| DEFAULT_TEST_DATABASE_URL.to_string());
    // The fixture tables are temporary, and a temporary table exists only in the session that
    // creates it. One connection keeps every statement below in that session.
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .unwrap_or_else(|e| panic!("this test needs the Django test database at {url}: {e}"));
    // A temporary table shadows the Django table of the same name, so the loads read these rows
    // and nothing is written to a shared table. A copy has Django's columns and none of its
    // constraints, so each insert names only the columns the loads read.
    sqlx::raw_sql(
        "CREATE TEMP TABLE posthog_team AS TABLE public.posthog_team WITH NO DATA; \
         CREATE TEMP TABLE posthog_cohort AS TABLE public.posthog_cohort WITH NO DATA; \
         INSERT INTO posthog_team (id, timezone) VALUES (1, 'UTC'), (2, 'UTC'), (3, 'UTC'); \
         INSERT INTO posthog_cohort \
             (id, team_id, cohort_type, realtime_enabled_at, is_static, deleted, filters) \
         VALUES (11, 1, 'realtime', now(), false, false, '{}'), \
                (12, 1, 'realtime', NULL, false, false, '{}'), \
                (13, 1, NULL, now(), false, false, '{}'), \
                (14, 1, 'realtime', now(), false, true, '{}'), \
                (15, 1, 'realtime', now(), true, false, '{}'), \
                (21, 2, 'realtime', NULL, false, false, '{}'), \
                (31, 3, 'realtime', now(), false, false, '{}');",
    )
    .execute(&pool)
    .await
    .expect("create the fixture tables");

    let all = load_realtime_cohorts(&pool).await.expect("load every team");
    let scoped = load_realtime_cohorts_for_teams(&pool, &[1, 2])
        .await
        .expect("load teams 1 and 2");
    let mut teams = load_realtime_cohort_teams(&pool)
        .await
        .expect("load the teams");
    teams.sort_unstable();

    // Cohort 12 is off, 13 is on but lost realtime support in an edit, 14 is on but deleted, and 15
    // is on but was converted to static.
    assert_eq!(team_and_cohort_ids(all), [(1, 11), (3, 31)]);
    assert_eq!(team_and_cohort_ids(scoped), [(1, 11)]);
    // Team 2's only cohort is off.
    assert_eq!(teams, [1, 3]);
}
