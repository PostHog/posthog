//! End-to-end tests of the DeletePersons endpoint flow: the RPC drives the
//! delete saga to a terminal step and the response is the recorded outcome.

mod common;

use std::sync::Arc;

use chrono::Utc;
use common::TestContext;
use tonic::Request;
use uuid::Uuid;

use personhog_identity::lifecycle::delete::SEAL_VERSION_MARGIN;
use personhog_identity::lifecycle::PersonHogLifecycleService;
use personhog_identity::storage::{IdentityStorage, PersonStub, StubOutcome};
use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::{DeletePersonOutcome, DeletePersonsRequest};

/// Storage-assertion helpers used only by this test binary.
impl TestContext {
    fn lifecycle_service(&self) -> PersonHogLifecycleService {
        PersonHogLifecycleService::new(Arc::new(self.engine()))
    }

    /// (is_deleted, version, properties) of a person row.
    async fn person_state(&self, person_id: i64) -> (bool, i64, String) {
        sqlx::query_as(
            r#"
            SELECT is_deleted, version, properties::text
            FROM posthog_person WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(self.team_id as i32)
        .bind(person_id)
        .fetch_one(&self.pool)
        .await
        .expect("person row exists")
    }

    /// (is_deleted, version) of a distinct id row.
    async fn pdi_state(&self, distinct_id: &str) -> (bool, i64) {
        sqlx::query_as(
            r#"
            SELECT is_deleted, version
            FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2
            "#,
        )
        .bind(self.team_id as i32)
        .bind(distinct_id)
        .fetch_one(&self.pool)
        .await
        .expect("distinct id row exists")
    }

    async fn set_person_properties(&self, person_id: i64, properties: &str) {
        sqlx::query(
            "UPDATE posthog_person SET properties = $3::jsonb WHERE team_id = $1 AND id = $2",
        )
        .bind(self.team_id as i32)
        .bind(person_id)
        .bind(properties)
        .execute(&self.pool)
        .await
        .expect("set properties");
    }

    async fn insert_cohort_and_hash_key_rows(&self, person_id: i64) {
        sqlx::query("INSERT INTO posthog_cohortpeople (cohort_id, person_id) VALUES (1, $1)")
            .bind(person_id)
            .execute(&self.pool)
            .await
            .expect("insert cohortpeople row");
        sqlx::query(
            r#"
            INSERT INTO posthog_featureflaghashkeyoverride
                (feature_flag_key, hash_key, person_id, team_id)
            VALUES ('flag', 'hash', $1, $2)
            "#,
        )
        .bind(person_id)
        .bind(self.team_id as i32)
        .execute(&self.pool)
        .await
        .expect("insert hash key override row");
    }

    async fn count_cohort_and_hash_key_rows(&self, person_id: i64) -> (i64, i64) {
        let cohort: i64 =
            sqlx::query_scalar("SELECT count(*) FROM posthog_cohortpeople WHERE person_id = $1")
                .bind(person_id)
                .fetch_one(&self.pool)
                .await
                .expect("count cohortpeople");
        let hash_key: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM posthog_featureflaghashkeyoverride WHERE person_id = $1",
        )
        .bind(person_id)
        .fetch_one(&self.pool)
        .await
        .expect("count hash key overrides");
        (cohort, hash_key)
    }

    /// (step, has_completed_at) of an op row.
    async fn op_state(&self, op_id: Uuid) -> (String, bool) {
        let row: (String, Option<chrono::DateTime<Utc>>) =
            sqlx::query_as("SELECT step, completed_at FROM lifecycle_op WHERE op_id = $1")
                .bind(op_id)
                .fetch_one(&self.pool)
                .await
                .expect("op row exists");
        (row.0, row.1.is_some())
    }

    /// Creates a person through the real stub-creation path, so its uuid is
    /// the deterministic uuidv5 and a post-delete re-create of the same
    /// distinct id conflicts with (and revives) the tombstone.
    async fn create_person_via_stub(&self, distinct_id: &str) -> i64 {
        let outcomes = self
            .storage
            .create_person_stubs(&[PersonStub {
                team_id: self.team_id,
                distinct_id: distinct_id.to_string(),
                extra_distinct_ids: vec![],
                created_at: Utc::now(),
                is_identified: false,
            }])
            .await
            .expect("stub creation succeeds");
        match &outcomes[0] {
            StubOutcome::Committed { person, .. } => person.id,
            StubOutcome::LostRace => panic!("no concurrent writers in this test"),
        }
    }
}

fn delete_request(team_id: i64, person_ids: Vec<i64>, op_id: Uuid) -> DeletePersonsRequest {
    DeletePersonsRequest {
        team_id,
        person_ids,
        op_id: op_id.to_string(),
    }
}

fn outcomes(
    response: &personhog_proto::personhog::lifecycle::v1::DeletePersonsResponse,
) -> Vec<(i64, DeletePersonOutcome)> {
    response
        .results
        .iter()
        .map(|r| (r.person_id, r.outcome()))
        .collect()
}

#[tokio::test]
async fn delete_destroys_the_person_and_its_satellite_rows() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let person_id = ctx.insert_person_with_distinct_id("victim-primary").await;
    sqlx::query(
        "INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version) VALUES ('victim-extra', $1, $2, 1)",
    )
    .bind(person_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert extra distinct id");
    ctx.set_person_properties(person_id, r#"{"email": "gdpr@example.com"}"#)
        .await;
    ctx.insert_cohort_and_hash_key_rows(person_id).await;

    let op_id = Uuid::now_v7();
    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![person_id],
            op_id,
        )))
        .await
        .expect("delete succeeds")
        .into_inner();

    assert_eq!(response.op_id, op_id.to_string());
    assert_eq!(
        outcomes(&response),
        vec![(person_id, DeletePersonOutcome::Deleted)]
    );

    // The person: tombstoned at sealed + 1 (version 0 at seal time), scrubbed.
    let (is_deleted, version, properties) = ctx.person_state(person_id).await;
    assert!(is_deleted);
    assert_eq!(version, SEAL_VERSION_MARGIN + 1);
    assert_eq!(properties, "{}");

    // The mappings: tombstoned one version above their previous one.
    assert_eq!(ctx.pdi_state("victim-primary").await, (true, 1));
    assert_eq!(ctx.pdi_state("victim-extra").await, (true, 2));

    // Cohort membership and hash-key overrides: cleared.
    assert_eq!(ctx.count_cohort_and_hash_key_rows(person_id).await, (0, 0));

    // The op: completed, with the per-person row settled and the tombstoned
    // mappings recorded in `moved`.
    assert_eq!(ctx.op_state(op_id).await, ("completed".to_string(), true));
    let (status, moved): (String, Option<serde_json::Value>) = sqlx::query_as(
        "SELECT status, moved FROM lifecycle_op_person WHERE op_id = $1 AND person_id = $2",
    )
    .bind(op_id)
    .bind(person_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("per-person row exists");
    assert_eq!(status, "deleted");
    let moved = moved.expect("moved recorded");
    let moved_ids: Vec<&str> = moved
        .as_array()
        .expect("moved is an array")
        .iter()
        .map(|m| m["distinct_id"].as_str().expect("distinct_id"))
        .collect();
    assert_eq!(moved_ids.len(), 2);
    assert!(moved_ids.contains(&"victim-primary") && moved_ids.contains(&"victim-extra"));

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn outcomes_follow_request_order_and_missing_persons_are_not_found() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let person_id = ctx.insert_person_with_distinct_id("mixed-batch").await;
    let missing_id = person_id + 1_000_000;

    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![missing_id, person_id],
            Uuid::now_v7(),
        )))
        .await
        .expect("delete succeeds")
        .into_inner();

    assert_eq!(
        outcomes(&response),
        vec![
            (missing_id, DeletePersonOutcome::NotFound),
            (person_id, DeletePersonOutcome::Deleted),
        ]
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_all_missing_batch_aborts_before_mutating_anything() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();
    let op_id = Uuid::now_v7();

    let response = service
        .delete_persons(Request::new(delete_request(ctx.team_id, vec![1, 2], op_id)))
        .await
        .expect("aborting is still an OK response")
        .into_inner();

    assert_eq!(
        outcomes(&response),
        vec![
            (1, DeletePersonOutcome::NotFound),
            (2, DeletePersonOutcome::NotFound),
        ]
    );
    assert_eq!(ctx.op_state(op_id).await, ("aborted".to_string(), true));

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_person_marked_by_another_live_op_is_skipped() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let contested = ctx.insert_person_with_distinct_id("contested").await;
    let free = ctx.insert_person_with_distinct_id("free").await;

    // Another live op (a merge, say) holds the contested person's mark.
    let other_op = Uuid::now_v7();
    sqlx::query(
        "INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at) VALUES ($1, 'merge', $2, 'claimed', '{}'::jsonb, now() + interval '1 hour')",
    )
    .bind(other_op)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert other op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) VALUES ($1, $2, $3, gen_random_uuid(), 'source', 'marked')",
    )
    .bind(other_op)
    .bind(ctx.team_id as i32)
    .bind(contested)
    .execute(&ctx.pool)
    .await
    .expect("insert other op's mark");

    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![contested, free],
            Uuid::now_v7(),
        )))
        .await
        .expect("delete succeeds")
        .into_inner();

    assert_eq!(
        outcomes(&response),
        vec![
            (contested, DeletePersonOutcome::SkippedConflict),
            (free, DeletePersonOutcome::Deleted),
        ]
    );
    // The contested person is untouched.
    let (is_deleted, version, _) = ctx.person_state(contested).await;
    assert!(!is_deleted);
    assert_eq!(version, 0);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_retry_with_the_same_op_id_returns_the_recorded_outcome() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let person_id = ctx.insert_person_with_distinct_id("retried").await;
    let op_id = Uuid::now_v7();
    let request = delete_request(ctx.team_id, vec![person_id], op_id);

    let first = service
        .delete_persons(Request::new(request.clone()))
        .await
        .expect("delete succeeds")
        .into_inner();
    assert_eq!(
        outcomes(&first),
        vec![(person_id, DeletePersonOutcome::Deleted)]
    );

    // The person no longer exists as a live row, but the retry still answers
    // DELETED — the recorded outcome, not a fresh evaluation.
    let retry = service
        .delete_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(
        outcomes(&retry),
        vec![(person_id, DeletePersonOutcome::Deleted)]
    );

    // A fresh op for the same (now tombstoned) person finds nothing to delete.
    let fresh = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![person_id],
            Uuid::now_v7(),
        )))
        .await
        .expect("fresh op succeeds")
        .into_inner();
    assert_eq!(
        outcomes(&fresh),
        vec![(person_id, DeletePersonOutcome::NotFound)]
    );

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_caller_retry_resumes_an_abandoned_op_from_its_saved_step() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let person_id = ctx.insert_person_with_distinct_id("resumed").await;
    let op_id = Uuid::now_v7();

    // The op crashed right after creating its row: step 'started', nothing
    // else persisted, lease lapsed.
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'delete', $2, 'started', $3, now() - interval '1 minute')
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .bind(serde_json::json!({"person_ids": [person_id]}))
    .execute(&ctx.pool)
    .await
    .expect("insert abandoned op");

    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![person_id],
            op_id,
        )))
        .await
        .expect("retry drives the op home")
        .into_inner();

    assert_eq!(
        outcomes(&response),
        vec![(person_id, DeletePersonOutcome::Deleted)]
    );
    let (is_deleted, _, _) = ctx.person_state(person_id).await;
    assert!(is_deleted);

    ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_recreated_distinct_id_revives_above_the_death_version() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    // Created through the real stub path so the person carries the uuidv5
    // key a re-create will collide with.
    let person_id = ctx.create_person_via_stub("reborn").await;

    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![person_id],
            Uuid::now_v7(),
        )))
        .await
        .expect("delete succeeds")
        .into_inner();
    assert_eq!(
        outcomes(&response),
        vec![(person_id, DeletePersonOutcome::Deleted)]
    );
    let (_, death_version, _) = ctx.person_state(person_id).await;

    // The same distinct id comes back: the create revives the tombstone one
    // version above the death document, so ClickHouse collapses toward the
    // new incarnation.
    let revived_id = ctx.create_person_via_stub("reborn").await;
    assert_eq!(revived_id, person_id, "revival reuses the tombstoned row");
    let (is_deleted, version, _) = ctx.person_state(person_id).await;
    assert!(!is_deleted);
    assert_eq!(version, death_version + 1);

    ctx.cleanup().await.expect("cleanup");
}
