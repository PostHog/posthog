//! End-to-end tests of the DeletePersons endpoint flow: the RPC drives the
//! delete saga to a terminal step and the response is the recorded outcome.

mod common;

use std::sync::Arc;

use chrono::Utc;
use common::sim_leader::{LeaderCall, Rpc, SimLeader, FENCED_METADATA_KEY};
use common::TestContext;
use tonic::{Request, Status};
use uuid::Uuid;

use personhog_identity::lifecycle::delete::{DeleteDriver, DeleteOutcome};
use personhog_identity::lifecycle::engine::{Engine, OpRow, SagaError};
use personhog_identity::lifecycle::PersonHogLifecycleService;
use personhog_identity::storage::{IdentityStorage, PersonStub, StubOutcome};
use personhog_proto::personhog::lifecycle::v1::person_hog_lifecycle_server::PersonHogLifecycle;
use personhog_proto::personhog::lifecycle::v1::{DeletePersonOutcome, DeletePersonsRequest};

/// Storage-assertion helpers used only by this test binary.
impl TestContext {
    fn lifecycle_service(&self) -> PersonHogLifecycleService {
        let engine = Arc::new(self.engine());
        let leader = Arc::new(SimLeader::new(
            self.pool.clone(),
            self.tables.person.clone(),
        ));
        PersonHogLifecycleService::new(engine, leader.clone(), self.tables.clone())
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

    // The person: tombstoned at sealed + 1 (the fence sealed version 0),
    // scrubbed.
    let (is_deleted, version, properties) = ctx.person_state(person_id).await;
    assert!(is_deleted);
    assert_eq!(version, 1);
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

/// A mark can land on a corpse when a merge destroys the person between
/// the mark step's liveness filter and its insert. The seeded state is
/// what that window produces: a marked row whose person is already
/// tombstoned. The recheck must settle it as not_found without touching
/// the corpse again.
#[tokio::test]
async fn a_victim_destroyed_between_liveness_check_and_mark_settles_as_not_found() {
    let ctx = TestContext::new().await;
    let service = ctx.lifecycle_service();

    let live = ctx.insert_person_with_distinct_id("recheck-live").await;
    let corpse = ctx.insert_person_with_distinct_id("recheck-corpse").await;
    sqlx::query(
        "UPDATE posthog_person SET is_deleted = true, version = 5 WHERE team_id = $1 AND id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(corpse)
    .execute(&ctx.pool)
    .await
    .expect("tombstone the corpse");

    let op_id = Uuid::now_v7();
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, lease_expires_at)
        VALUES ($1, 'delete', $2, 'started', $3, now() - interval '1 minute')
        "#,
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .bind(serde_json::json!({"person_ids": [corpse, live]}))
    .execute(&ctx.pool)
    .await
    .expect("insert op");
    sqlx::query(
        "INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status) \
         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'marked')",
    )
    .bind(op_id)
    .bind(ctx.team_id as i32)
    .bind(corpse)
    .execute(&ctx.pool)
    .await
    .expect("insert the corpse's mark");

    let response = service
        .delete_persons(Request::new(delete_request(
            ctx.team_id,
            vec![corpse, live],
            op_id,
        )))
        .await
        .expect("delete succeeds")
        .into_inner();

    assert_eq!(
        outcomes(&response),
        vec![
            (corpse, DeletePersonOutcome::NotFound),
            (live, DeletePersonOutcome::Deleted),
        ]
    );
    let (is_deleted, version, _) = ctx.person_state(corpse).await;
    assert!(is_deleted);
    assert_eq!(version, 5, "the corpse was never re-tombstoned");
    let (is_deleted, _, _) = ctx.person_state(live).await;
    assert!(is_deleted, "the live victim's delete proceeded normally");

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

/// Fenced-mode walkthrough harness: the delete driver wired to a
/// [`SimLeader`], driven through the engine directly so tests can stop at
/// step boundaries and probe the leader's state in between.
struct FencedHarness {
    ctx: TestContext,
    engine: Engine,
    leader: Arc<SimLeader>,
    driver: DeleteDriver,
}

impl FencedHarness {
    async fn new() -> Self {
        let ctx = TestContext::new().await;
        let engine = ctx.engine();
        let leader = Arc::new(SimLeader::new(ctx.pool.clone(), ctx.tables.person.clone()));
        let driver = DeleteDriver::new(leader.clone(), ctx.tables.clone());
        Self {
            ctx,
            engine,
            leader,
            driver,
        }
    }

    fn request(person_ids: &[i64]) -> serde_json::Value {
        serde_json::json!({ "person_ids": person_ids })
    }

    async fn execute(&self, op_id: Uuid, person_ids: &[i64]) -> Result<OpRow, SagaError> {
        self.engine
            .execute(
                &self.driver,
                op_id,
                self.ctx.team_id,
                &Self::request(person_ids),
            )
            .await
    }

    async fn step(&self, op_id: Uuid) -> Result<OpRow, SagaError> {
        self.engine
            .step_once(&self.driver, op_id, self.ctx.team_id)
            .await
    }

    fn outcome(row: &OpRow) -> DeleteOutcome {
        serde_json::from_value(row.outcome.clone().expect("terminal outcome"))
            .expect("outcome parses")
    }
}

#[tokio::test]
async fn fenced_delete_seals_the_exact_version_and_produces_the_death_document() {
    let h = FencedHarness::new().await;
    let distinct_id = format!("fenced-victim-{}", Uuid::now_v7());
    let person_id = h.ctx.create_person_via_stub(&distinct_id).await;

    let op_id = Uuid::now_v7();
    let row = h
        .execute(op_id, &[person_id])
        .await
        .expect("fenced delete completes");
    let outcome = FencedHarness::outcome(&row);
    assert_eq!(outcome.results[0].outcome, "deleted");

    // The fence sealed the stub's exact version (0), so the tombstone and
    // the death document land at 1 — no margin.
    let (is_deleted, version, _) = h.ctx.person_state(person_id).await;
    assert!(is_deleted);
    assert_eq!(version, 1, "fenced seal must not add the pre-fence margin");
    let docs = h.leader.death_documents();
    assert_eq!(docs.len(), 1);
    assert_eq!(docs[0].person_id, person_id);
    assert_eq!(docs[0].version, 1);

    // The fence is gone, and it was installed before the release ran.
    assert!(h.leader.fence_for(person_id).is_none());
    let calls = h.leader.calls();
    let fence_at = calls
        .iter()
        .position(|c| matches!(c, LeaderCall::Fence { .. }))
        .expect("a fence call");
    let release_at = calls
        .iter()
        .position(|c| matches!(c, LeaderCall::ReleaseCommitted { .. }))
        .expect("a committed release call");
    assert!(fence_at < release_at);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_fenced_victim_rejects_writes_until_the_op_completes() {
    let h = FencedHarness::new().await;
    let distinct_id = format!("fenced-frozen-{}", Uuid::now_v7());
    let person_id = h.ctx.create_person_via_stub(&distinct_id).await;

    let op_id = Uuid::now_v7();
    h.engine
        .create_or_attach(
            &h.driver,
            op_id,
            h.ctx.team_id,
            &FencedHarness::request(&[person_id]),
        )
        .await
        .expect("create op");
    let row = h.step(op_id).await.expect("started -> marked");
    assert_eq!(row.step, "marked");
    let row = h.step(op_id).await.expect("marked -> sealed");
    assert_eq!(row.step, "sealed");

    // Sealed means fenced: an ordinary write is rejected with the leader's
    // typed fence metadata until the op finishes.
    let rejection = h
        .leader
        .admit_write(h.ctx.team_id, person_id)
        .await
        .expect_err("a sealed victim must reject writes");
    assert!(rejection.metadata().contains_key(FENCED_METADATA_KEY));

    let row = h.step(op_id).await.expect("sealed -> unmapped");
    assert_eq!(row.step, "unmapped");
    let row = h.step(op_id).await.expect("unmapped -> completed");
    assert!(row.completed_at.is_some());

    // The fence is released; the person now answers destroyed, not fenced.
    assert!(h.leader.fence_for(person_id).is_none());
    let destroyed = h
        .leader
        .admit_write(h.ctx.team_id, person_id)
        .await
        .expect_err("a destroyed person rejects writes");
    assert_eq!(destroyed.code(), tonic::Code::NotFound);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_transient_fence_failure_leaves_the_op_retryable() {
    let h = FencedHarness::new().await;
    let distinct_id = format!("fenced-retry-{}", Uuid::now_v7());
    let person_id = h.ctx.create_person_via_stub(&distinct_id).await;

    h.leader
        .fail_next(Rpc::Fence, person_id, Status::unavailable("leader down"));
    let op_id = Uuid::now_v7();
    let err = h
        .execute(op_id, &[person_id])
        .await
        .expect_err("the fence failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));

    let row = h
        .execute(op_id, &[person_id])
        .await
        .expect("retry completes");
    assert_eq!(FencedHarness::outcome(&row).results[0].outcome, "deleted");
    assert_eq!(h.leader.death_documents().len(), 1);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_transient_release_failure_leaves_the_op_retryable() {
    let h = FencedHarness::new().await;
    let distinct_id = format!("fenced-release-retry-{}", Uuid::now_v7());
    let person_id = h.ctx.create_person_via_stub(&distinct_id).await;

    h.leader
        .fail_next(Rpc::Release, person_id, Status::unavailable("leader down"));
    let op_id = Uuid::now_v7();
    let err = h
        .execute(op_id, &[person_id])
        .await
        .expect_err("the release failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));

    // The op parked on unmapped with its sync-plane work done; the retry
    // re-releases and the duplicate-absorbing leader still produces exactly
    // one death document.
    let row = h
        .execute(op_id, &[person_id])
        .await
        .expect("retry completes");
    assert_eq!(FencedHarness::outcome(&row).results[0].outcome, "deleted");
    assert_eq!(h.leader.death_documents().len(), 1);
    assert!(h.leader.fence_for(person_id).is_none());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_op_sealed_by_a_pre_fence_build_completes_without_release_calls() {
    let h = FencedHarness::new().await;
    let distinct_id = format!("pre-fence-upgrade-{}", Uuid::now_v7());
    let person_id = h.ctx.create_person_via_stub(&distinct_id).await;

    // Recreate the state a pre-fence build leaves behind at a deploy
    // boundary: victims sealed with the margin folded into the version and
    // no created_at in the sealed jsonb. The new build must finish the op
    // without inventing release calls for victims it never fenced.
    let op_id = Uuid::now_v7();
    h.engine
        .create_or_attach(
            &h.driver,
            op_id,
            h.ctx.team_id,
            &FencedHarness::request(&[person_id]),
        )
        .await
        .expect("create op");
    let row = h.step(op_id).await.expect("started -> marked");
    assert_eq!(row.step, "marked");
    sqlx::query(
        r#"
        UPDATE lifecycle_op_person
        SET status = 'sealed', sealed = jsonb_build_object('version', 100)
        WHERE op_id = $1 AND person_id = $2
        "#,
    )
    .bind(op_id)
    .bind(person_id)
    .execute(&h.ctx.pool)
    .await
    .expect("seal like a pre-fence build");
    sqlx::query("UPDATE lifecycle_op SET step = 'sealed' WHERE op_id = $1")
        .bind(op_id)
        .execute(&h.ctx.pool)
        .await
        .expect("advance like a pre-fence build");

    let row = h.step(op_id).await.expect("sealed -> unmapped");
    assert_eq!(row.step, "unmapped");
    let row = h.step(op_id).await.expect("unmapped -> completed");
    assert!(row.completed_at.is_some());
    assert_eq!(FencedHarness::outcome(&row).results[0].outcome, "deleted");
    assert!(
        h.leader.calls().is_empty(),
        "a margin-sealed op must not reach the leader"
    );
    let (is_deleted, version, _) = h.ctx.person_state(person_id).await;
    assert!(is_deleted);
    assert_eq!(version, 101, "the old margin stays folded into the version");

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_victim_destroyed_before_its_fence_settles_as_not_found() {
    let h = FencedHarness::new().await;
    let keep = h
        .ctx
        .create_person_via_stub(&format!("fenced-keep-{}", Uuid::now_v7()))
        .await;
    let gone = h
        .ctx
        .create_person_via_stub(&format!("fenced-gone-{}", Uuid::now_v7()))
        .await;

    let op_id = Uuid::now_v7();
    h.engine
        .create_or_attach(
            &h.driver,
            op_id,
            h.ctx.team_id,
            &FencedHarness::request(&[keep, gone]),
        )
        .await
        .expect("create op");
    let row = h.step(op_id).await.expect("started -> marked");
    assert_eq!(row.step, "marked");
    // Destroy one victim behind its mark — the anomaly the seal absorbs by
    // settling it as not_found instead of failing the whole op.
    sqlx::query("UPDATE posthog_person SET is_deleted = true WHERE team_id = $1 AND id = $2")
        .bind(h.ctx.team_id as i32)
        .bind(gone)
        .execute(&h.ctx.pool)
        .await
        .expect("tombstone the victim");

    let row = h.execute(op_id, &[keep, gone]).await.expect("op completes");
    let outcome = FencedHarness::outcome(&row);
    assert_eq!(
        outcome
            .results
            .iter()
            .map(|r| (r.person_id, r.outcome.as_str()))
            .collect::<Vec<_>>(),
        vec![(keep, "deleted"), (gone, "not_found")]
    );
    let docs = h.leader.death_documents();
    assert_eq!(docs.len(), 1, "only the live victim gets a death document");
    assert_eq!(docs[0].person_id, keep);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn full_flow_works_on_a_configured_person_table() {
    // Runs create, resolve, and the whole delete saga against
    // personhog_person_tmp — a leftover hardcoded posthog_person in any of
    // the interpolated queries would pass silently on the default table.
    let ctx = TestContext::new_with_tables(common::tmp_tables()).await;
    let service = ctx.lifecycle_service();
    let distinct_id = format!("tmp-table-{}", Uuid::now_v7());

    ctx.park_tmp_person_sequence().await;
    let person_id = ctx.create_person_via_stub(&distinct_id).await;

    let key = (ctx.team_id, distinct_id.clone());
    let resolved = ctx
        .storage
        .resolve_distinct_ids(std::slice::from_ref(&key))
        .await
        .expect("resolve succeeds");
    assert_eq!(resolved.get(&key).map(|p| p.id), Some(person_id));

    // Distinct id expansion must read the configured mapping table too.
    let mappings = ctx
        .storage
        .get_distinct_ids_for_persons(ctx.team_id, &[person_id], None)
        .await
        .expect("distinct id expansion succeeds");
    assert_eq!(
        mappings
            .iter()
            .map(|m| m.distinct_id.as_str())
            .collect::<Vec<_>>(),
        vec![distinct_id.as_str()]
    );

    // A cohort row whose person_id collides numerically belongs to the real
    // namespace; a delete on the validation set must not touch it.
    sqlx::query("INSERT INTO posthog_cohortpeople (cohort_id, person_id) VALUES (1, $1)")
        .bind(person_id)
        .execute(&ctx.pool)
        .await
        .expect("insert colliding cohort row");

    // The same collision for the other two interpolated tables: a real
    // person sharing the numeric id, its mapping row, and an override on
    // each mirror. The saga must tombstone/clear only the tmp rows.
    let real_distinct_id = format!("real-{distinct_id}");
    ctx.seed_real_namespace_collision(person_id, &real_distinct_id)
        .await;
    sqlx::query(
        r#"
        INSERT INTO personhog_featureflaghashkeyoverride_tmp
            (feature_flag_key, hash_key, person_id, team_id)
        VALUES ('flag', 'tmp-hash', $1, $2)
        "#,
    )
    .bind(person_id)
    .bind(ctx.team_id as i32)
    .execute(&ctx.pool)
    .await
    .expect("insert tmp override");

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

    let (is_deleted, version): (bool, i64) = sqlx::query_as(
        "SELECT is_deleted, version FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(person_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("tombstone row exists");
    assert!(is_deleted);
    // The fence sealed the stub's exact version (0), so the tombstone
    // lands at 1 — no margin.
    assert_eq!(version, 1);

    let resolved = ctx
        .storage
        .resolve_distinct_ids(std::slice::from_ref(&key))
        .await
        .expect("resolve after delete succeeds");
    assert!(resolved.is_empty(), "tombstoned person must not resolve");

    // The tmp mapping row tombstoned; the colliding real one untouched.
    let tmp_mapping_deleted: bool = sqlx::query_scalar(
        "SELECT is_deleted FROM personhog_persondistinctid_tmp WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(&distinct_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("tmp mapping row exists");
    assert!(
        tmp_mapping_deleted,
        "the configured mapping table must be tombstoned"
    );
    let real_mapping_deleted: bool = sqlx::query_scalar(
        "SELECT is_deleted FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(&real_distinct_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("real mapping row exists");
    assert!(
        !real_mapping_deleted,
        "a validation-set delete must not tombstone real-namespace mapping rows"
    );

    // The tmp override cleared; the real-namespace one survives.
    let tmp_overrides: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM personhog_featureflaghashkeyoverride_tmp WHERE team_id = $1 AND person_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(person_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("count tmp overrides");
    assert_eq!(
        tmp_overrides, 0,
        "the configured override table must be cleared"
    );
    let real_overrides: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2",
    )
    .bind(ctx.team_id as i32)
    .bind(person_id)
    .fetch_one(&ctx.pool)
    .await
    .expect("count real overrides");
    assert_eq!(
        real_overrides, 1,
        "a validation-set delete must not clear real-namespace overrides"
    );

    // The colliding real person row is untouched.
    let real_person_deleted: bool =
        sqlx::query_scalar("SELECT is_deleted FROM posthog_person WHERE team_id = $1 AND id = $2")
            .bind(ctx.team_id as i32)
            .bind(person_id)
            .fetch_one(&ctx.pool)
            .await
            .expect("real person row exists");
    assert!(
        !real_person_deleted,
        "a validation-set delete must not tombstone real-namespace persons"
    );

    let colliding_rows: i64 =
        sqlx::query_scalar("SELECT count(*) FROM posthog_cohortpeople WHERE person_id = $1")
            .bind(person_id)
            .fetch_one(&ctx.pool)
            .await
            .expect("count cohort rows");
    assert_eq!(
        colliding_rows, 1,
        "a validation-set delete must not clear real-namespace cohort rows"
    );
    sqlx::query("DELETE FROM posthog_cohortpeople WHERE person_id = $1")
        .bind(person_id)
        .execute(&ctx.pool)
        .await
        .expect("remove colliding cohort row");

    ctx.cleanup_real_namespace()
        .await
        .expect("cleanup real namespace");
    ctx.cleanup().await.expect("cleanup");
}
