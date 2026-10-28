//! Integration tests for /flags while the persons database stalls. During each fault, flags that
//! need no persons data still evaluate, and flags that need persons data fail within the persons
//! DB deadline. After the fault ends, the same server answers every flag again.
//!
//! These tests depend on timing, so CI runs them alone in the `flags-db-faults` job of `ci-rust.yml`. Run them
//! locally with `cargo test -p feature-flags --test test_persons_db_faults -- --ignored`.

use std::time::{Duration, Instant};

use anyhow::Result;
use reqwest::StatusCode;
use serde_json::{json, Value};

pub mod common;
use crate::common::persons_db_proxy::PersonsDbProxy;
use crate::common::ServerHandle;
use feature_flags::config::{Config, DEFAULT_TEST_CONFIG};
use feature_flags::flags::flag_models::FeatureFlagRow;
use feature_flags::team::team_models::Team;
use feature_flags::utils::test_utils::TestContext;

const DISTINCT_ID: &str = "stall_user";
const DB_FREE_FLAG: &str = "rollout-flag";
const PERSON_FLAG: &str = "person-flag";
const CONTINUITY_FLAG: &str = "continuity-flag";
/// The longest time that a response can take after the persons DB deadline.
const RESPONSE_SLACK: Duration = Duration::from_millis(1000);
/// The longest time that the server can take to answer every flag again after a fault ends.
const RECOVERY_LIMIT: Duration = Duration::from_secs(5);

fn flag_row(team_id: i32, key: &str, filters: Value) -> FeatureFlagRow {
    FeatureFlagRow {
        team_id,
        name: Some(key.to_string()),
        key: key.to_string(),
        filters,
        active: true,
        version: Some(1),
        ..Default::default()
    }
}

/// Inserts a team with a flag that needs no persons data, a flag on a person property, and an
/// experience continuity flag, plus a person who matches the person property flag.
async fn insert_team_with_flags(context: &TestContext) -> Result<(Team, i64)> {
    let team = context.insert_new_team(None).await?;
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                DB_FREE_FLAG,
                json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            )),
        )
        .await?;
    context
        .insert_flag(
            team.id,
            Some(flag_row(
                team.id,
                PERSON_FLAG,
                json!({"groups": [{
                    "properties": [{"key": "email", "value": "user@example.com", "operator": "exact", "type": "person"}],
                    "rollout_percentage": 100
                }]}),
            )),
        )
        .await?;
    // A continuity flag at 100% rollout skips the hash key override work. This flag uses 50% so
    // that the work runs.
    let mut continuity = flag_row(
        team.id,
        CONTINUITY_FLAG,
        json!({"groups": [{"properties": [], "rollout_percentage": 50}]}),
    );
    continuity.ensure_experience_continuity = Some(true);
    context.insert_flag(team.id, Some(continuity)).await?;
    let person_id = context
        .insert_person(
            team.id,
            DISTINCT_ID.to_string(),
            Some(json!({"email": "user@example.com"})),
        )
        .await?;
    Ok((team, person_id))
}

async fn start_server(config: Config, team: &Team) -> ServerHandle {
    ServerHandle::for_config_with_mock_redis(
        config,
        vec![],
        vec![(team.api_token.clone(), team.id)],
    )
    .await
}

/// Sends a /flags request with `$anon_distinct_id`, so that the continuity flag reads and writes
/// hash key overrides. Returns the response body and the response time.
async fn evaluate(server: &ServerHandle, team: &Team) -> Result<(Value, Duration)> {
    let payload = json!({
        "token": team.api_token,
        "distinct_id": DISTINCT_ID,
        "$anon_distinct_id": format!("anon_{DISTINCT_ID}"),
    });
    let started = Instant::now();
    let res = server
        .send_flags_request(payload.to_string(), Some("2"), None)
        .await;
    let status = res.status();
    let body = res.text().await?;
    let elapsed = started.elapsed();
    assert_eq!(status, StatusCode::OK, "{body}");
    Ok((serde_json::from_str(&body)?, elapsed))
}

fn is_healthy(body: &Value) -> bool {
    body["errorsWhileComputingFlags"] == json!(false)
        && body["flags"][DB_FREE_FLAG]["enabled"] == json!(true)
        && body["flags"][PERSON_FLAG]["enabled"] == json!(true)
        && [DB_FREE_FLAG, PERSON_FLAG, CONTINUITY_FLAG]
            .iter()
            .all(|key| body["flags"][key].is_object() && body["flags"][key].get("failed").is_none())
}

/// Sends one request during a fault and checks that only the flags that need persons data fail,
/// within `deadline` plus `RESPONSE_SLACK`.
async fn assert_person_flags_fail_within(
    server: &ServerHandle,
    team: &Team,
    deadline: Duration,
) -> Result<()> {
    let (body, elapsed) = evaluate(server, team).await?;
    assert!(
        elapsed < deadline + RESPONSE_SLACK,
        "the response took {elapsed:?}: {body}"
    );
    assert_eq!(body["errorsWhileComputingFlags"], json!(true), "{body}");
    assert_eq!(
        body["flags"][DB_FREE_FLAG]["enabled"],
        json!(true),
        "{body}"
    );
    assert!(
        body["flags"][DB_FREE_FLAG].get("failed").is_none(),
        "{body}"
    );
    for key in [CONTINUITY_FLAG, PERSON_FLAG] {
        assert_eq!(body["flags"][key]["failed"], json!(true), "{key}: {body}");
    }
    Ok(())
}

/// Sends requests until one answers every flag, and fails the test after `RECOVERY_LIMIT`.
async fn assert_recovers(server: &ServerHandle, team: &Team) -> Result<()> {
    let started = Instant::now();
    loop {
        let (body, _) = evaluate(server, team).await?;
        if is_healthy(&body) {
            return Ok(());
        }
        assert!(
            started.elapsed() < RECOVERY_LIMIT,
            "no recovery after {RECOVERY_LIMIT:?}: {body}"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

#[tokio::test]
#[ignore = "depends on timing; runs alone in the flags-db-faults CI job"]
async fn person_flags_fail_at_the_deadline_when_replies_arrive_late() -> Result<()> {
    let context = TestContext::new(None).await;
    let (team, _) = insert_team_with_flags(&context).await?;
    let proxy = PersonsDbProxy::start().await?;
    let deadline = Duration::from_millis(500);
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.persons_read_database_url = proxy.url();
    config.persons_db_deadline_ms = deadline.as_millis() as u64;
    // With more connections, the pool opens a new connection and routes around the held one.
    config.max_pg_connections = 1;
    let server = start_server(config, &team).await;

    // This request opens the persons reader connection that the fault then holds.
    let (body, _) = evaluate(&server, &team).await?;
    assert!(is_healthy(&body), "{body}");

    proxy.hold_replies_on_open_connections();
    assert_person_flags_fail_within(&server, &team, deadline).await?;

    proxy.resume();
    assert_recovers(&server, &team).await
}

#[tokio::test]
#[ignore = "depends on timing; runs alone in the flags-db-faults CI job"]
async fn person_flags_fail_at_the_deadline_when_a_lock_wait_outlasts_it() -> Result<()> {
    let context = TestContext::new(None).await;
    let (team, person_id) = insert_team_with_flags(&context).await?;
    let deadline = Duration::from_millis(500);
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.persons_db_deadline_ms = deadline.as_millis() as u64;
    // Postgres must not end the lock wait before the deadline does.
    assert!(config.writer_statement_timeout_ms > 2 * deadline.as_millis() as u64);
    let server = start_server(config, &team).await;

    // A person delete holds this lock. The hash key override insert checks its foreign key to the
    // person row, so it waits for the lock. Only this team's person row is locked, so tests that
    // run in parallel are not affected.
    let mut conn = context.get_persons_connection().await?;
    sqlx::query("BEGIN").execute(&mut *conn).await?;
    sqlx::query("SELECT id FROM posthog_person WHERE id = $1 FOR UPDATE")
        .bind(person_id)
        .execute(&mut *conn)
        .await?;

    let result = assert_person_flags_fail_within(&server, &team, deadline).await;
    sqlx::query("ROLLBACK").execute(&mut *conn).await?;
    result?;

    assert_recovers(&server, &team).await
}

#[tokio::test]
#[ignore = "depends on timing; runs alone in the flags-db-faults CI job"]
async fn person_flags_fail_within_the_deadline_when_new_connections_open_too_slowly() -> Result<()>
{
    let context = TestContext::new(None).await;
    let (team, _) = insert_team_with_flags(&context).await?;
    let proxy = PersonsDbProxy::start().await?;
    // Before any request, the persons reader pool has no connections. Every acquire must
    // therefore open a connection, and the stall makes it wait for the acquire timeout.
    proxy.stall_new_connections();
    let deadline = Duration::from_millis(2500);
    let mut config = DEFAULT_TEST_CONFIG.clone();
    config.persons_read_database_url = proxy.url();
    config.persons_db_deadline_ms = deadline.as_millis() as u64;
    config.acquire_timeout_secs = 1;
    // Each persons DB call in the request waits the full acquire timeout before it fails.
    assert!(Duration::from_secs(config.acquire_timeout_secs) < deadline);
    let server = start_server(config, &team).await;

    assert_person_flags_fail_within(&server, &team, deadline).await?;

    proxy.resume();
    assert_recovers(&server, &team).await
}
