//! End-to-end tests of the merge saga driver: the engine drives a
//! [`MergeDriver`] against real Postgres, with the leader surface
//! simulated behind [`LifecycleLeader`] by [`SimLeader`] (see
//! `common/sim_leader.rs`), which enforces the leader's admission rules —
//! fenced writes reject, a committed release needs a live mark, duplicate
//! releases absorb — so protocol violations fail tests instead of merely
//! being recorded. The walkthrough tests step the saga one transition at
//! a time via `Engine::step_once` and assert, at every state, what other
//! actors in the system can and cannot see.

mod common;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono::Utc;
use common::sim_leader::{
    LeaderCall, Rpc, SimLeader, FENCED_CREATOR_METADATA_KEY, FENCED_METADATA_KEY,
};
use common::TestContext;
use personhog_common::grpc::semantic_refusal;
use personhog_common::persons::person_uuid;
use serde_json::json;
use sqlx::postgres::PgPool;
use sqlx::Row;
use tonic::{Code, Status};
use uuid::Uuid;

use personhog_identity::lifecycle::engine::{
    Engine, OpDriver, OpRow, SagaError, STEP_ABORTED, STEP_COMPLETED,
};
use personhog_identity::lifecycle::merge::{
    MergeDriver, MergeOutcome, MergeRequest, MergeSourceEntry, OUTCOME_MERGED,
    OUTCOME_NOOP_SAME_PERSON, OUTCOME_SKIPPED_ALREADY_IDENTIFIED, OUTCOME_SKIPPED_CONFLICT,
    OUTCOME_SKIPPED_MOVE_LIMIT,
};
use personhog_proto::personhog::types::v1::LifecycleOpType;

struct MergeHarness {
    ctx: TestContext,
    engine: Engine,
    leader: Arc<SimLeader>,
    driver: MergeDriver,
}

impl MergeHarness {
    async fn new() -> Self {
        Self::new_with_tables(common::default_tables()).await
    }

    async fn new_with_tables(tables: personhog_identity::config::IdentityTables) -> Self {
        let ctx = TestContext::new_with_tables(tables).await;
        let engine = ctx.engine();
        let leader = Arc::new(SimLeader::new(ctx.pool.clone(), ctx.tables.person.clone()));
        let driver = MergeDriver::new(leader.clone(), ctx.tables.clone());
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

    /// Create (or attach to) the op without driving it — the walkthrough
    /// entry point, paired with [`step`].
    async fn create(&self, op_id: Uuid, request: &MergeRequest) -> OpRow {
        let frozen = serde_json::to_value(request).unwrap();
        self.engine
            .create_or_attach(&self.driver, op_id, self.ctx.team_id, &frozen)
            .await
            .expect("create or attach op")
    }

    /// Run exactly one saga step and return the reloaded row.
    async fn step(&self, op_id: Uuid) -> Result<OpRow, SagaError> {
        self.engine
            .step_once(&self.driver, op_id, self.ctx.team_id)
            .await
    }

    /// Adds another distinct id mapping to an existing person.
    async fn add_distinct_id(&self, person_id: i64, distinct_id: &str) {
        sqlx::query(&format!(
            r#"
            INSERT INTO {} (team_id, person_id, distinct_id, version)
            VALUES ($1, $2, $3, 0)
            "#,
            self.ctx.tables.person_distinct_id
        ))
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .bind(distinct_id)
        .execute(&self.ctx.pool)
        .await
        .expect("insert distinct id");
    }

    async fn set_person(&self, person_id: i64, properties: &str, version: i64, identified: bool) {
        sqlx::query(&format!(
            r#"
            UPDATE {}
            SET properties = $3::jsonb, version = $4, is_identified = $5
            WHERE team_id = $1 AND id = $2
            "#,
            self.ctx.tables.person
        ))
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
        sqlx::query_as(&format!(
            r#"
            SELECT is_deleted, COALESCE(version, 0), properties
            FROM {} WHERE team_id = $1 AND id = $2
            "#,
            self.ctx.tables.person
        ))
        .bind(self.ctx.team_id as i32)
        .bind(person_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("person row exists")
    }

    /// (person_id, is_deleted, version) of a distinct id row.
    async fn pdi_state(&self, distinct_id: &str) -> (i64, bool, i64) {
        sqlx::query_as(&format!(
            r#"
            SELECT person_id, is_deleted, COALESCE(version, 0)
            FROM {} WHERE team_id = $1 AND distinct_id = $2
            "#,
            self.ctx.tables.person_distinct_id
        ))
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

    /// The `sealed` payload of an op's per-person row (the fence snapshot
    /// for sources, the folded survivor for the target).
    async fn op_person_sealed(&self, op_id: Uuid, person_id: i64) -> Option<serde_json::Value> {
        sqlx::query_scalar(
            "SELECT sealed FROM lifecycle_op_person WHERE op_id = $1 AND person_id = $2",
        )
        .bind(op_id)
        .bind(person_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("op person row exists")
    }

    /// The `moved` payload of an op's per-person row (the repointed
    /// mappings for sources, the claim record for the target).
    async fn op_person_moved(&self, op_id: Uuid, person_id: i64) -> Option<serde_json::Value> {
        sqlx::query_scalar(
            "SELECT moved FROM lifecycle_op_person WHERE op_id = $1 AND person_id = $2",
        )
        .bind(op_id)
        .bind(person_id)
        .fetch_one(&self.ctx.pool)
        .await
        .expect("op person row exists")
    }

    fn assert_write_fenced(&self, err: Status, op_id: Uuid) {
        assert_eq!(err.code(), Code::FailedPrecondition);
        assert!(
            err.message().contains("PERSON_MERGING"),
            "expected the typed merge rejection, got: {}",
            err.message()
        );
        assert_eq!(
            err.metadata().get(FENCED_METADATA_KEY).unwrap(),
            "merge",
            "the x-person-fenced metadata carries the op type"
        );
        assert!(err.message().contains(&op_id.to_string()));
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
        move_limit: 1_000,
        creator_event_uuid: String::new(),
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

    // The source was seen after the target: the fold must carry the max.
    h.leader.set_last_seen(target, 1_000);
    h.leader.set_last_seen(source, 2_000);

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
    // verification depends on (the sim also enforces it).
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
                // The source's later last_seen_at survived the frozen
                // snapshot round-trip and won the max-merge.
                folded_last_seen_at: Some(2_000),
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

/// The state-machine walkthrough: one `step_once` per transition, with
/// the full invariant set asserted in every state — what is persisted,
/// which fences and marks are held, and what other actors (ordinary
/// writes, rival lifecycle ops) are allowed to do.
#[tokio::test]
async fn a_walkthrough_asserts_every_state_and_shields_it_from_other_actors() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let target = h.ctx.insert_person_with_distinct_id("walk-target").await;
    let source = h.ctx.insert_person_with_distinct_id("walk-source").await;
    h.add_distinct_id(source, "walk-source-alias").await;
    h.set_person(target, r#"{"a": "target"}"#, 3, false).await;
    h.set_person(source, r#"{"a": "source", "b": "source"}"#, 7, false)
        .await;

    let op_id = Uuid::now_v7();
    let creator = Uuid::now_v7();
    let mut request = merge_request("walk-target", &["walk-source"]);
    request.creator_event_uuid = creator.to_string();

    // State: started. Nothing claimed, nothing fenced, everyone writable.
    let row = h.create(op_id, &request).await;
    assert_eq!(row.step, "started");
    assert!(row.completed_at.is_none());
    assert!(h.leader.fence_for(source).is_none());
    h.leader
        .admit_write(team, source)
        .await
        .expect("source writable before the claim");

    // started → claimed: marks exist, but fences do not yet — the claim's
    // shield is the mark index, which blocks rival lifecycle ops.
    let row = h.step(op_id).await.expect("claim step");
    assert_eq!(row.step, "claimed");
    assert_eq!(h.op_person_status(op_id, target).await, "marked");
    assert_eq!(h.op_person_status(op_id, source).await, "marked");
    assert!(
        h.leader.fence_for(source).is_none(),
        "fences are installed at seal, not claim"
    );
    h.leader
        .admit_write(team, source)
        .await
        .expect("ordinary writes still flow between claim and seal");
    let rival = h
        .execute(
            Uuid::now_v7(),
            &merge_request("walk-source", &["walk-target"]),
        )
        .await
        .expect("rival op reaches a terminal step");
    assert!(
        rival.aborted,
        "the mark shields claimed persons from rival ops"
    );
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, "claimed", "the rival left our op untouched");
    assert!(!completed);
    assert_eq!(h.op_person_status(op_id, source).await, "marked");

    // claimed → sources_sealed: the fence goes up, the snapshot freezes,
    // and other actors' writes to the source start bouncing with the
    // typed rejection. The target is never fenced.
    let row = h.step(op_id).await.expect("seal step");
    assert_eq!(row.step, "sources_sealed");
    assert_eq!(h.op_person_status(op_id, source).await, "sealed");
    let fence = h.leader.fence_for(source).expect("fence installed");
    assert_eq!(fence.op_id, op_id);
    assert_eq!(fence.op_type, LifecycleOpType::Merge);
    assert_eq!(
        fence.creator_event_uuid,
        Some(creator),
        "the seal carries the frozen request's creator onto the fence"
    );
    let err = h.leader.admit_write(team, source).await.unwrap_err();
    assert_eq!(
        err.metadata().get(FENCED_CREATOR_METADATA_KEY).unwrap(),
        creator.to_string().as_str(),
        "the rejection names the creator for the event's own caller"
    );
    h.assert_write_fenced(err, op_id);
    h.leader
        .admit_write(team, target)
        .await
        .expect("the merge target is never fenced");
    let sealed = h
        .op_person_sealed(op_id, source)
        .await
        .expect("seal snapshot persisted");
    assert_eq!(sealed["version"], json!(7));
    assert_eq!(sealed["is_identified"], json!(false));
    assert_eq!(sealed["properties"], json!({"a": "source", "b": "source"}));

    // sources_sealed → document_folded: the survivor document persists on
    // the target row; nothing in Postgres has been destroyed yet, and the
    // source stays shielded.
    let row = h.step(op_id).await.expect("fold step");
    assert_eq!(row.step, "document_folded");
    let survivor = h
        .op_person_sealed(op_id, target)
        .await
        .expect("survivor persisted on the target row");
    assert_eq!(
        survivor["properties"],
        json!({"a": "target", "b": "source"})
    );
    assert_eq!(survivor["version"], json!(8), "max(target 3, sealed 7) + 1");
    let (source_deleted, source_version, _) = h.person_state(source).await;
    assert!(!source_deleted, "the flip has not run yet");
    assert_eq!(source_version, 7);
    assert!(h.leader.fence_for(source).is_some());
    let err = h.leader.admit_write(team, source).await.unwrap_err();
    h.assert_write_fenced(err, op_id);

    // document_folded → flipped: Postgres is destroyed and repointed, but
    // the fence is STILL held — the half-dead source is never exposed as
    // writable, and no death document exists yet.
    let row = h.step(op_id).await.expect("flip step");
    assert_eq!(row.step, "flipped");
    for did in ["walk-source", "walk-source-alias"] {
        let (person_id, is_deleted, version) = h.pdi_state(did).await;
        assert_eq!(person_id, target, "{did} repointed");
        assert!(!is_deleted);
        assert_eq!(version, 1);
    }
    let (source_deleted, source_version, source_properties) = h.person_state(source).await;
    assert!(source_deleted, "the source is a scrubbed tombstone");
    assert_eq!(source_version, 8, "sealed 7 + 1");
    assert_eq!(source_properties, json!({}));
    let moved = h
        .op_person_moved(op_id, source)
        .await
        .expect("the repointed mappings are recorded on the source row");
    let moved_dids: HashSet<String> = moved
        .as_array()
        .expect("moved is an array")
        .iter()
        .map(|entry| {
            assert_eq!(entry["version"], json!(1));
            entry["distinct_id"].as_str().unwrap().to_string()
        })
        .collect();
    assert_eq!(
        moved_dids,
        HashSet::from(["walk-source".to_string(), "walk-source-alias".to_string()])
    );
    assert_eq!(
        h.op_person_status(op_id, target).await,
        "cleared",
        "the target is claimable again from here"
    );
    assert_eq!(
        h.op_person_status(op_id, source).await,
        "sealed",
        "the source mark is the fence's durable record until release"
    );
    assert!(
        h.leader.fence_for(source).is_some(),
        "fence held across the flip"
    );
    let err = h.leader.admit_write(team, source).await.unwrap_err();
    h.assert_write_fenced(err, op_id);
    assert!(h.leader.death_documents().is_empty());

    // flipped → completed: the death document is produced, the fence
    // released, the mark settled, and the outcome recorded. Only now does
    // the source answer not-found instead of fenced.
    let row = h.step(op_id).await.expect("complete step");
    assert_eq!(row.step, STEP_COMPLETED);
    assert!(row.completed_at.is_some());
    let outcome: MergeOutcome = serde_json::from_value(row.outcome.clone().unwrap()).unwrap();
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("walk-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    let deaths = h.leader.death_documents();
    assert_eq!(deaths.len(), 1);
    assert_eq!(deaths[0].person_id, source);
    assert_eq!(deaths[0].version, 8, "death document at sealed 7 + 1");
    assert!(deaths[0].created_at > 0);
    assert!(h.leader.fence_for(source).is_none());
    let err = h.leader.admit_write(team, source).await.unwrap_err();
    assert_eq!(err.code(), Code::NotFound);
    h.leader
        .admit_write(team, target)
        .await
        .expect("the merged person takes writes again");
    assert_eq!(h.op_person_status(op_id, source).await, "deleted");

    // A step on a terminal op is a no-op returning the recorded row.
    let again = h.step(op_id).await.expect("terminal step is a no-op");
    assert_eq!(again.step, STEP_COMPLETED);
    assert_eq!(again.outcome, row.outcome);

    h.ctx.cleanup().await.expect("cleanup");
}

/// A fence failure for one of two sources leaves the op re-drivable:
/// the already-installed fence stands (the source stays shielded), the
/// retry re-seals it idempotently, and the fold consumes the snapshots
/// in request order — first source wins contested keys.
#[tokio::test]
async fn a_partially_failed_seal_re_seals_and_sources_fold_in_request_order() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let _target = h.ctx.insert_person_with_distinct_id("prec-target").await;
    let s1 = h.ctx.insert_person_with_distinct_id("prec-s1").await;
    let s2 = h.ctx.insert_person_with_distinct_id("prec-s2").await;
    h.set_person(s1, r#"{"p": "s1", "q": "s1"}"#, 5, false)
        .await;
    h.set_person(s2, r#"{"p": "s2", "r": "s2"}"#, 9, false)
        .await;

    let op_id = Uuid::now_v7();
    let request = merge_request("prec-target", &["prec-s1", "prec-s2"]);
    h.leader.fail_next(
        Rpc::Fence,
        s2,
        Status::unavailable("injected fence failure"),
    );

    let row = h.create(op_id, &request).await;
    assert_eq!(row.step, "started");
    let row = h.step(op_id).await.expect("claim step");
    assert_eq!(row.step, "claimed");

    // The partial failure: s1's fence installed, s2's failed, the step
    // did not advance and no snapshot was persisted.
    let err = h.step(op_id).await.expect_err("injected failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, "claimed");
    assert!(!completed);
    assert_eq!(h.leader.fence_for(s1).expect("s1 fenced").op_id, op_id);
    assert!(h.leader.fence_for(s2).is_none());
    assert_eq!(h.op_person_status(op_id, s1).await, "marked");
    assert_eq!(h.op_person_status(op_id, s2).await, "marked");
    assert!(h.op_person_sealed(op_id, s1).await.is_none());
    // The installed fence stands through the retry window: s1 stays
    // shielded even while the op is between attempts.
    let fenced = h.leader.admit_write(team, s1).await.unwrap_err();
    h.assert_write_fenced(fenced, op_id);

    // The retry re-seals s1 (a same-op re-fence) and fences s2.
    let row = h.step(op_id).await.expect("seal retry");
    assert_eq!(row.step, "sources_sealed");
    assert_eq!(
        h.leader.fence_for(s1).expect("s1 still fenced").op_id,
        op_id
    );
    assert_eq!(h.leader.fence_for(s2).expect("s2 fenced").op_id, op_id);
    assert_eq!(
        h.op_person_sealed(op_id, s1).await.unwrap()["version"],
        json!(5)
    );
    assert_eq!(
        h.op_person_sealed(op_id, s2).await.unwrap()["version"],
        json!(9)
    );

    let outcome = h.execute(op_id, &request).await.expect("merge completes");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([
            ("prec-s1".to_string(), OUTCOME_MERGED.to_string()),
            ("prec-s2".to_string(), OUTCOME_MERGED.to_string()),
        ])
    );
    // Precedence: the target has nothing, s1 (ordinal 0) fills p and q,
    // s2 only gets keys s1 did not take.
    let survivor = outcome.survivor.expect("survivor");
    assert_eq!(
        survivor["properties"],
        json!({"p": "s1", "q": "s1", "r": "s2"}),
        "earlier sources take precedence in the fold"
    );
    let deaths = h.leader.death_documents();
    assert_eq!(deaths.len(), 2);
    assert_eq!(deaths[0].version, 6, "s1 death at sealed 5 + 1");
    assert_eq!(deaths[1].version, 10, "s2 death at sealed 9 + 1");

    h.ctx.cleanup().await.expect("cleanup");
}

/// A fold failure keeps every fence and mark in place — the sources stay
/// shielded while the op waits — and the retry completes from the saved
/// step without re-fencing.
#[tokio::test]
async fn a_fold_failure_holds_the_fences_until_the_retry_completes() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let target = h.ctx.insert_person_with_distinct_id("fold-target").await;
    let source = h.ctx.insert_person_with_distinct_id("fold-source").await;
    h.set_person(source, r#"{"k": "v"}"#, 2, false).await;

    let op_id = Uuid::now_v7();
    let request = merge_request("fold-target", &["fold-source"]);
    h.leader.fail_next(
        Rpc::Fold,
        target,
        Status::unavailable("injected fold failure"),
    );

    let err = h
        .execute(op_id, &request)
        .await
        .expect_err("injected fold failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(
        step, "sources_sealed",
        "the seal committed; the fold did not"
    );
    assert!(!completed);
    assert!(h.leader.fence_for(source).is_some());
    let fenced = h.leader.admit_write(team, source).await.unwrap_err();
    h.assert_write_fenced(fenced, op_id);
    assert!(h.op_person_sealed(op_id, target).await.is_none());
    assert!(h.leader.death_documents().is_empty());
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(!source_deleted);

    let outcome = h.execute(op_id, &request).await.expect("retry completes");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("fold-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    // The retry did not re-fence: one fence call for the whole op.
    let fence_calls = h
        .leader
        .calls()
        .iter()
        .filter(|c| matches!(c, LeaderCall::Fence { .. }))
        .count();
    assert_eq!(fence_calls, 1);
    assert!(h.leader.fence_for(source).is_none());
    assert_eq!(h.leader.death_documents().len(), 1);

    h.ctx.cleanup().await.expect("cleanup");
}

/// A release failure for one of two sources: the other's death document
/// is already produced, and the retry converges to exactly one death
/// document per source — the duplicate release is absorbed, never
/// re-produced — while the failed source stays fenced in between.
#[tokio::test]
async fn a_partial_release_failure_retries_to_one_death_document_each() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let target = h.ctx.insert_person_with_distinct_id("rel-target").await;
    let a = h.ctx.insert_person_with_distinct_id("rel-a").await;
    let b = h.ctx.insert_person_with_distinct_id("rel-b").await;
    h.set_person(a, r#"{"a": "a"}"#, 2, false).await;
    h.set_person(b, r#"{"b": "b"}"#, 4, false).await;

    let op_id = Uuid::now_v7();
    let request = merge_request("rel-target", &["rel-a", "rel-b"]);
    h.leader.fail_next(
        Rpc::Release,
        b,
        Status::unavailable("injected release failure"),
    );

    let err = h
        .execute(op_id, &request)
        .await
        .expect_err("injected release failure surfaces");
    assert!(matches!(err, SagaError::Leader(_)));
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, "flipped", "the flip committed; the release did not");
    assert!(!completed);
    // A's release landed: death produced, fence gone. B's did not: no
    // death, fence held, still shielded — even though its Postgres row is
    // already a tombstone, other actors see "fenced", never a half-dead
    // person.
    let deaths = h.leader.death_documents();
    assert_eq!(deaths.len(), 1, "only A's death document exists so far");
    assert_eq!(deaths[0].person_id, a);
    assert_eq!(deaths[0].version, 3, "A's death at sealed 2 + 1");
    assert!(h.leader.fence_for(a).is_none());
    assert!(h.leader.fence_for(b).is_some());
    let fenced = h.leader.admit_write(team, b).await.unwrap_err();
    h.assert_write_fenced(fenced, op_id);
    // Neither mark settled: the settle transaction runs only after every
    // release acks, because a settled mark would make the leader refuse
    // the retry's death document.
    assert_eq!(h.op_person_status(op_id, a).await, "sealed");
    assert_eq!(h.op_person_status(op_id, b).await, "sealed");
    assert!(
        !parked_state(&h.ctx.pool, op_id).await.0,
        "a transient failure leaves the op to the sweeper instead of parking it"
    );

    let outcome = h.execute(op_id, &request).await.expect("retry completes");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([
            ("rel-a".to_string(), OUTCOME_MERGED.to_string()),
            ("rel-b".to_string(), OUTCOME_MERGED.to_string()),
        ])
    );
    // Convergence, not duplication: A was released twice (the retry
    // re-releases every sealed source) but its death document was
    // absorbed, not re-produced.
    let a_releases = h
        .leader
        .calls()
        .iter()
        .filter(|c| matches!(c, LeaderCall::ReleaseCommitted { person_id, .. } if *person_id == a))
        .count();
    assert_eq!(a_releases, 2, "the retry re-released A");
    let deaths = h.leader.death_documents();
    assert_eq!(deaths.len(), 2, "exactly one death document per source");
    assert_eq!(
        deaths[0].version, 3,
        "A's death version unchanged by the retry"
    );
    assert_eq!(deaths[1].version, 5, "B's death at sealed 4 + 1");
    assert_eq!(h.op_person_status(op_id, a).await, "deleted");
    assert_eq!(h.op_person_status(op_id, b).await, "deleted");
    assert!(h.leader.fence_for(b).is_none());
    let err = h.leader.admit_write(team, a).await.unwrap_err();
    assert_eq!(err.code(), Code::NotFound);
    let (target_deleted, _, _) = h.person_state(target).await;
    assert!(!target_deleted);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_leader_refusal_at_release_parks_the_op_until_an_explicit_retry() {
    let h = MergeHarness::new().await;
    let source = h.ctx.insert_person_with_distinct_id("park-source").await;
    h.ctx.insert_person_with_distinct_id("park-target").await;
    h.set_person(source, r#"{"s": "s"}"#, 2, false).await;

    let op_id = Uuid::now_v7();
    let request = merge_request("park-target", &["park-source"]);
    // A definitive verification refusal in the real leader's
    // release-unverified shape, marker metadata included.
    h.leader.fail_next(
        Rpc::Release,
        source,
        semantic_refusal("injected verification refusal", "release-unverified"),
    );

    let err = h
        .execute(op_id, &request)
        .await
        .expect_err("the refusal surfaces");
    assert!(matches!(err, SagaError::LeaderRefused(_)));
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(
        step, "flipped",
        "the flip committed; the refused release did not"
    );
    assert!(!completed);
    let (parked, reason) = parked_state(&h.ctx.pool, op_id).await;
    assert!(parked, "a definitive refusal parks the op");
    assert_eq!(reason.as_deref(), Some("release-unverified"));

    // The refusal was scripted once, so it is gone: an explicit retry
    // with the same op_id un-parks, re-drives, and completes.
    let outcome = h.execute(op_id, &request).await.expect("retry completes");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("park-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    assert!(
        !parked_state(&h.ctx.pool, op_id).await.0,
        "claiming un-parks"
    );
    assert_eq!(h.leader.death_documents().len(), 1);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_stale_drivers_fold_refusal_defers_instead_of_unfencing_the_new_owners_sources() {
    let h = MergeHarness::new().await;
    let source = h.ctx.insert_person_with_distinct_id("stale-source").await;
    let target = h.ctx.insert_person_with_distinct_id("stale-target").await;

    let op_id = Uuid::now_v7();
    let request = merge_request("stale-target", &["stale-source"]);
    h.create(op_id, &request).await;
    h.step(op_id).await.expect("claim");
    let row = h.step(op_id).await.expect("seal");
    assert_eq!(row.step, "sources_sealed");

    // This drive's snapshot of the row, taken before another driver
    // steals its lapsed lease and flips the op.
    let stale = sqlx::query("SELECT request, created_at FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_one(&h.ctx.pool)
        .await
        .expect("row exists");
    let stale_row = OpRow {
        op_id,
        op_type: "merge".to_string(),
        team_id: h.ctx.team_id,
        step: "sources_sealed".to_string(),
        attempt: 1,
        request: stale.get("request"),
        outcome: None,
        created_at: stale.get("created_at"),
        completed_at: None,
        lease_live: false,
    };
    sqlx::query("UPDATE lifecycle_op SET step = 'flipped' WHERE op_id = $1")
        .bind(op_id)
        .execute(&h.ctx.pool)
        .await
        .expect("the stealer's flip commits");
    // The stealer's fold already verified; the stale driver's late fold
    // draws the real leader's fold-unverified shape.
    h.leader.fail_next(
        Rpc::Fold,
        target,
        semantic_refusal("injected fold refusal", "fold-unverified"),
    );

    // Aborting would release the sources' fences — the leader's aborted
    // release verifies nothing beyond the op id, which matches — between
    // the stealer's flip and its death documents, where an acked write
    // could land and be destroyed. The stale drive defers to the row.
    let err = h
        .driver
        .run_step(&h.ctx.pool, &stale_row)
        .await
        .expect_err("the stale drive defers rather than settling");
    assert!(matches!(err, SagaError::Busy));
    assert!(
        h.leader.fence_for(source).is_some(),
        "the fence stays held for the op's new owner"
    );
    assert_eq!(
        h.op_person_status(op_id, source).await,
        "sealed",
        "nothing was unwound"
    );
    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, "flipped", "the stealer's progress stands");
    assert!(!completed);
    assert!(h.leader.death_documents().is_empty());

    h.ctx.cleanup().await.expect("cleanup");
}

/// An abandoned merge op is driven through `sweep()`/`resume()` to a
/// merged outcome, while a parked op sitting next to it is skipped.
///
/// Isolation: this is the suite's single sweep call (see the engine
/// tests' header). Its one-hour lease keeps concurrent tests' fresh
/// NULL-lease ops outside the "never claimed" window, and the only
/// expired-lease rows in the suite are seeded here.
#[tokio::test]
async fn the_sweeper_drives_an_abandoned_merge_to_completion() {
    let h = MergeHarness::new().await;
    let source = h.ctx.insert_person_with_distinct_id("sweep-source").await;
    h.ctx.insert_person_with_distinct_id("sweep-target").await;

    // Created but never driven: the RPC died right after create-or-attach.
    let op_id = Uuid::now_v7();
    let request = merge_request("sweep-target", &["sweep-source"]);
    h.create(op_id, &request).await;
    sqlx::query("UPDATE lifecycle_op SET created_at = now() - interval '2 hours' WHERE op_id = $1")
        .bind(op_id)
        .execute(&h.ctx.pool)
        .await
        .expect("backdate the abandoned op");

    // A parked op that would otherwise be prime sweeper bait (expired
    // lease): a definitive leader refusal means automatic retry cannot
    // succeed, so the sweep must leave it alone.
    let parked_op_id = Uuid::now_v7();
    sqlx::query(
        r#"
        INSERT INTO lifecycle_op
            (op_id, op_type, team_id, step, request, lease_expires_at, parked_at, parked_reason)
        VALUES ($1, 'merge', $2, 'started', '{}'::jsonb, now() - interval '1 minute', now(), 'test-refusal')
        "#,
    )
    .bind(parked_op_id)
    .bind(h.ctx.team_id as i32)
    .execute(&h.ctx.pool)
    .await
    .expect("insert parked op");

    let sweep_engine = Engine::new(
        h.ctx.pool.clone(),
        personhog_identity::lifecycle::engine::EngineConfig {
            lease: std::time::Duration::from_secs(3600),
            execute_timeout: std::time::Duration::from_secs(10),
            poll_interval: std::time::Duration::from_millis(25),
            attempt_alert_threshold: 5,
        },
    );
    let resumed = sweep_engine.sweep(&[&h.driver]).await.expect("sweep runs");
    assert!(resumed >= 1, "the abandoned merge was resumed");

    let (step, completed) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, STEP_COMPLETED);
    assert!(completed);
    let outcome: MergeOutcome = serde_json::from_value(
        sqlx::query_scalar::<_, serde_json::Value>(
            "SELECT outcome FROM lifecycle_op WHERE op_id = $1",
        )
        .bind(op_id)
        .fetch_one(&h.ctx.pool)
        .await
        .expect("outcome recorded"),
    )
    .expect("outcome parses");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("sweep-source".to_string(), OUTCOME_MERGED.to_string())])
    );
    // Full-protocol effects, scoped to this test's persons because the
    // sweep's scan is global and may also touch rows other tests seeded.
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(source_deleted);
    assert!(!h.pdi_state("sweep-source").await.1);
    assert_eq!(
        h.leader
            .death_documents()
            .iter()
            .filter(|d| d.person_id == source)
            .count(),
        1
    );
    assert!(h.leader.fence_for(source).is_none());

    let (step, completed) = op_row_state(&h.ctx.pool, parked_op_id).await;
    assert_eq!(step, "started", "the sweep skipped the parked op");
    assert!(!completed);
    assert!(parked_state(&h.ctx.pool, parked_op_id).await.0);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_fold_without_a_live_target_mark_is_refused_and_the_op_aborts() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let source = h.ctx.insert_person_with_distinct_id("tmark-source").await;
    h.ctx.insert_person_with_distinct_id("tmark-target").await;

    let op_id = Uuid::now_v7();
    let request = merge_request("tmark-target", &["tmark-source"]);
    h.create(op_id, &request).await;
    let row = h.step(op_id).await.expect("claim");
    assert_eq!(row.step, "claimed");
    let row = h.step(op_id).await.expect("seal");
    assert_eq!(row.step, "sources_sealed");

    // The target mark vanishes under a live op (manual surgery, a settle
    // bug). Unlike a scripted status, this refusal comes from the sim's
    // own verification, the same check the real leader runs.
    sqlx::query(
        "UPDATE lifecycle_op_person SET status = 'cleared' WHERE op_id = $1 AND role = 'target'",
    )
    .bind(op_id)
    .execute(&h.ctx.pool)
    .await
    .expect("clear the target mark");

    let row = h
        .step(op_id)
        .await
        .expect("the refused fold aborts cleanly");
    assert_eq!(row.step, STEP_ABORTED);
    assert!(row.completed_at.is_some());
    // A slugged refusal is a definitive verdict, not contention: recorded
    // as a conflict, the caller would salt retries that abort identically
    // and then misfile the loss as a claim race. Its own verdict name
    // keeps it apart from a completed operation's indeterminate source.
    let outcome = row
        .outcome
        .as_ref()
        .expect("a terminal op records its outcome");
    assert_eq!(outcome["results"][0]["outcome"], "skipped_refused");
    assert!(!parked_state(&h.ctx.pool, op_id).await.0);
    assert!(
        h.leader.fence_for(source).is_none(),
        "the abort released the fence"
    );
    h.leader
        .admit_write(team, source)
        .await
        .expect("the source unfroze");
    assert!(h.leader.death_documents().is_empty());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_leader_refusal_at_fence_aborts_instead_of_parking() {
    let h = MergeHarness::new().await;
    let team = h.ctx.team_id;
    let source_a = h.ctx.insert_person_with_distinct_id("sabort-a").await;
    let source_b = h.ctx.insert_person_with_distinct_id("sabort-b").await;
    h.ctx.insert_person_with_distinct_id("sabort-target").await;

    let op_id = Uuid::now_v7();
    let request = merge_request("sabort-target", &["sabort-a", "sabort-b"]);
    // FencePerson has no refusals of its own (this one is scripted);
    // pins the policy that any pre-flip refusal backs the op out.
    h.leader.fail_next(
        Rpc::Fence,
        source_b,
        semantic_refusal("injected fence refusal", "test-refusal"),
    );

    let outcome = h
        .execute(op_id, &request)
        .await
        .expect("the refusal aborts the op cleanly");
    assert!(outcome.aborted);
    assert!(!parked_state(&h.ctx.pool, op_id).await.0);
    // The sibling's fence from the same fan-out was released by the
    // unwind; the refused source never had one.
    assert!(h.leader.fence_for(source_a).is_none());
    assert!(h.leader.fence_for(source_b).is_none());
    h.leader
        .admit_write(team, source_a)
        .await
        .expect("the fenced sibling unfroze");
    assert!(h.leader.death_documents().is_empty());

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
    request.move_limit = 2;
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

    h.leader.fail_next(
        Rpc::Fence,
        source,
        Status::unavailable("injected fence failure"),
    );
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
    h.leader.set_sealed_identified(source, true);

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
    // source lives on, unmerged and writable again.
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
    assert!(h.leader.death_documents().is_empty());
    assert!(h.leader.fence_for(source).is_none());
    h.leader
        .admit_write(h.ctx.team_id, source)
        .await
        .expect("the dropped source takes writes again");
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

async fn parked_state(pool: &PgPool, op_id: Uuid) -> (bool, Option<String>) {
    let row: (Option<chrono::DateTime<Utc>>, Option<String>) =
        sqlx::query_as("SELECT parked_at, parked_reason FROM lifecycle_op WHERE op_id = $1")
            .bind(op_id)
            .fetch_one(pool)
            .await
            .expect("op row exists");
    (row.0.is_some(), row.1)
}

#[tokio::test]
async fn merge_works_on_a_configured_person_table() {
    // Runs the whole merge saga against personhog_person_tmp — a leftover
    // hardcoded posthog_person in any of the interpolated queries would
    // pass silently on the default table.
    let h = MergeHarness::new_with_tables(common::tmp_tables()).await;
    h.ctx.park_tmp_person_sequence().await;
    let target = h
        .ctx
        .insert_person_with_distinct_id("tmp-merge-target")
        .await;
    let source = h
        .ctx
        .insert_person_with_distinct_id("tmp-merge-source")
        .await;

    // A cohort row whose person_id collides numerically belongs to the real
    // namespace; a merge on the validation set must not move it.
    sqlx::query("INSERT INTO posthog_cohortpeople (cohort_id, person_id) VALUES (1, $1)")
        .bind(source)
        .execute(&h.ctx.pool)
        .await
        .expect("insert colliding cohort row");

    // The same collision for the other two interpolated tables: a real
    // person sharing the source's numeric id, its mapping row, and an
    // override on each mirror. The flip must repoint/move only the tmp
    // rows.
    h.ctx
        .seed_real_namespace_collision(source, "tmp-merge-collide-real")
        .await;
    sqlx::query(
        r#"
        INSERT INTO personhog_featureflaghashkeyoverride_tmp
            (feature_flag_key, hash_key, person_id, team_id)
        VALUES ('flag', 'tmp-hash', $1, $2)
        "#,
    )
    .bind(source)
    .bind(h.ctx.team_id as i32)
    .execute(&h.ctx.pool)
    .await
    .expect("insert tmp override");

    let op_id = Uuid::now_v7();
    let outcome = h
        .execute(
            op_id,
            &merge_request("tmp-merge-target", &["tmp-merge-source"]),
        )
        .await
        .expect("merge completes");
    assert!(!outcome.aborted);
    assert_eq!(
        result_map(&outcome),
        HashMap::from([("tmp-merge-source".to_string(), OUTCOME_MERGED.to_string())])
    );

    // The source's distinct id repointed at the target on the configured
    // mapping table; the source person tombstoned on the configured person
    // table.
    let (person_id, is_deleted, version) = h.pdi_state("tmp-merge-source").await;
    assert_eq!(person_id, target);
    assert!(!is_deleted);
    assert_eq!(version, 1);
    let (source_deleted, _, properties) = h.person_state(source).await;
    assert!(source_deleted);
    assert_eq!(properties, json!({}));
    let (target_deleted, _, _) = h.person_state(target).await;
    assert!(!target_deleted);

    // The colliding real-namespace mapping still points at its own person.
    let (real_pid, real_deleted, real_version): (i64, bool, i64) = sqlx::query_as(
        r#"
        SELECT person_id, is_deleted, COALESCE(version, 0)
        FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2
        "#,
    )
    .bind(h.ctx.team_id as i32)
    .bind("tmp-merge-collide-real")
    .fetch_one(&h.ctx.pool)
    .await
    .expect("real mapping row exists");
    assert_eq!(
        real_pid, source,
        "a validation-set merge must not repoint real-namespace mapping rows"
    );
    assert!(!real_deleted);
    assert_eq!(real_version, 0);

    // The tmp override moved to the target; the real one stayed put.
    let tmp_override_owner: i64 = sqlx::query_scalar(
        r#"
        SELECT person_id FROM personhog_featureflaghashkeyoverride_tmp
        WHERE team_id = $1 AND feature_flag_key = 'flag'
        "#,
    )
    .bind(h.ctx.team_id as i32)
    .fetch_one(&h.ctx.pool)
    .await
    .expect("tmp override row exists");
    assert_eq!(
        tmp_override_owner, target,
        "the configured override table must move to the target"
    );
    let real_override_owner: i64 = sqlx::query_scalar(
        r#"
        SELECT person_id FROM posthog_featureflaghashkeyoverride
        WHERE team_id = $1 AND feature_flag_key = 'flag'
        "#,
    )
    .bind(h.ctx.team_id as i32)
    .fetch_one(&h.ctx.pool)
    .await
    .expect("real override row exists");
    assert_eq!(
        real_override_owner, source,
        "a validation-set merge must not move real-namespace overrides"
    );

    // The colliding real person row is untouched.
    let real_person_deleted: bool =
        sqlx::query_scalar("SELECT is_deleted FROM posthog_person WHERE team_id = $1 AND id = $2")
            .bind(h.ctx.team_id as i32)
            .bind(source)
            .fetch_one(&h.ctx.pool)
            .await
            .expect("real person row exists");
    assert!(
        !real_person_deleted,
        "a validation-set merge must not tombstone real-namespace persons"
    );

    let colliding_rows: i64 =
        sqlx::query_scalar("SELECT count(*) FROM posthog_cohortpeople WHERE person_id = $1")
            .bind(source)
            .fetch_one(&h.ctx.pool)
            .await
            .expect("count cohort rows");
    assert_eq!(
        colliding_rows, 1,
        "a validation-set merge must not move real-namespace cohort rows"
    );
    sqlx::query("DELETE FROM posthog_cohortpeople WHERE person_id = $1")
        .bind(source)
        .execute(&h.ctx.pool)
        .await
        .expect("remove colliding cohort row");

    h.ctx
        .cleanup_real_namespace()
        .await
        .expect("cleanup real namespace");
}

// ============================================================
// The MergePersons RPC: classification, inline settlement, and the
// attach-first retry contract
// ============================================================

use personhog_identity::lifecycle::merge::MergeOpExecutor;
use personhog_identity::service::merge::MergeEntrance;
use personhog_identity::service::validation::RequestLimits;
use personhog_identity::service::PersonHogIdentityService;
use personhog_identity::storage::IdentityStorage;
use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentity;
use personhog_proto::personhog::identity::v1::{
    MergePersonsRequest, MergePersonsResponse, MergeSource, MergeSourceOutcome,
};
use tonic::Request;

impl MergeHarness {
    fn service_with_storage(&self, storage: Arc<dyn IdentityStorage>) -> PersonHogIdentityService {
        let engine = Arc::new(self.ctx.engine());
        PersonHogIdentityService::new(
            storage.clone(),
            self.leader.clone(),
            RequestLimits {
                max_batch_size: 250,
                max_distinct_id_length: 400,
                max_extra_distinct_ids: 10,
            },
            MergeEntrance::new(
                storage,
                self.leader.clone(),
                MergeOpExecutor::new(
                    engine,
                    MergeDriver::new(self.leader.clone(), self.ctx.tables.clone()),
                ),
            ),
        )
    }

    fn service(&self) -> PersonHogIdentityService {
        let engine = Arc::new(self.ctx.engine());
        PersonHogIdentityService::new(
            self.ctx.storage.clone(),
            self.leader.clone(),
            RequestLimits {
                max_batch_size: 250,
                max_distinct_id_length: 400,
                max_extra_distinct_ids: 10,
            },
            MergeEntrance::new(
                self.ctx.storage.clone(),
                self.leader.clone(),
                MergeOpExecutor::new(
                    engine,
                    MergeDriver::new(self.leader.clone(), self.ctx.tables.clone()),
                ),
            ),
        )
    }
}

fn rpc_request(team_id: i64, target: &str, sources: &[&str], op_id: Uuid) -> MergePersonsRequest {
    MergePersonsRequest {
        team_id,
        target_distinct_id: target.to_string(),
        sources: sources
            .iter()
            .map(|did| MergeSource {
                source_distinct_id: did.to_string(),
                event_uuid: Uuid::now_v7().to_string(),
            })
            .collect(),
        event_set: Vec::new(),
        event_set_once: Vec::new(),
        op_id: op_id.to_string(),
        allow_identified_sources: false,
        move_limit: Some(1_000),
        created_at: 0,
        creator_event_uuid: String::new(),
    }
}

fn rpc_outcomes(response: &MergePersonsResponse) -> Vec<(String, MergeSourceOutcome)> {
    response
        .results
        .iter()
        .map(|r| (r.source_distinct_id.clone(), r.outcome()))
        .collect()
}

#[tokio::test]
async fn a_saga_survivor_carries_the_folded_last_seen_at() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h.ctx.insert_person_with_distinct_id("seen-target").await;
    let source = h.ctx.insert_person_with_distinct_id("seen-source").await;
    h.leader.set_last_seen(target, 1_000);
    h.leader.set_last_seen(source, 2_000);

    let request = rpc_request(
        h.ctx.team_id,
        "seen-target",
        &["seen-source"],
        Uuid::now_v7(),
    );
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("merge succeeds")
        .into_inner();

    // The saga records its survivor as JSON and rebuilds the wire person
    // from it, so a field the record leaves out reaches the caller as unset
    // however well the fold computed it.
    let survivor = response.survivor.expect("survivor present");
    assert_eq!(survivor.id, target);
    assert_eq!(survivor.last_seen_at, Some(2_000));

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test(flavor = "multi_thread")]
async fn the_rpc_runs_the_saga_and_a_retry_returns_the_recorded_answer() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h.ctx.insert_person_with_distinct_id("rpc-target").await;
    let source = h.ctx.insert_person_with_distinct_id("rpc-source").await;
    h.set_person(source, r#"{"plan": "free"}"#, 4, false).await;

    let op_id = Uuid::now_v7();
    let request = rpc_request(h.ctx.team_id, "rpc-target", &["rpc-source"], op_id);
    let response = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("merge succeeds")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![("rpc-source".to_string(), MergeSourceOutcome::Merged)]
    );
    let survivor = response.survivor.expect("survivor present");
    assert_eq!(survivor.id, target);
    assert!(survivor.is_identified);
    let calls_after_first = h.leader.calls().len();

    // The retry arrives AFTER the merge moved the world: the source did now
    // resolves to the target, so re-classification would answer
    // noop_same_person — and a naive handler would freeze that different
    // request and be rejected by the engine's equality guard. Attach-first
    // returns the recorded answer instead: same outcome, no new leader work.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("the retry attaches")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry),
        vec![("rpc-source".to_string(), MergeSourceOutcome::Merged)]
    );
    assert_eq!(retry.survivor.expect("survivor present").id, target);
    assert_eq!(
        h.leader.calls().len(),
        calls_after_first,
        "a retry of a finished op re-runs nothing"
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn inline_cases_settle_without_an_op_row_and_push_the_event_properties() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h.ctx.insert_person_with_distinct_id("inline-target").await;
    h.add_distinct_id(target, "inline-alias").await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(
        h.ctx.team_id,
        "inline-target",
        &["inline-alias", "anonymous", "inline-unresolved"],
        op_id,
    );
    request.event_set = serde_json::to_vec(&json!({"plan": "pro"})).unwrap();
    let response = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("inline call succeeds")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![
            (
                "inline-alias".to_string(),
                MergeSourceOutcome::NoopSamePerson
            ),
            ("anonymous".to_string(), MergeSourceOutcome::SkippedIllegal),
            (
                "inline-unresolved".to_string(),
                MergeSourceOutcome::Attached
            ),
        ]
    );
    assert_eq!(h.pdi_state("inline-unresolved").await, (target, false, 1));
    let survivor = response.survivor.expect("survivor present");
    assert_eq!(survivor.id, target);
    // The survivor's created_at unit must not depend on which branch
    // produced it: the leader already answers epoch millis, so the
    // response must pass it through unscaled.
    let target_created_ms: i64 = sqlx::query_scalar(
        "SELECT floor(extract(epoch from created_at) * 1000)::bigint \
         FROM posthog_person WHERE team_id = $1 AND id = $2",
    )
    .bind(h.ctx.team_id as i32)
    .bind(target)
    .fetch_one(&h.ctx.pool)
    .await
    .unwrap();
    assert_eq!(survivor.created_at, target_created_ms);
    // The event's $set reached the survivor through the leader, carrying
    // the identified flip: pairs settled, so the survivor is identified...
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: target,
            is_identified: Some(true),
        }]
    );
    // ...and no durable op exists: nothing was destroyed, so retries just
    // re-classify.
    let op_count: i64 = sqlx::query_scalar("SELECT count(*) FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_one(&h.ctx.pool)
        .await
        .unwrap();
    assert_eq!(op_count, 0);

    // On re-classification the attached source resolves to the target and
    // settles as a no-op — an equivalent answer, not an error.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry)[2],
        (
            "inline-unresolved".to_string(),
            MergeSourceOutcome::NoopSamePerson
        )
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_mixed_call_folds_inline_and_saga_outcomes_in_request_order() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h.ctx.insert_person_with_distinct_id("mixed-target").await;
    h.add_distinct_id(target, "mixed-alias").await;
    let source = h.ctx.insert_person_with_distinct_id("mixed-source").await;

    let request = rpc_request(
        h.ctx.team_id,
        "mixed-target",
        &["mixed-alias", "mixed-personless", "mixed-source"],
        Uuid::now_v7(),
    );
    let response = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("merge succeeds")
        .into_inner();

    let expected = vec![
        (
            "mixed-alias".to_string(),
            MergeSourceOutcome::NoopSamePerson,
        ),
        ("mixed-personless".to_string(), MergeSourceOutcome::Attached),
        ("mixed-source".to_string(), MergeSourceOutcome::Merged),
    ];
    assert_eq!(rpc_outcomes(&response), expected);
    assert_eq!(h.pdi_state("mixed-personless").await, (target, false, 1));
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(source_deleted);

    // The attach outcome is frozen in the op row: a retry reproduces it
    // instead of re-classifying the pair as a no-op.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry attaches to the op")
        .into_inner();
    assert_eq!(rpc_outcomes(&retry), expected);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_op_id_reused_with_a_different_request_is_rejected() {
    let h = MergeHarness::new().await;
    let service = h.service();
    h.ctx.insert_person_with_distinct_id("reuse-target").await;
    h.ctx.insert_person_with_distinct_id("reuse-source").await;
    h.ctx.insert_person_with_distinct_id("reuse-other").await;

    let op_id = Uuid::now_v7();
    service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "reuse-target",
            &["reuse-source"],
            op_id,
        )))
        .await
        .expect("first call succeeds");

    let status = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "reuse-target",
            &["reuse-other"],
            op_id,
        )))
        .await
        .expect_err("a different request must not attach");
    assert_eq!(status.code(), Code::FailedPrecondition);
    assert_eq!(
        personhog_common::grpc::semantic_refusal_reason(&status),
        Some("op_id_reused"),
        "callers branch on the refusal reason, not the message"
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_create_race_loser_answers_retryable_unavailable() {
    let h = MergeHarness::new().await;
    let executor = MergeOpExecutor::new(
        Arc::new(h.ctx.engine()),
        MergeDriver::new(h.leader.clone(), h.ctx.tables.clone()),
    );
    let op_id = Uuid::now_v7();

    // Drive a first frozen request to terminal: its target resolves to
    // nothing, so the claim aborts the op in a single step.
    let mut frozen_a =
        serde_json::to_value(merge_request("race-target", &["race-source"])).unwrap();
    frozen_a["original"] = json!({"call": "a"});
    frozen_a["inline_results"] = json!({});
    executor
        .execute(op_id, h.ctx.team_id, &frozen_a)
        .await
        .expect("first request drives to terminal");

    // The entrance reaches this create path only after its attach-first
    // check found no op row, so a mismatch here is the insert-race
    // window: it must answer retryable UNAVAILABLE (the retry attaches
    // fine), not the terminal FAILED_PRECONDITION neither client stack
    // retries.
    let mut frozen_b = frozen_a.clone();
    frozen_b["original"] = json!({"call": "b"});
    let status = executor
        .execute(op_id, h.ctx.team_id, &frozen_b)
        .await
        .expect_err("a mismatched frozen request must not attach");
    assert_eq!(status.code(), Code::Unavailable);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn invalid_merge_requests_are_rejected_before_any_work() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let team_id = h.ctx.team_id;
    let op = Uuid::now_v7();

    let cases: Vec<(&str, MergePersonsRequest, Code)> = vec![
        (
            "zero team",
            rpc_request(0, "t", &["s"], op),
            Code::InvalidArgument,
        ),
        (
            "illegal target",
            rpc_request(team_id, "anonymous", &["s"], op),
            Code::InvalidArgument,
        ),
        (
            "no sources",
            rpc_request(team_id, "t", &[], op),
            Code::InvalidArgument,
        ),
        (
            "duplicate sources",
            rpc_request(team_id, "t", &["s", "s"], op),
            Code::InvalidArgument,
        ),
        (
            "bad op_id",
            MergePersonsRequest {
                op_id: "not-a-uuid".to_string(),
                ..rpc_request(team_id, "t", &["s"], op)
            },
            Code::InvalidArgument,
        ),
        (
            "non-object event_set",
            MergePersonsRequest {
                event_set: serde_json::to_vec(&json!(["not", "a", "map"])).unwrap(),
                ..rpc_request(team_id, "t", &["s"], op)
            },
            Code::InvalidArgument,
        ),
        (
            "missing move_limit",
            MergePersonsRequest {
                move_limit: None,
                ..rpc_request(team_id, "t", &["s"], op)
            },
            Code::InvalidArgument,
        ),
        (
            "non-positive move_limit",
            MergePersonsRequest {
                move_limit: Some(0),
                ..rpc_request(team_id, "t", &["s"], op)
            },
            Code::InvalidArgument,
        ),
        (
            "negative created_at",
            MergePersonsRequest {
                created_at: -1,
                ..rpc_request(team_id, "t", &["s"], op)
            },
            Code::InvalidArgument,
        ),
        (
            "oversized target",
            rpc_request(team_id, &"x".repeat(401), &["s"], op),
            Code::InvalidArgument,
        ),
        (
            "NUL target",
            rpc_request(team_id, "nul\u{0000}target", &["s"], op),
            Code::InvalidArgument,
        ),
        (
            "NUL source",
            rpc_request(team_id, "t", &["nul\u{0000}source"], op),
            Code::InvalidArgument,
        ),
    ];
    for (label, request, expected) in cases {
        let status = service
            .merge_persons(Request::new(request))
            .await
            .expect_err(label);
        assert_eq!(status.code(), expected, "{label}");
    }
    assert!(h.leader.calls().is_empty());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_unresolved_target_attaches_to_the_first_resolved_sources_person() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let survivor = h.ctx.insert_person_with_distinct_id("flip-source").await;

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "flip-target",
            &["flip-personless", "flip-source"],
            Uuid::now_v7(),
        )))
        .await
        .expect("target attach succeeds")
        .into_inner();

    assert_eq!(
        response.survivor.as_ref().expect("survivor present").id,
        survivor
    );
    assert_eq!(
        rpc_outcomes(&response),
        vec![
            ("flip-personless".to_string(), MergeSourceOutcome::Attached),
            (
                "flip-source".to_string(),
                MergeSourceOutcome::NoopSamePerson
            ),
        ]
    );
    // The target distinct id and the personless source both attached to the
    // surviving person, with version 1 (an override row is always written).
    assert_eq!(h.pdi_state("flip-target").await, (survivor, false, 1));
    assert_eq!(h.pdi_state("flip-personless").await, (survivor, false, 1));
    // Pairs settled, so the survivor is identified via one leader push.
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: survivor,
            is_identified: Some(true),
        }]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_identified_source_is_not_an_eligible_survivor_for_an_unresolved_target() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let source = h
        .ctx
        .insert_person_with_distinct_id("elig-ident-source")
        .await;
    h.set_person(source, r#"{"plan": "pro"}"#, 3, true).await;

    // A creating event is sent, so the newborn's lack of one below is the
    // saga path declining to stamp rather than nothing having been offered.
    let mut request = rpc_request(
        h.ctx.team_id,
        "elig-target",
        &["elig-ident-source"],
        Uuid::now_v7(),
    );
    request.creator_event_uuid = "77777777-7777-7777-7777-777777777777".to_string();
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("call succeeds")
        .into_inner();

    // The identified person must not absorb the unresolved target: that
    // attach would settle the pair as a same-person no-op and bypass the
    // saga's refusal. The target is born fresh instead and the pair gets
    // the same policy answer the both-exist shape gives.
    let survivor = response.survivor.as_ref().expect("survivor present");
    assert_ne!(survivor.id, source);
    assert_eq!(
        survivor.uuid,
        person_uuid(h.ctx.team_id, "elig-target").to_string()
    );
    assert_eq!(
        rpc_outcomes(&response),
        vec![(
            "elig-ident-source".to_string(),
            MergeSourceOutcome::SkippedAlreadyIdentified
        )]
    );
    // Establishment birthed the target while the classification loop sent
    // the identified source to the saga, so the response reports no birth
    // and the newborn carries no creating event. Only the inline settlement
    // stamps one.
    assert!(!response.survivor_created);
    let born_properties: serde_json::Value = if survivor.properties.is_empty() {
        serde_json::json!({})
    } else {
        serde_json::from_slice(&survivor.properties).expect("survivor properties are JSON")
    };
    assert_eq!(born_properties.get("$creator_event_uuid"), None);
    assert_eq!(h.pdi_state("elig-target").await, (survivor.id, false, 0));
    assert_eq!(h.pdi_state("elig-ident-source").await.0, source);
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(!source_deleted);
    // The refused pair aborts the saga, so the abort delivery flips the
    // newborn through the leader.
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: survivor.id,
            is_identified: Some(true),
        }]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn allow_identified_sources_lets_an_identified_source_survive_an_unresolved_target() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let source = h
        .ctx
        .insert_person_with_distinct_id("elig-allowed-source")
        .await;
    h.set_person(source, r#"{"plan": "pro"}"#, 3, true).await;

    let mut request = rpc_request(
        h.ctx.team_id,
        "elig-allowed-target",
        &["elig-allowed-source"],
        Uuid::now_v7(),
    );
    request.allow_identified_sources = true;
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("call succeeds")
        .into_inner();

    let survivor = response.survivor.as_ref().expect("survivor present");
    assert_eq!(survivor.id, source);
    assert_eq!(
        rpc_outcomes(&response),
        vec![(
            "elig-allowed-source".to_string(),
            MergeSourceOutcome::NoopSamePerson
        )]
    );
    assert_eq!(h.pdi_state("elig-allowed-target").await, (source, false, 1));

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_fully_unresolved_call_births_the_target_person() {
    let h = MergeHarness::new().await;
    let service = h.service();

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(h.ctx.team_id, "birth-target", &["birth-anon"], op_id);
    request.created_at = 1_700_000_000_000;
    request.creator_event_uuid = "11111111-2222-3333-4444-555555555555".to_string();
    let response = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("target birth succeeds")
        .into_inner();

    // The person is born on the target distinct id's deterministic uuid,
    // stamped with the event's timestamp, and identified by the settlement
    // flip through the leader.
    let survivor = response.survivor.as_ref().expect("survivor present");
    assert_eq!(
        survivor.uuid,
        person_uuid(h.ctx.team_id, "birth-target").to_string()
    );
    assert_eq!(survivor.created_at, 1_700_000_000_000);
    assert!(survivor.is_identified);
    assert_eq!(
        rpc_outcomes(&response),
        vec![("birth-anon".to_string(), MergeSourceOutcome::Attached)]
    );
    // The uuid-seeding distinct id keeps version 0 (its implied-person
    // events already point at this person); the attached one gets 1.
    assert_eq!(h.pdi_state("birth-target").await, (survivor.id, false, 0));
    assert_eq!(h.pdi_state("birth-anon").await, (survivor.id, false, 1));
    // Born unidentified, then flipped through the leader: the flip is a
    // change the leader records, so it doubles as the newborn's first
    // changelog document — the downstream person feed's copy. A stub born
    // identified would make the flip a no-op and never reach the feed.
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: survivor.id,
            is_identified: Some(true),
        }]
    );
    // The event that created the person is recorded on it, which is what the
    // Postgres backend writes at creation. It rides the settlement push rather
    // than the stub row, because a stub is written straight to Postgres and
    // never reaches the leader's changelog.
    let properties: serde_json::Value =
        serde_json::from_slice(&survivor.properties).expect("survivor properties are JSON");
    assert_eq!(
        properties
            .get("$creator_event_uuid")
            .and_then(serde_json::Value::as_str),
        Some("11111111-2222-3333-4444-555555555555")
    );
    // Born by this call and identified by the settlement flip, which is the
    // pair the caller reads to decide it needs no follow-up update.
    assert!(response.survivor_created);
    let op_count: i64 = sqlx::query_scalar("SELECT count(*) FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_one(&h.ctx.pool)
        .await
        .unwrap();
    assert_eq!(op_count, 0);

    // A retry re-classifies against the settled world and answers the
    // equivalent no-op, with the same survivor.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(
        retry.survivor.as_ref().expect("survivor present").id,
        survivor.id
    );
    assert_eq!(
        rpc_outcomes(&retry),
        vec![("birth-anon".to_string(), MergeSourceOutcome::NoopSamePerson)]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn attaching_an_unseen_target_onto_a_source_is_not_a_birth() {
    // With no target person to resolve, establish_target attaches the unseen
    // target id onto the eligible source's person instead of birthing one.
    // That person predates the call, so the event that reached it did not
    // create it and must not be recorded as having done so.
    let h = MergeHarness::new().await;
    let service = h.service();
    let source = h.ctx.insert_person_with_distinct_id("attach-source").await;

    let mut request = rpc_request(
        h.ctx.team_id,
        "attach-target",
        &["attach-source"],
        Uuid::now_v7(),
    );
    request.creator_event_uuid = "44444444-3333-2222-1111-000000000000".to_string();
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("merge succeeds")
        .into_inner();

    let survivor = response.survivor.as_ref().expect("survivor present");
    assert_eq!(survivor.id, source);
    assert!(!response.survivor_created);
    let properties: serde_json::Value =
        serde_json::from_slice(&survivor.properties).expect("survivor properties are JSON");
    assert!(properties.get("$creator_event_uuid").is_none());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_event_cannot_choose_its_own_creator_event_uuid() {
    // The property names the event that created the person, and it is
    // client-supplied input, so a value the event carries for that key must
    // not survive. The Postgres backend spreads its own last over both maps
    // at creation for the same reason.
    let h = MergeHarness::new().await;
    let service = h.service();

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(h.ctx.team_id, "forge-target", &["forge-anon"], op_id);
    request.created_at = 1_700_000_000_000;
    request.creator_event_uuid = "11111111-2222-3333-4444-555555555555".to_string();
    request.event_set = serde_json::to_vec(&serde_json::json!({
        "$creator_event_uuid": "99999999-9999-9999-9999-999999999999"
    }))
    .expect("set serializes");
    request.event_set_once = serde_json::to_vec(&serde_json::json!({
        "$creator_event_uuid": "88888888-8888-8888-8888-888888888888"
    }))
    .expect("set_once serializes");

    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("target birth succeeds")
        .into_inner();

    let survivor = response.survivor.as_ref().expect("survivor present");
    let properties: serde_json::Value =
        serde_json::from_slice(&survivor.properties).expect("survivor properties are JSON");
    assert_eq!(
        properties
            .get("$creator_event_uuid")
            .and_then(serde_json::Value::as_str),
        Some("11111111-2222-3333-4444-555555555555")
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_resolved_target_does_not_gain_a_creator_event_uuid() {
    // The Postgres backend stamps $creator_event_uuid at creation and never
    // afterwards, so a merge landing on a person that already existed must
    // leave it alone. Only the establish path's newborn gets one.
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h.ctx.insert_person_with_distinct_id("keep-target").await;

    let mut request = rpc_request(h.ctx.team_id, "keep-target", &["keep-anon"], Uuid::now_v7());
    request.creator_event_uuid = "99999999-8888-7777-6666-555555555555".to_string();
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("merge succeeds")
        .into_inner();

    let survivor = response.survivor.as_ref().expect("survivor present");
    assert_eq!(survivor.id, target);
    let properties: serde_json::Value = if survivor.properties.is_empty() {
        serde_json::json!({})
    } else {
        serde_json::from_slice(&survivor.properties).expect("survivor properties are JSON")
    };
    assert_eq!(properties.get("$creator_event_uuid"), None);
    assert!(!response.survivor_created);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_all_illegal_call_births_the_target_unidentified() {
    let h = MergeHarness::new().await;
    let service = h.service();

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "illegal-only-target",
            &["anonymous"],
            Uuid::now_v7(),
        )))
        .await
        .expect("call succeeds")
        .into_inner();

    // The caller's event still needs a person, so the target is born — but
    // an identify whose every pair was skipped proves no identity.
    let survivor = response.survivor.as_ref().expect("survivor present");
    assert!(!survivor.is_identified);
    assert_eq!(
        rpc_outcomes(&response),
        vec![("anonymous".to_string(), MergeSourceOutcome::SkippedIllegal)]
    );
    assert_eq!(
        h.pdi_state("illegal-only-target").await,
        (survivor.id, false, 0)
    );
    assert!(h.leader.calls().is_empty());

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_unresolved_target_call_still_runs_the_saga_for_second_persons() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let survivor = h.ctx.insert_person_with_distinct_id("flip-saga-a").await;
    let other = h.ctx.insert_person_with_distinct_id("flip-saga-b").await;

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "flip-saga-target",
            &["flip-saga-a", "flip-saga-b"],
            Uuid::now_v7(),
        )))
        .await
        .expect("merge succeeds")
        .into_inner();

    // The first resolved source's person survives; the second person folds
    // into it through the saga and dies.
    assert_eq!(
        response.survivor.as_ref().expect("survivor present").id,
        survivor
    );
    assert_eq!(
        rpc_outcomes(&response),
        vec![
            (
                "flip-saga-a".to_string(),
                MergeSourceOutcome::NoopSamePerson
            ),
            ("flip-saga-b".to_string(), MergeSourceOutcome::Merged),
        ]
    );
    assert_eq!(h.pdi_state("flip-saga-target").await, (survivor, false, 1));
    assert_eq!(h.pdi_state("flip-saga-b").await, (survivor, false, 1));
    let (other_deleted, _, _) = h.person_state(other).await;
    assert!(other_deleted);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_move_limited_source_skips_while_the_rest_merge_through_the_rpc() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("rpc-limit-target")
        .await;
    let small = h
        .ctx
        .insert_person_with_distinct_id("rpc-limit-small")
        .await;
    let big = h.ctx.insert_person_with_distinct_id("rpc-limit-big").await;
    h.add_distinct_id(big, "rpc-limit-big-2").await;

    let mut request = rpc_request(
        h.ctx.team_id,
        "rpc-limit-target",
        &["rpc-limit-small", "rpc-limit-big"],
        Uuid::now_v7(),
    );
    request.move_limit = Some(1);
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("merge succeeds")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![
            ("rpc-limit-small".to_string(), MergeSourceOutcome::Merged),
            (
                "rpc-limit-big".to_string(),
                MergeSourceOutcome::SkippedMoveLimit
            ),
        ]
    );
    assert_eq!(response.survivor.as_ref().expect("survivor").id, target);
    let (small_deleted, _, _) = h.person_state(small).await;
    assert!(small_deleted);
    let (big_deleted, _, _) = h.person_state(big).await;
    assert!(!big_deleted, "a move-limited source must stay untouched");

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn an_identified_source_abort_still_delivers_the_events_writes() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("rpc-ident-target")
        .await;
    let source = h
        .ctx
        .insert_person_with_distinct_id("rpc-ident-source")
        .await;
    h.set_person(source, r#"{"plan": "pro"}"#, 3, true).await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(
        h.ctx.team_id,
        "rpc-ident-target",
        &["rpc-ident-source"],
        op_id,
    );
    request.event_set = serde_json::to_vec(&json!({"tier": "pro"})).unwrap();
    let response = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("an aborted op still answers OK")
        .into_inner();

    // The skip is an answer, not an error. The saga never folds, so the
    // event's $set and the identified flip are delivered through the
    // ordinary write surface instead, and the answer carries the person
    // they landed on — the same person ingestion continues the event with
    // when it refuses a merge.
    assert_eq!(
        rpc_outcomes(&response),
        vec![(
            "rpc-ident-source".to_string(),
            MergeSourceOutcome::SkippedAlreadyIdentified
        )]
    );
    assert_eq!(response.survivor.as_ref().expect("survivor").id, target);
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: target,
            is_identified: Some(true),
        }]
    );
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(!source_deleted);

    // The abort is recorded: a retry reproduces the answer instead of
    // re-running classification, and re-drives the delivery (the same
    // at-least-once semantics as the inline branch).
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(retry.survivor.as_ref().expect("survivor").id, target);
    assert_eq!(
        rpc_outcomes(&retry),
        vec![(
            "rpc-ident-source".to_string(),
            MergeSourceOutcome::SkippedAlreadyIdentified
        )]
    );
    assert_eq!(h.leader.calls().len(), 2);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_failed_abort_delivery_errors_the_call_and_the_retry_delivers() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("rpc-abort-fail-target")
        .await;
    let source = h
        .ctx
        .insert_person_with_distinct_id("rpc-abort-fail-source")
        .await;
    h.set_person(source, r#"{"plan": "pro"}"#, 3, true).await;
    h.leader.fail_next(
        Rpc::PropertyPush,
        target,
        Status::unavailable("leader unavailable"),
    );

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(
        h.ctx.team_id,
        "rpc-abort-fail-target",
        &["rpc-abort-fail-source"],
        op_id,
    );
    request.event_set = serde_json::to_vec(&json!({"tier": "pro"})).unwrap();

    // OK means the event's writes are durable, so a failed delivery must
    // surface as an error, never as an aborted answer with lost writes.
    let status = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect_err("a failed delivery fails the call");
    assert_eq!(status.code(), Code::Unavailable);
    let (step, _) = op_row_state(&h.ctx.pool, op_id).await;
    assert_eq!(step, STEP_ABORTED);

    // The retry attaches to the recorded abort and re-drives the delivery.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(retry.survivor.as_ref().expect("survivor").id, target);
    assert_eq!(
        rpc_outcomes(&retry),
        vec![(
            "rpc-abort-fail-source".to_string(),
            MergeSourceOutcome::SkippedAlreadyIdentified
        )]
    );
    assert_eq!(
        h.leader.calls(),
        vec![LeaderCall::PropertyPush {
            person_id: target,
            is_identified: Some(true),
        }]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn allow_identified_sources_merges_an_identified_source() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("rpc-dang-target")
        .await;
    let source = h
        .ctx
        .insert_person_with_distinct_id("rpc-dang-source")
        .await;
    h.set_person(source, r#"{"plan": "pro"}"#, 3, true).await;

    let mut request = rpc_request(
        h.ctx.team_id,
        "rpc-dang-target",
        &["rpc-dang-source"],
        Uuid::now_v7(),
    );
    request.allow_identified_sources = true;
    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("merge succeeds")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![("rpc-dang-source".to_string(), MergeSourceOutcome::Merged)]
    );
    assert_eq!(response.survivor.as_ref().expect("survivor").id, target);
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(source_deleted);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_failed_property_push_errors_the_call_and_the_retry_settles() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("rpc-pushfail-target")
        .await;
    h.add_distinct_id(target, "rpc-pushfail-alias").await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(
        h.ctx.team_id,
        "rpc-pushfail-target",
        &["rpc-pushfail-alias"],
        op_id,
    );
    request.event_set = serde_json::to_vec(&json!({"plan": "pro"})).unwrap();
    h.leader.fail_next(
        Rpc::PropertyPush,
        target,
        Status::unavailable("leader down"),
    );

    // The push failure must fail the whole call — never an OK response
    // whose properties silently went nowhere.
    let status = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect_err("a failed push fails the call");
    assert_eq!(status.code(), Code::Unavailable);
    let op_count: i64 = sqlx::query_scalar("SELECT count(*) FROM lifecycle_op WHERE op_id = $1")
        .bind(op_id)
        .fetch_one(&h.ctx.pool)
        .await
        .unwrap();
    assert_eq!(op_count, 0);

    // The retry re-classifies and settles the same pairs.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry),
        vec![(
            "rpc-pushfail-alias".to_string(),
            MergeSourceOutcome::NoopSamePerson
        )]
    );
    assert_eq!(retry.survivor.as_ref().expect("survivor").id, target);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_failed_push_after_attach_leaves_the_attach_durable() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("att-pushfail-target")
        .await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(
        h.ctx.team_id,
        "att-pushfail-target",
        &["att-pushfail-anon"],
        op_id,
    );
    request.event_set = serde_json::to_vec(&json!({"plan": "pro"})).unwrap();
    h.leader.fail_next(
        Rpc::PropertyPush,
        target,
        Status::unavailable("leader down"),
    );

    let status = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect_err("a failed push fails the call");
    assert_eq!(status.code(), Code::Unavailable);
    // The attach committed before the push and must survive the failure —
    // the retry contract depends on it.
    assert_eq!(h.pdi_state("att-pushfail-anon").await, (target, false, 1));

    // The retry re-classifies: the attached pair settles as the
    // equivalent no-op and the push succeeds.
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("retry succeeds")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry),
        vec![(
            "att-pushfail-anon".to_string(),
            MergeSourceOutcome::NoopSamePerson
        )]
    );
    assert_eq!(retry.survivor.as_ref().expect("survivor").id, target);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_target_attach_race_resolves_to_the_winner() {
    let h = MergeHarness::new().await;
    let winner = h.ctx.insert_person_with_distinct_id("race-winner").await;
    let source = h.ctx.insert_person_with_distinct_id("race-source").await;
    let racing = Arc::new(common::RacingStorage::new(h.ctx.storage.clone()));
    *racing.hijack_attach_to.lock().unwrap() = Some(winner);
    let service = h.service_with_storage(racing);

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "race-target",
            &["race-source"],
            Uuid::now_v7(),
        )))
        .await
        .expect("merge succeeds")
        .into_inner();

    // The concurrent mapping wins: the target distinct id belongs to the
    // winner, the winner is the survivor, and the resolved source still
    // folds into it through the saga.
    assert_eq!(response.survivor.as_ref().expect("survivor").id, winner);
    assert_eq!(
        rpc_outcomes(&response),
        vec![("race-source".to_string(), MergeSourceOutcome::Merged)]
    );
    assert_eq!(h.pdi_state("race-target").await, (winner, false, 1));
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(source_deleted);

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_lost_stub_race_resolves_to_the_winner() {
    let h = MergeHarness::new().await;
    let racing = Arc::new(common::RacingStorage::new(h.ctx.storage.clone()));
    *racing.lose_create_race.lock().unwrap() = true;
    let service = h.service_with_storage(racing);

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "race-birth-target",
            &["race-birth-anon"],
            Uuid::now_v7(),
        )))
        .await
        .expect("merge succeeds")
        .into_inner();

    // The lost insert re-resolves to the concurrent winner — the same
    // person, born on the target distinct id's deterministic uuid — and
    // settlement continues against it.
    let survivor = response.survivor.as_ref().expect("survivor");
    assert_eq!(
        survivor.uuid,
        person_uuid(h.ctx.team_id, "race-birth-target").to_string()
    );
    assert_eq!(
        rpc_outcomes(&response),
        vec![("race-birth-anon".to_string(), MergeSourceOutcome::Attached)]
    );
    assert_eq!(
        h.pdi_state("race-birth-anon").await,
        (survivor.id, false, 1)
    );

    h.ctx.cleanup().await.expect("cleanup");
}

#[tokio::test]
async fn a_vanished_survivor_answers_unavailable_with_nothing_written() {
    let h = MergeHarness::new().await;
    let source = h
        .ctx
        .insert_person_with_distinct_id("race-vanish-source")
        .await;
    let racing = Arc::new(common::RacingStorage::new(h.ctx.storage.clone()));
    *racing.vanish_attach.lock().unwrap() = true;
    let service = h.service_with_storage(racing);

    let status = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "race-vanish-target",
            &["race-vanish-source"],
            Uuid::now_v7(),
        )))
        .await
        .expect_err("a vanished survivor fails the call");

    // Retryable, and nothing durable happened: the target distinct id is
    // still unmapped and the source person untouched.
    assert_eq!(status.code(), Code::Unavailable);
    let mapped: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2",
    )
    .bind(h.ctx.team_id as i32)
    .bind("race-vanish-target")
    .fetch_one(&h.ctx.pool)
    .await
    .unwrap();
    assert_eq!(mapped, 0);
    let (source_deleted, _, _) = h.person_state(source).await;
    assert!(!source_deleted);

    h.ctx.cleanup().await.expect("cleanup");
}

/// Sources whose verdict is fixed before any lookup — illegal ids and ids
/// too long for the varchar(400) column — must not ride the resolution
/// query: nothing reads their resolutions, so resolving them would let a
/// caller pump arbitrarily large ids through the primary for free.
#[tokio::test]
async fn settled_sources_stay_out_of_the_resolution_query() {
    let h = MergeHarness::new().await;
    let racing = Arc::new(common::RacingStorage::new(h.ctx.storage.clone()));
    let service = h.service_with_storage(racing.clone());
    h.ctx.insert_person_with_distinct_id("resq-target").await;
    h.ctx.insert_person_with_distinct_id("resq-source").await;

    let oversized = "x".repeat(401);
    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "resq-target",
            &["resq-source", "anonymous", &oversized],
            Uuid::now_v7(),
        )))
        .await
        .expect("merge succeeds")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![
            ("resq-source".to_string(), MergeSourceOutcome::Merged),
            ("anonymous".to_string(), MergeSourceOutcome::SkippedIllegal),
            (oversized.clone(), MergeSourceOutcome::SkippedIllegal),
        ]
    );
    let resolved: Vec<String> = racing
        .resolved_keys
        .lock()
        .unwrap()
        .iter()
        .map(|(_, did)| did.clone())
        .collect();
    assert!(
        resolved.contains(&"resq-target".to_string())
            && resolved.contains(&"resq-source".to_string()),
        "the live pair still resolves"
    );
    assert!(
        !resolved.contains(&"anonymous".to_string()) && !resolved.contains(&oversized),
        "settled sources must not reach the resolution query: {resolved:?}"
    );

    h.ctx.cleanup().await.expect("cleanup");
}

/// An oversized source settles per-source, exactly like an illegal id: it
/// cannot exist in the varchar(400) column, so it can never resolve, and
/// failing the whole request would take legitimate sources down with it.
#[tokio::test]
async fn an_oversized_source_settles_per_source_instead_of_failing_the_request() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let target = h
        .ctx
        .insert_person_with_distinct_id("oversize-target")
        .await;
    let oversized = "x".repeat(401);

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "oversize-target",
            &[oversized.as_str()],
            Uuid::now_v7(),
        )))
        .await
        .expect("the request succeeds; the source settles")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![(oversized, MergeSourceOutcome::SkippedIllegal)]
    );
    assert_eq!(response.survivor.expect("survivor").id, target);

    h.ctx.cleanup().await.expect("cleanup");
}

/// A multibyte source inside 400 characters but past 400 bytes is storable
/// (varchar counts characters) and must merge, not bounce the request.
#[tokio::test]
async fn a_multibyte_source_within_the_character_limit_merges() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let _target = h
        .ctx
        .insert_person_with_distinct_id("multibyte-target")
        .await;
    // 200 three-byte chars: 600 bytes, 200 characters.
    let multibyte = "\u{4e16}".repeat(200);
    let source = h.ctx.insert_person_with_distinct_id(&multibyte).await;

    let response = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "multibyte-target",
            &[multibyte.as_str()],
            Uuid::now_v7(),
        )))
        .await
        .expect("a storable id merges")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![(multibyte, MergeSourceOutcome::Merged)]
    );
    let _ = source;

    h.ctx.cleanup().await.expect("cleanup");
}

/// NUL in the merge event's payload sanitizes rather than killing the
/// frozen op row's jsonb insert; the merge itself proceeds.
#[tokio::test]
async fn a_nul_bearing_event_payload_is_sanitized_and_the_merge_runs() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let _target = h.ctx.insert_person_with_distinct_id("nul-target").await;
    let _source = h.ctx.insert_person_with_distinct_id("nul-source").await;

    let mut request = rpc_request(h.ctx.team_id, "nul-target", &["nul-source"], Uuid::now_v7());
    request.event_set = serde_json::to_vec(&json!({"note": "x\u{0000}y"})).unwrap();

    let response = service
        .merge_persons(Request::new(request))
        .await
        .expect("the merge survives a NUL payload")
        .into_inner();

    assert_eq!(
        rpc_outcomes(&response),
        vec![("nul-source".to_string(), MergeSourceOutcome::Merged)]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

/// NUL cannot exist in Postgres text: a NUL target would fail person
/// establishment with an internal error on every attempt, and a NUL source
/// would make the frozen op row unwritable jsonb. Both refuse up front.
#[tokio::test]
async fn nul_bearing_distinct_ids_are_refused_before_any_durable_work() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let _target = h.ctx.insert_person_with_distinct_id("nul-id-target").await;

    let target_nul = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "bad\u{0000}target",
            &["nul-id-source"],
            Uuid::now_v7(),
        )))
        .await
        .expect_err("a NUL target refuses");
    assert_eq!(target_nul.code(), Code::InvalidArgument);

    let source_nul = service
        .merge_persons(Request::new(rpc_request(
            h.ctx.team_id,
            "nul-id-target",
            &["bad\u{0000}source"],
            Uuid::now_v7(),
        )))
        .await
        .expect_err("a NUL source refuses");
    assert_eq!(source_nul.code(), Code::InvalidArgument);

    h.ctx.cleanup().await.expect("cleanup");
}

/// The one job of the `created_at` strip in `same_merge`: a redelivery
/// whose event carried no timestamp derives a fresh wall-clock created_at,
/// and the retry must attach to the recorded op and replay its outcome
/// rather than bounce FAILED_PRECONDITION forever.
#[tokio::test]
async fn a_retry_with_a_drifted_created_at_replays_the_recorded_outcome() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let _target = h.ctx.insert_person_with_distinct_id("drift-target").await;
    let source = h.ctx.insert_person_with_distinct_id("drift-source").await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(h.ctx.team_id, "drift-target", &["drift-source"], op_id);
    request.created_at = 1_000;
    let first = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("first call merges")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&first),
        vec![("drift-source".to_string(), MergeSourceOutcome::Merged)]
    );

    request.created_at = 2_000;
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("the drifted retry attaches instead of bouncing")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry),
        vec![("drift-source".to_string(), MergeSourceOutcome::Merged)]
    );
    let _ = source;

    h.ctx.cleanup().await.expect("cleanup");
}

/// Two deliveries of one event disagree on pipeline-refreshed properties,
/// so the retry must attach to the recorded op and replay its outcome — a
/// refusal here is permanent and drops the merge with the fence standing.
/// The recorded op re-executes from its own frozen request, so drifted
/// values are discarded either way.
#[tokio::test]
async fn a_retry_with_drifted_event_properties_replays_the_recorded_outcome() {
    let h = MergeHarness::new().await;
    let service = h.service();
    let _target = h.ctx.insert_person_with_distinct_id("props-target").await;
    let _source = h.ctx.insert_person_with_distinct_id("props-source").await;

    let op_id = Uuid::now_v7();
    let mut request = rpc_request(h.ctx.team_id, "props-target", &["props-source"], op_id);
    request.event_set = serde_json::to_vec(&json!({"$geoip_city_name": "Paris"})).unwrap();
    request.event_set_once = serde_json::to_vec(&json!({"$initial_referrer": "a"})).unwrap();
    let first = service
        .merge_persons(Request::new(request.clone()))
        .await
        .expect("first call merges")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&first),
        vec![("props-source".to_string(), MergeSourceOutcome::Merged)]
    );

    request.event_set = serde_json::to_vec(&json!({"$geoip_city_name": "Berlin"})).unwrap();
    request.event_set_once = serde_json::to_vec(&json!({"$initial_referrer": "b"})).unwrap();
    let retry = service
        .merge_persons(Request::new(request))
        .await
        .expect("the drifted retry attaches instead of bouncing")
        .into_inner();
    assert_eq!(
        rpc_outcomes(&retry),
        vec![("props-source".to_string(), MergeSourceOutcome::Merged)]
    );

    h.ctx.cleanup().await.expect("cleanup");
}

/// U+0085 (NEL) survives JavaScript's trim, so a JavaScript client reads a
/// NEL-only id as legal; the server must agree or every merge naming one
/// bounces INVALID_ARGUMENT on a check the client cannot predict.
#[test]
fn nel_only_ids_match_the_javascript_trim_semantics() {
    use personhog_identity::lifecycle::validation::is_distinct_id_illegal;
    assert!(!is_distinct_id_illegal("\u{0085}"));
    assert!(is_distinct_id_illegal(" \t\n "));
    assert!(is_distinct_id_illegal("\u{FEFF}"));
}
