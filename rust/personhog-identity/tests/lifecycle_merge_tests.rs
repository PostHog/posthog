//! End-to-end tests of the merge saga driver: the engine drives a
//! [`MergeDriver`] against real Postgres, with the leader surface faked
//! behind [`LifecycleLeader`]. The fake seals from the live person row —
//! exactly what the real leader's cache holds in a quiet system — and
//! records every call so tests can assert the fence/release protocol,
//! including the load-bearing ordering: a committed release must observe
//! the source's mark still live.

mod common;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use chrono::Utc;
use common::TestContext;
use serde_json::json;
use sqlx::postgres::PgPool;
use tonic::Status;
use uuid::Uuid;

use personhog_identity::leader::LifecycleLeader;
use personhog_identity::lifecycle::engine::{Engine, SagaError, STEP_ABORTED, STEP_COMPLETED};
use personhog_identity::lifecycle::merge::{
    MergeDriver, MergeOutcome, MergeRequest, MergeSourceEntry, OUTCOME_MERGED,
    OUTCOME_NOOP_SAME_PERSON, OUTCOME_SKIPPED_ALREADY_IDENTIFIED, OUTCOME_SKIPPED_CONFLICT,
    OUTCOME_SKIPPED_MOVE_LIMIT,
};
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonResponse, FoldPersonDocumentRequest, FoldPersonDocumentResponse,
    LifecycleOpType, Person, ReleaseFenceRequest, ReleaseFenceResponse, ReleaseOutcome,
};

#[derive(Debug, Clone, PartialEq)]
enum LeaderCall {
    Fence {
        person_id: i64,
        op_type: LifecycleOpType,
    },
    Fold {
        target_person_id: i64,
        snapshot_versions: Vec<i64>,
    },
    ReleaseCommitted {
        person_id: i64,
        sealed_version: i64,
        /// The source's `lifecycle_op_person.status` observed at release
        /// time — the real leader refuses to produce a death document
        /// unless this is a live mark, so the saga must release before it
        /// settles the row.
        mark_status_at_release: Option<String>,
    },
    ReleaseAborted {
        person_id: i64,
    },
}

/// A leader whose "cache" is the live Postgres row: seals return the row's
/// current state, folds compute the real fold semantics, releases record
/// what the mark table said at the moment of the call.
struct FakeLeader {
    pool: PgPool,
    calls: Mutex<Vec<LeaderCall>>,
    fail_next_fence: AtomicBool,
    fail_next_fold: AtomicBool,
    /// Sealed `is_identified` overrides per person: the leader's state can
    /// be ahead of Postgres, which is exactly what the seal-time re-check
    /// exists for.
    sealed_identified: Mutex<HashMap<i64, bool>>,
}

impl FakeLeader {
    fn new(pool: PgPool) -> Self {
        Self {
            pool,
            calls: Mutex::new(Vec::new()),
            fail_next_fence: AtomicBool::new(false),
            fail_next_fold: AtomicBool::new(false),
            sealed_identified: Mutex::new(HashMap::new()),
        }
    }

    fn calls(&self) -> Vec<LeaderCall> {
        self.calls.lock().unwrap().clone()
    }

    async fn live_person(&self, team_id: i64, person_id: i64) -> Option<Person> {
        let row: Option<(Uuid, i64, chrono::DateTime<Utc>, bool, serde_json::Value)> =
            sqlx::query_as(
                r#"
                SELECT uuid, COALESCE(version, 0), created_at, is_identified, properties
                FROM posthog_person
                WHERE team_id = $1 AND id = $2 AND is_deleted = false
                "#,
            )
            .bind(team_id as i32)
            .bind(person_id)
            .fetch_optional(&self.pool)
            .await
            .expect("person lookup");
        row.map(
            |(uuid, version, created_at, is_identified, properties)| Person {
                id: person_id,
                uuid: uuid.to_string(),
                team_id,
                properties: serde_json::to_vec(&properties).unwrap(),
                created_at: created_at.timestamp(),
                version,
                is_identified,
                ..Default::default()
            },
        )
    }
}

#[async_trait]
impl LifecycleLeader for FakeLeader {
    async fn fence_person(
        &self,
        request: FencePersonRequest,
    ) -> Result<FencePersonResponse, Status> {
        if self.fail_next_fence.swap(false, Ordering::SeqCst) {
            return Err(Status::unavailable("injected fence failure"));
        }
        let Some(mut person) = self.live_person(request.team_id, request.person_id).await else {
            return Err(Status::not_found("person is destroyed"));
        };
        if let Some(identified) = self
            .sealed_identified
            .lock()
            .unwrap()
            .get(&request.person_id)
        {
            person.is_identified = *identified;
        }
        self.calls.lock().unwrap().push(LeaderCall::Fence {
            person_id: request.person_id,
            op_type: request.op_type(),
        });
        Ok(FencePersonResponse {
            sealed: Some(person),
        })
    }

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status> {
        let call = match request.outcome() {
            ReleaseOutcome::Committed => {
                let mark_status_at_release: Option<String> = sqlx::query_scalar(
                    r#"
                    SELECT status FROM lifecycle_op_person
                    WHERE op_id = $1::uuid AND person_id = $2 AND status IN ('marked', 'sealed')
                    "#,
                )
                .bind(&request.op_id)
                .bind(request.person_id)
                .fetch_optional(&self.pool)
                .await
                .expect("mark lookup");
                LeaderCall::ReleaseCommitted {
                    person_id: request.person_id,
                    sealed_version: request.sealed_version.expect("committed carries the seal"),
                    mark_status_at_release,
                }
            }
            _ => LeaderCall::ReleaseAborted {
                person_id: request.person_id,
            },
        };
        self.calls.lock().unwrap().push(call);
        Ok(ReleaseFenceResponse {})
    }

    async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status> {
        if self.fail_next_fold.swap(false, Ordering::SeqCst) {
            return Err(Status::unavailable("injected fold failure"));
        }
        let Some(target) = self.live_person(request.team_id, request.person_id).await else {
            return Err(Status::not_found("person is destroyed"));
        };
        let mut folded: serde_json::Map<String, serde_json::Value> =
            serde_json::from_slice(&target.properties).unwrap();
        let mut created_at = target.created_at;
        let mut max_sealed = 0;
        let mut snapshot_versions = Vec::new();
        for snapshot in &request.sealed_snapshots {
            let properties: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&snapshot.properties).unwrap();
            for (key, value) in properties {
                folded.entry(key).or_insert(value);
            }
            created_at = created_at.min(snapshot.created_at);
            max_sealed = max_sealed.max(snapshot.version);
            snapshot_versions.push(snapshot.version);
        }
        if !request.event_set.is_empty() {
            let event_set: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&request.event_set).unwrap();
            for (key, value) in event_set {
                folded.insert(key, value);
            }
        }
        if !request.event_set_once.is_empty() {
            let event_set_once: serde_json::Map<String, serde_json::Value> =
                serde_json::from_slice(&request.event_set_once).unwrap();
            for (key, value) in event_set_once {
                folded.entry(key).or_insert(value);
            }
        }
        self.calls.lock().unwrap().push(LeaderCall::Fold {
            target_person_id: request.person_id,
            snapshot_versions,
        });
        Ok(FoldPersonDocumentResponse {
            person: Some(Person {
                properties: serde_json::to_vec(&folded).unwrap(),
                created_at,
                version: target.version.max(max_sealed) + 1,
                is_identified: true,
                ..target
            }),
        })
    }
}

struct MergeHarness {
    ctx: TestContext,
    engine: Engine,
    leader: Arc<FakeLeader>,
    driver: MergeDriver,
}

impl MergeHarness {
    async fn new() -> Self {
        let ctx = TestContext::new().await;
        let engine = ctx.engine();
        let leader = Arc::new(FakeLeader::new(ctx.pool.clone()));
        let driver = MergeDriver::new(leader.clone());
        Self {
            ctx,
            engine,
            leader,
            driver,
        }
    }

    async fn execute(
        &self,
        op_id: Uuid,
        request: &MergeRequest,
    ) -> Result<MergeOutcome, SagaError> {
        let frozen = serde_json::to_value(request).unwrap();
        let row = self
            .engine
            .execute(&self.driver, op_id, self.ctx.team_id, &frozen)
            .await?;
        Ok(serde_json::from_value(row.outcome.expect("terminal outcome")).unwrap())
    }

    /// Adds another distinct id mapping to an existing person.
    async fn add_distinct_id(&self, person_id: i64, distinct_id: &str) {
        sqlx::query(
            r#"
            INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version)
            VALUES ($1, $2, $3, 0)
            "#,
        )
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .bind(distinct_id)
        .execute(&self.ctx.pool)
        .await
        .expect("insert distinct id");
    }

    async fn set_person(&self, person_id: i64, properties: &str, version: i64, identified: bool) {
        sqlx::query(
            r#"
            UPDATE posthog_person
            SET properties = $3::jsonb, version = $4, is_identified = $5
            WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .bind(properties)
        .bind(version)
        .bind(identified)
        .execute(&self.ctx.pool)
        .await
        .expect("set person state");
    }

    /// A mark row held by a different (still-live) op.
    async fn foreign_mark(&self, person_id: i64) -> Uuid {
        let foreign_op = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request)
            VALUES ($1, 'delete', $2, 'marked', '{}'::jsonb)
            "#,
        )
        .bind(foreign_op)
        .bind(self.ctx.team_id as i32)
        .execute(&self.ctx.pool)
        .await
        .expect("insert foreign op");
        sqlx::query(
            r#"
            INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status)
            VALUES ($1, $2, $3, $4, 'victim', 'marked')
            "#,
        )
        .bind(foreign_op)
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .bind(Uuid::new_v4())
        .execute(&self.ctx.pool)
        .await
        .expect("insert foreign mark");
        foreign_op
    }

    /// (is_deleted, version, properties) of a person row.
    async fn person_state(&self, person_id: i64) -> (bool, i64, serde_json::Value) {
        sqlx::query_as(
            r#"
            SELECT is_deleted, COALESCE(version, 0), properties
            FROM posthog_person WHERE team_id = $1 AND id = $2
            "#,
        )
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("person row exists")
    }

    /// (person_id, is_deleted, version) of a distinct id row.
    async fn pdi_state(&self, distinct_id: &str) -> (i64, bool, i64) {
        sqlx::query_as(
            r#"
            SELECT person_id, is_deleted, COALESCE(version, 0)
            FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2
            "#,
        )
        .bind(self.ctx.team_id as i32)
        .bind(distinct_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("distinct id row exists")
    }

    async fn op_person_status(&self, op_id: Uuid, person_id: i64) -> String {
        sqlx::query_scalar(
            "SELECT status FROM lifecycle_op_person WHERE op_id = $1 AND person_id = $2",
        )
        .bind(op_id)
        .bind(person_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("op person row exists")
    }
}

fn merge_request(target: &str, sources: &[&str]) -> MergeRequest {
    MergeRequest {
        target_distinct_id: target.to_string(),
        sources: sources
            .iter()
            .map(|did| MergeSourceEntry {
                distinct_id: did.to_string(),
                event_uuid: Uuid::now_v7().to_string(),
            })
            .collect(),
        event_set: json!({}),
        event_set_once: json!({}),
        allow_identified_sources: false,
        move_limit: None,
    }
}

fn result_map(outcome: &MergeOutcome) -> HashMap<String, String> {
    outcome
        .results
        .iter()
        .map(|r| (r.distinct_id.clone(), r.outcome.clone()))
        .collect()
}

#[tokio::test]
async fn a_merge_folds_repoints_tombstones_and_records_the_outcome() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("merge-target").await;
    let source = h.ctx.insert_person_with_distinct_id("merge-source").await;
    h.add_distinct_id(source, "merge-source-alias").await;
    h.set_person(target, r#"{"a": "target"}"#, 3, false).await;
    h.set_person(source, r#"{"a": "source", "b": "source"}"#, 7, false)
        .await;
    // Satellite rows: the source's move, and a target-side hash-key
    // override that must win the dedupe.
    sqlx::query("INSERT INTO posthog_cohortpeople (cohort_id, person_id) VALUES (1, $1)")
        .bind(source)
        .execute(&h.ctx.pool)
        .await
        .unwrap();
    for (person, hash) in [(target, "target-hash"), (source, "source-hash")] {
        sqlx::query(
            r#"
            INSERT INTO posthog_featureflaghashkeyoverride
                (feature_flag_key, hash_key, person_id, team_id)
            VALUES ('flag', $2, $1, $3)
            "#,
        )
        .bind(person)
        .bind(hash)
        .bind(h.ctx.team_id as i32)
        .execute(&h.ctx.pool)
        .await
        .unwrap();
    }

    let op_id = Uuid::now_v7();
    let mut request = merge_request("merge-target", &["merge-source"]);
    request.event_set = json!({"c": "event"});
    let outcome = h.execute(op_id, &request).await.expect("merge completes");

    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("merge-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    let survivor = outcome
        .survivor
        .expect("committed merges carry the survivor");
    assert_eq!(
        survivor["properties"],
        json!({"a": "target", "b": "source", "c": "event"}),
        "target wins, snapshot fills, event overrides"
    );
    assert_eq!(survivor["version"], json!(8), "max(target 3, sealed 7) + 1");
    assert_eq!(survivor["is_identified"], json!(true));

    // Both of the source's distinct ids now point at the target, above
    // their previous versions.
    for did in ["merge-source", "merge-source-alias"] {
        let (person_id, is_deleted, version) = h.pdi_state(did).await;
        assert_eq!(person_id, target, "{did} repointed");
        assert!(!is_deleted);
        assert_eq!(version, 1);
    }
    // The source person is a scrubbed tombstone at exactly sealed + 1; the
    // target's own row is untouched (the writer projects the fold).
    let (is_deleted, version, properties) = h.person_state(source).await;
    assert!(is_deleted);
    assert_eq!(version, 8);
    assert_eq!(properties, json!({}));
    let (target_deleted, target_version, _) = h.person_state(target).await;
    assert!(!target_deleted);
    assert_eq!(target_version, 3, "sync plane never writes the target");

    // Satellite rows moved; the target's own hash-key override won.
    let moved_cohort: i64 =
        sqlx::query_scalar("SELECT count(*) FROM posthog_cohortpeople WHERE person_id = $1")
            .bind(target)
            .fetch_one(&h.ctx.pool)
            .await
            .unwrap();
    assert_eq!(moved_cohort, 1);
    let hash: String = sqlx::query_scalar(
        r#"
        SELECT hash_key FROM posthog_featureflaghashkeyoverride
        WHERE team_id = $1 AND person_id = $2 AND feature_flag_key = 'flag'
        "#,
    )
    .bind(h.ctx.team_id as i32)
    .bind(target)
    .fetch_one(&h.ctx.pool)
    .await
    .unwrap();
    assert_eq!(hash, "target-hash");

    // The leader protocol ran in order, and the committed release saw the
    // source's mark still live — the invariant the leader's death-document
    // verification depends on.
    assert_eq!(
        h.leader.calls(),
        vec![
            LeaderCall::Fence {
                person_id: source,
                op_type: LifecycleOpType::Merge,
            },
            LeaderCall::Fold {
                target_person_id: target,
                snapshot_versions: vec![7],
            },
            LeaderCall::ReleaseCommitted {
                person_id: source,
                sealed_version: 7,
                mark_status_at_release: Some("sealed".to_string()),
            },
        ]
    );

    // Marks settled: the target's cleared, the source's deleted.
    assert_eq!(h.op_person_status(op_id, target).await, "cleared");
    assert_eq!(h.op_person_status(op_id, source).await, "deleted");

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn claim_classification_settles_each_source_without_touching_it() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("cls-target").await;
    h.add_distinct_id(target, "cls-target-alias").await;
    let identified = h.ctx.insert_person_with_distinct_id("cls-identified").await;
    h.set_person(identified, "{}", 0, true).await;
    let oversized = h.ctx.insert_person_with_distinct_id("cls-oversized").await;
    h.add_distinct_id(oversized, "cls-oversized-2").await;
    h.add_distinct_id(oversized, "cls-oversized-3").await;
    let mergeable = h.ctx.insert_person_with_distinct_id("cls-mergeable").await;

    let mut request = merge_request(
        "cls-target",
        &[
            "cls-target-alias", // resolves to the target person
            "cls-missing",      // resolves to nothing
            "cls-identified",
            "cls-oversized",
            "cls-mergeable",
        ],
    );
    request.move_limit = Some(2);
    let outcome = h
        .execute(Uuid::now_v7(), &request)
        .await
        .expect("merge completes");

    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([
            (
                "cls-target-alias".to_string(),
                OUTCOME_NOOP_SAME_PERSON.to_string()
            ),
            (
                "cls-missing".to_string(),
                OUTCOME_SKIPPED_CONFLICT.to_string()
            ),
            (
                "cls-identified".to_string(),
                OUTCOME_SKIPPED_ALREADY_IDENTIFIED.to_string()
            ),
            (
                "cls-oversized".to_string(),
                OUTCOME_SKIPPED_MOVE_LIMIT.to_string()
            ),
            ("cls-mergeable".to_string(), OUTCOME_MERGED.to_string()),
        ])
    );

    // Skipped persons are untouched — live, ids where they were.
    for (person, did) in [(identified, "cls-identified"), (oversized, "cls-oversized")] {
        let (is_deleted, _, _) = h.person_state(person).await;
        assert!(!is_deleted);
        assert_eq!(h.pdi_state(did).await.0, person);
    }
    let (mergeable_deleted, _, _) = h.person_state(mergeable).await;
    assert!(mergeable_deleted);
    assert_eq!(h.pdi_state("cls-mergeable").await.0, target);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_target_held_by_another_op_aborts_before_mutating_anything() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("held-target").await;
    let source = h.ctx.insert_person_with_distinct_id("held-source").await;
    let foreign_op = h.foreign_mark(target).await;

    let op_id = Uuid::now_v7();
    let outcome = h
        .execute(op_id, &merge_request("held-target", &["held-source"]))
        .await
        .expect("op reaches a terminal step");

    assert!(outcome.aborted);
    assert!(outcome.survivor.is_none());
    assert_eq!(
        result_map(&outcome),
        HashMap::from([(
            "held-source".to_string(),
            OUTCOME_SKIPPED_CONFLICT.to_string()
        )])
    );
    let (step, _) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, STEP_ABORTED);

    // The world is unchanged: both persons live, ids in place, the foreign
    // op's mark untouched, no leader call ever made.
    for (person, did) in [(target, "held-target"), (source, "held-source")] {
        let (is_deleted, _, _) = h.person_state(person).await;
        assert!(!is_deleted);
        assert_eq!(h.pdi_state(did).await.0, person);
    }
    assert_eq!(h.op_person_status(foreign_op, target).await, "marked");
    assert!(h.leader.calls().is_empty());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_source_held_by_another_op_is_skipped_while_the_rest_merge() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("part-target").await;
    let held = h.ctx.insert_person_with_distinct_id("part-held").await;
    let free = h.ctx.insert_person_with_distinct_id("part-free").await;
    h.foreign_mark(held).await;

    let outcome = h
        .execute(
            Uuid::now_v7(),
            &merge_request("part-target", &["part-held", "part-free"]),
        )
        .await
        .expect("merge completes");

    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([
            (
                "part-held".to_string(),
                OUTCOME_SKIPPED_CONFLICT.to_string()
            ),
            ("part-free".to_string(), OUTCOME_MERGED.to_string()),
        ])
    );
    let (held_deleted, _, _) = h.person_state(held).await;
    assert!(!held_deleted);
    let (free_deleted, _, _) = h.person_state(free).await;
    assert!(free_deleted);
    assert_eq!(h.pdi_state("part-held").await.0, held);
    assert_eq!(h.pdi_state("part-free").await.0, target);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_leader_failure_is_retried_from_the_saved_step() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("retry-target").await;
    let source = h.ctx.insert_person_with_distinct_id("retry-source").await;
    h.set_person(source, r#"{"k": "v"}"#, 2, false).await;

    let op_id = Uuid::now_v7();
    let request = merge_request("retry-target", &["retry-source"]);

    h.leader.fail_next_fence.store(true, Ordering::SeqCst);
    let err = h
        .execute(op_id, &request)
        .await
        .expect_err("the injected fence failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, "claimed", "the claim committed; the seal did not");
    assert!(!completed);
    // The source stays claimed across the failure: the mark is the op's
    // durable hold on it.
    assert_eq!(h.op_person_status(op_id, source).await, "marked");

    let outcome = h
        .execute(op_id, &request)
        .await
        .expect("the retry drives the op home");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("retry-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, STEP_COMPLETED);
    assert!(completed);
    assert_eq!(h.pdi_state("retry-source").await.0, target);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_identified_source_detected_at_seal_time_drops_with_a_released_fence() {
    let h = MergeHarness::new().await;
    let target = h.ctx.insert_person_with_distinct_id("seal-target").await;
    let source = h.ctx.insert_person_with_distinct_id("seal-source").await;
    // Postgres still says unidentified — only the leader's sealed state
    // carries the flip. The claim's cheap pre-filter must not catch it;
    // the seal's authoritative re-check must.
    h.leader
        .sealed_identified
        .lock()
        .unwrap()
        .insert(source, true);

    let op_id = Uuid::now_v7();
    let outcome = h
        .execute(op_id, &merge_request("seal-target", &["seal-source"]))
        .await
        .expect("op reaches a terminal step");

    assert!(
        outcome.aborted,
        "the only source dropped, so the op aborted"
    );
    assert_eq!(
        result_map(&outcome),
        HashMap::from([(
            "seal-source".to_string(),
            OUTCOME_SKIPPED_ALREADY_IDENTIFIED.to_string()
        )])
    );
    // The fence was installed, then released without a death document; the
    // source lives on, unmerged.
    let calls = h.leader.calls();
    assert!(calls.contains(&LeaderCall::Fence {
        person_id: source,
        op_type: LifecycleOpType::Merge,
    }));
    assert!(calls
        .iter()
        .any(|c| matches!(c, LeaderCall::ReleaseAborted { person_id } if *person_id == source)));
    assert!(!calls
        .iter()
        .any(|c| matches!(c, LeaderCall::ReleaseCommitted { .. })));
    let (is_deleted, _, _) = h.person_state(source).await;
    assert!(!is_deleted);
    let (target_deleted, _, _) = h.person_state(target).await;
    assert!(!target_deleted);
    assert_eq!(h.pdi_state("seal-source").await.0, source);

    h.ctx.cleanup().await.expect("cleanup");
}

async fn op_row_state(pool: &PgPool, op_id: Uuid) -> (String, bool) {
    let row: (String, Option<chrono::DateTime<Utc>>) =
        sqlx::query_as("SELECT step, completed_at FROM lifecycle_op WHERE op_id = $1")
            .bind(op_id)
            .fetch_one(pool)
            .await
            .expect("op row exists");
    (row.0, row.1.is_some())
}
