//! Polls the table that Django creates. It fails instead of skipping without a database, because CI
//! builds `test_posthog` before the Rust tests.

use std::collections::HashSet;

use common_cohort_team_access::TeamAccess;
use common_types::cohort::TeamAllowlist;
use rand::Rng;
use sqlx::PgPool;

const DEFAULT_TEST_DATABASE_URL: &str = "postgres://posthog:posthog@localhost:5432/test_posthog";

#[tokio::test]
async fn poll_reads_every_level_django_writes() {
    let url =
        std::env::var("DATABASE_URL").unwrap_or_else(|_| DEFAULT_TEST_DATABASE_URL.to_string());
    let pool = PgPool::connect(&url)
        .await
        .unwrap_or_else(|e| panic!("this test needs the Django test database at {url}: {e}"));
    // Random ids, so rows that a failed earlier run left behind cannot collide.
    let team_id: i32 = rand::thread_rng().gen_range(1_000_000_000..2_000_000_000);
    let teams = [team_id, team_id + 1, team_id + 2];
    sqlx::query(
        "INSERT INTO cohort_realtime_team_access \
             (team_id, level, purpose, save_triggers_backfill, processing_since, off_since, changed_at) \
         VALUES ($1, 'processing', 'load_test', false, now(), NULL, now()), \
                ($2, 'serving', 'pilot', true, now(), NULL, now()), \
                ($3, 'off', 'load_test', false, now(), now(), now())",
    )
    .bind(teams[0])
    .bind(teams[1])
    .bind(teams[2])
    .execute(&pool)
    .await
    .expect("insert access rows");

    let (access, mut poller) = TeamAccess::new(TeamAllowlist::Only(HashSet::new()));
    let polled = poller.poll(&pool).await;
    // Delete before asserting, so a failed assertion leaves no rows behind.
    sqlx::query("DELETE FROM cohort_realtime_team_access WHERE team_id = ANY($1)")
        .bind(&teams[..])
        .execute(&pool)
        .await
        .expect("delete access rows");

    polled.expect("poll the access table");
    assert!(access.processing(teams[0]));
    assert!(access.processing(teams[1]));
    assert!(!access.processing(teams[2]));
}
