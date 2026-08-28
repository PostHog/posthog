//! The delete saga's step handlers: `started → marked → sealed → unmapped →
//! completed`, with `aborted` reachable only from `started` (before anything
//! was mutated). Each step is one transaction that commits its work together
//! with the step advance — see the engine's correctness model.
//!
//! Sealing fences each victim on its owning leader — `FencePerson` rejects
//! writes while the op lives and returns the exact sealed version, so no
//! margin is needed — and completion calls `ReleaseFence(committed)` per
//! victim, which makes the leader produce the death document into the
//! changelog and evict its cache entry. The unmapped transaction still
//! writes the person tombstone directly: it is the durable revival floor
//! the sync plane reads (sanctioned by the RFC); the death document
//! confirms it downstream (writer, ClickHouse) at the same version,
//! sealed + 1. The distinct-id rows tombstoned by an op are recorded in
//! each victim row's `moved` column, so nothing needed for later emission
//! is lost.
//!
//! Ops sealed by a pre-fence build (sealed jsonb without `created_at`, the
//! margin folded into the version) complete without release calls — the
//! leader was never fenced for them, and their tombstone version already
//! carries the old margin.

use std::sync::Arc;

use async_trait::async_trait;
use futures::stream::{self, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::postgres::PgPool;
use tonic::Code;
use uuid::Uuid;

use personhog_proto::personhog::types::v1::{
    FencePersonRequest, LifecycleOpType, ReleaseFenceRequest, ReleaseOutcome,
};

use crate::config::IdentityTables;
use crate::leader::LifecycleLeader;
use crate::lifecycle::engine::{
    advance_step_in_tx, complete_op_in_tx, OpDriver, OpRow, SagaError, Tx, STEP_ABORTED,
    STEP_COMPLETED,
};

/// Bound on concurrent leader calls per step, matching the merge driver.
const LEADER_CALL_CONCURRENCY: usize = 8;

// Derived from the shared enum so the op-type string cannot drift from
// the leader's fence records or the lifecycle_op CHECK constraint.
pub const OP_TYPE_DELETE: &str = LifecycleOpType::Delete.as_op_type_str();

/// The delete saga's non-terminal steps, in order. Stored as text in
/// `lifecycle_op.step` (the engine is generic over op types, so its API is
/// stringly-typed); parsed back exactly once, at step dispatch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeleteStep {
    Started,
    Marked,
    Sealed,
    Unmapped,
}

impl DeleteStep {
    pub fn as_str(self) -> &'static str {
        match self {
            DeleteStep::Started => "started",
            DeleteStep::Marked => "marked",
            DeleteStep::Sealed => "sealed",
            DeleteStep::Unmapped => "unmapped",
        }
    }

    fn parse(step: &str) -> Option<Self> {
        match step {
            "started" => Some(DeleteStep::Started),
            "marked" => Some(DeleteStep::Marked),
            "sealed" => Some(DeleteStep::Sealed),
            "unmapped" => Some(DeleteStep::Unmapped),
            _ => None,
        }
    }
}

/// The frozen `lifecycle_op.request` payload for a delete op.
#[derive(Debug, Serialize, Deserialize)]
pub struct DeleteRequest {
    pub person_ids: Vec<i64>,
}

/// The recorded `lifecycle_op.outcome` payload: one entry per requested
/// person id, in request order.
#[derive(Debug, Serialize, Deserialize)]
pub struct DeleteOutcome {
    pub results: Vec<DeletePersonRecord>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DeletePersonRecord {
    pub person_id: i64,
    pub outcome: String,
}

pub const OUTCOME_DELETED: &str = "deleted";
pub const OUTCOME_SKIPPED_CONFLICT: &str = "skipped_conflict";
pub const OUTCOME_NOT_FOUND: &str = "not_found";

/// Per-person row statuses this driver writes.
const STATUS_MARKED: &str = "marked";
const STATUS_SEALED: &str = "sealed";
const STATUS_DELETED: &str = "deleted";
const STATUS_SKIPPED_CONFLICT: &str = "skipped_conflict";

const STEPS_TOTAL: &str = "personhog_lifecycle_delete_steps_total";
const OUTCOMES_TOTAL: &str = "personhog_lifecycle_delete_outcomes_total";

/// Call after a step's transaction commits — a commit means the step CAS was
/// won, so each transition is counted exactly once across concurrent drivers.
fn record_transition(from: &str, to: &str) {
    common_metrics::inc(
        STEPS_TOTAL,
        &[
            ("from".to_string(), from.to_string()),
            ("to".to_string(), to.to_string()),
        ],
        1,
    );
}

/// Call after the terminal transaction commits: one count per person,
/// labeled with its recorded outcome.
fn record_outcomes(outcome: &Value) {
    let Ok(parsed) = serde_json::from_value::<DeleteOutcome>(outcome.clone()) else {
        return;
    };
    for label in [OUTCOME_DELETED, OUTCOME_SKIPPED_CONFLICT, OUTCOME_NOT_FOUND] {
        let count = parsed.results.iter().filter(|r| r.outcome == label).count();
        if count > 0 {
            common_metrics::inc(
                OUTCOMES_TOTAL,
                &[("outcome".to_string(), label.to_string())],
                count as u64,
            );
        }
    }
}

pub struct DeleteDriver {
    leader: Arc<dyn LifecycleLeader>,
    tables: IdentityTables,
}

impl DeleteDriver {
    pub fn new(leader: Arc<dyn LifecycleLeader>, tables: IdentityTables) -> Self {
        tables.validate().expect("invalid identity table set");
        Self { leader, tables }
    }
}

#[async_trait]
impl OpDriver for DeleteDriver {
    fn op_type(&self) -> &'static str {
        OP_TYPE_DELETE
    }

    fn initial_step(&self) -> &'static str {
        DeleteStep::Started.as_str()
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let step = DeleteStep::parse(&op.step).ok_or_else(|| {
            SagaError::CorruptState(format!(
                "delete op {} is on unknown step '{}'",
                op.op_id, op.step
            ))
        })?;
        match step {
            DeleteStep::Started => mark(pool, &self.tables.person, op).await,
            DeleteStep::Marked => seal(pool, self.leader.as_ref(), op).await,
            DeleteStep::Sealed => unmap(pool, &self.tables, op).await,
            DeleteStep::Unmapped => complete(pool, self.leader.as_ref(), op).await,
        }
    }
}

fn parse_request(op: &OpRow) -> Result<DeleteRequest, SagaError> {
    serde_json::from_value(op.request.clone()).map_err(|e| {
        SagaError::CorruptState(format!(
            "delete op {} has a malformed request: {e}",
            op.op_id
        ))
    })
}

/// `started → marked`: claim the victims. One row per live victim in
/// `lifecycle_op_person`; the partial unique mark index makes a conflicting
/// insert a no-op, and a victim we could not claim is recorded as
/// `skipped_conflict`. Requested ids with no live person row get no row at
/// all — they surface as `not_found` in the outcome. If nothing was claimed
/// the op aborts here, before anything was mutated.
async fn mark(pool: &PgPool, person_table: &str, op: &OpRow) -> Result<(), SagaError> {
    let request = parse_request(op)?;
    let team_id = op.team_id as i32;
    let mut tx = pool.begin().await?;

    // Rows from a previous attempt of this op (crash between the insert and
    // the advance): whatever they claimed stays claimed.
    let existing: Vec<i64> = sqlx::query_scalar!(
        "SELECT person_id FROM lifecycle_op_person WHERE op_id = $1",
        op.op_id
    )
    .fetch_all(&mut *tx)
    .await?;

    // Sorted + deduped by the mark's conflict key so concurrent ops touching
    // the same persons take row locks in the same order.
    let mut to_claim: Vec<i64> = request
        .person_ids
        .iter()
        .copied()
        .filter(|id| !existing.contains(id))
        .collect();
    to_claim.sort_unstable();
    to_claim.dedup();

    let live_sql = format!(
        r#"
        SELECT id, uuid FROM {person_table}
        WHERE team_id = $1 AND id = ANY($2) AND is_deleted = false
        ORDER BY id
        "#
    );
    let live: Vec<(i64, Uuid)> = sqlx::query_as(&live_sql)
        .bind(team_id)
        .bind(&to_claim)
        .fetch_all(&mut *tx)
        .await?;
    let live_ids: Vec<i64> = live.iter().map(|(id, _)| *id).collect();
    let live_uuids: Vec<Uuid> = live.iter().map(|(_, uuid)| *uuid).collect();

    // The mark: inserting the row is claiming the person; a unique violation
    // on the partial mark index IS the conflict with another live op.
    let marked: Vec<i64> = sqlx::query_scalar!(
        r#"
        INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status)
        SELECT $1, $2, u.person_id, u.person_uuid, 'victim', $5
        FROM unnest($3::bigint[], $4::uuid[]) AS u(person_id, person_uuid)
        ON CONFLICT (team_id, person_id) WHERE status IN ('marked', 'sealed') DO NOTHING
        RETURNING person_id
        "#,
        op.op_id,
        team_id,
        &live_ids,
        &live_uuids,
        STATUS_MARKED,
    )
    .fetch_all(&mut *tx)
    .await?;

    // Victims another live op holds: record the skip (the status keeps the
    // row outside the mark index). ON CONFLICT on the primary key covers a
    // concurrent driver of this same op racing us to the insert.
    let conflicted_ids: Vec<i64> = live_ids
        .iter()
        .copied()
        .filter(|id| !marked.contains(id))
        .collect();
    let conflicted_uuids: Vec<Uuid> = live
        .iter()
        .filter(|(id, _)| conflicted_ids.contains(id))
        .map(|(_, uuid)| *uuid)
        .collect();
    if !conflicted_ids.is_empty() {
        sqlx::query!(
            r#"
            INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status)
            SELECT $1, $2, u.person_id, u.person_uuid, 'victim', $5
            FROM unnest($3::bigint[], $4::uuid[]) AS u(person_id, person_uuid)
            ON CONFLICT (op_id, person_id) DO NOTHING
            "#,
            op.op_id,
            team_id,
            &conflicted_ids,
            &conflicted_uuids,
            STATUS_SKIPPED_CONFLICT,
        )
        .execute(&mut *tx)
        .await?;
    }

    // The live filter above and the mark insert run in different
    // statement snapshots, so a merge can destroy a person between them
    // and the insert lands on a corpse. Remove such marks here, in the
    // same transaction: the person reports as not_found and is never
    // touched again. From here on the mark keeps every held person alive.
    let corpse_sql = format!(
        r#"
        DELETE FROM lifecycle_op_person lop
        WHERE lop.op_id = $1 AND lop.status = 'marked'
          AND NOT EXISTS (
              SELECT 1 FROM {person_table} p
              WHERE p.team_id = $2 AND p.id = lop.person_id AND p.is_deleted = false
          )
        "#
    );
    sqlx::query(&corpse_sql)
        .bind(op.op_id)
        .bind(team_id)
        .execute(&mut *tx)
        .await?;

    let claims: i64 = sqlx::query_scalar!(
        r#"
        SELECT count(*) as "count!" FROM lifecycle_op_person
        WHERE op_id = $1 AND status IN ('marked', 'sealed')
        "#,
        op.op_id
    )
    .fetch_one(&mut *tx)
    .await?;

    let mut abort_outcome: Option<Value> = None;
    let advanced = if claims == 0 {
        // Every requested person was conflicted or missing: nothing was (or
        // will be) mutated, so the op ends here as aborted.
        let outcome = build_outcome(&mut tx, op.op_id, &request.person_ids).await?;
        let advanced = complete_op_in_tx(
            &mut tx,
            op.op_id,
            DeleteStep::Started.as_str(),
            STEP_ABORTED,
            &outcome,
        )
        .await?;
        abort_outcome = Some(outcome);
        advanced
    } else {
        advance_step_in_tx(
            &mut tx,
            op.op_id,
            DeleteStep::Started.as_str(),
            DeleteStep::Marked.as_str(),
        )
        .await?
    };
    if !advanced {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    match abort_outcome {
        Some(outcome) => {
            record_transition(DeleteStep::Started.as_str(), STEP_ABORTED);
            record_outcomes(&outcome);
        }
        None => record_transition(DeleteStep::Started.as_str(), DeleteStep::Marked.as_str()),
    }
    Ok(())
}

/// `marked → sealed`: fence every victim's owning leader and
/// persist the exact sealed versions. The fences are the step's only
/// external effect and a same-op re-fence is a re-seal returning fresh
/// state, so the fan-out is safe to repeat; the sealed values and the step
/// CAS commit together afterwards. The sealed jsonb records `created_at`
/// (epoch milliseconds, as the leader seals it) alongside `version`; its
/// presence is what marks a victim as fenced when the release runs.
///
/// A victim the leader reports NOT_FOUND vanished between the claim
/// recheck and its fence (destroyed by another actor) — its mark row is
/// removed so it settles as `not_found`, mirroring the merge driver's
/// vanished-source handling. A definitive refusal propagates and parks the
/// op; unlike the merge driver's pre-flip abort, delete has no abort path
/// past `started`, and a parked delete is an operator signal, not a stuck
/// customer flow.
async fn seal(pool: &PgPool, leader: &dyn LifecycleLeader, op: &OpRow) -> Result<(), SagaError> {
    let victims = sqlx::query!(
        r#"
        SELECT person_id FROM lifecycle_op_person
        WHERE op_id = $1 AND status IN ('marked', 'sealed')
        ORDER BY person_id
        "#,
        op.op_id
    )
    .fetch_all(pool)
    .await?;

    let fence_calls: Vec<_> = victims
        .iter()
        .map(|victim| {
            let request = FencePersonRequest {
                team_id: op.team_id,
                person_id: victim.person_id,
                op_id: op.op_id.to_string(),
                op_type: LifecycleOpType::Delete.into(),
                // A delete has no creating event to name.
                creator_event_uuid: String::new(),
            };
            let person_id = victim.person_id;
            async move { (person_id, leader.fence_person(request).await) }
        })
        .collect();
    let fence_results: Vec<_> = stream::iter(fence_calls)
        .buffer_unordered(LEADER_CALL_CONCURRENCY)
        .collect()
        .await;

    let mut sealed_ids: Vec<i64> = Vec::with_capacity(fence_results.len());
    let mut sealed_versions: Vec<i64> = Vec::with_capacity(fence_results.len());
    let mut sealed_created_ats: Vec<i64> = Vec::with_capacity(fence_results.len());
    let mut vanished: Vec<i64> = Vec::new();
    for (person_id, result) in fence_results {
        match result {
            Ok(response) => {
                let sealed = response.sealed.ok_or_else(|| {
                    SagaError::CorruptState(format!(
                        "fence response for person {person_id} carries no sealed state"
                    ))
                })?;
                sealed_ids.push(person_id);
                sealed_versions.push(sealed.version);
                sealed_created_ats.push(sealed.created_at);
            }
            Err(status) if status.code() == Code::NotFound => {
                tracing::error!(
                    op_id = %op.op_id,
                    person_id,
                    "marked delete victim vanished before its fence; settling it as not_found"
                );
                vanished.push(person_id);
            }
            // A semantic refusal here would park the op holding the fences
            // already installed this round, with live marks the healer will
            // not clear. FencePerson mints no semantic refusal today; if
            // one is added, this driver needs an abort path first (see the
            // merge driver's abort_refused for the shape).
            Err(status) => return Err(SagaError::leader(status)),
        }
    }

    let mut tx = pool.begin().await?;
    sqlx::query!(
        r#"
        UPDATE lifecycle_op_person lop
        SET status = $2, sealed = jsonb_build_object('version', u.version, 'created_at', u.created_at)
        FROM unnest($3::bigint[], $4::bigint[], $5::bigint[]) AS u(person_id, version, created_at)
        WHERE lop.op_id = $1 AND lop.person_id = u.person_id
          AND lop.status IN ('marked', 'sealed')
        "#,
        op.op_id,
        STATUS_SEALED,
        &sealed_ids,
        &sealed_versions,
        &sealed_created_ats,
    )
    .execute(&mut *tx)
    .await?;
    if !vanished.is_empty() {
        sqlx::query!(
            r#"
            DELETE FROM lifecycle_op_person
            WHERE op_id = $1 AND person_id = ANY($2) AND status IN ('marked', 'sealed')
            "#,
            op.op_id,
            &vanished,
        )
        .execute(&mut *tx)
        .await?;
    }

    if !advance_step_in_tx(
        &mut tx,
        op.op_id,
        DeleteStep::Marked.as_str(),
        DeleteStep::Sealed.as_str(),
    )
    .await?
    {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    record_transition(DeleteStep::Marked.as_str(), DeleteStep::Sealed.as_str());
    Ok(())
}

/// `sealed → unmapped`: the destroying transaction. Tombstone the victims'
/// distinct-id rows (recording each new version in `moved`, in the same
/// commit that bumps them), clear cohort membership and feature-flag
/// hash-key overrides, and tombstone the person rows themselves — properties
/// scrubbed (the GDPR erasure; the retained uuid is not PII), version parked
/// at sealed + 1 so the tombstone outranks every write the old incarnation
/// ever produced. Revival (a later create on the same key) upserts above
/// this version.
async fn unmap(pool: &PgPool, tables: &IdentityTables, op: &OpRow) -> Result<(), SagaError> {
    let team_id = op.team_id as i32;
    let mut tx = pool.begin().await?;

    let mut victims: Vec<i64> = sqlx::query_scalar!(
        r#"
        SELECT person_id FROM lifecycle_op_person
        WHERE op_id = $1 AND status = 'sealed'
        "#,
        op.op_id
    )
    .fetch_all(&mut *tx)
    .await?;
    victims.sort_unstable();

    // Take every row lock this transaction will need up front, in id order,
    // before the multi-row updates below. Those statements acquire locks in
    // whatever order the query plan visits rows, and the writer's flush
    // upsert spans overlapping persons in one statement — uncontrolled
    // order on either side is a deadlock cycle waiting for load. Sorted
    // acquisition on both sides (the writer sorts its flush batches the
    // same way) makes a cycle impossible.
    let lock_persons_sql = format!(
        "SELECT id FROM {person_table} WHERE team_id = $1 AND id = ANY($2) ORDER BY id FOR UPDATE",
        person_table = tables.person,
    );
    sqlx::query(&lock_persons_sql)
        .bind(team_id)
        .bind(&victims)
        .execute(&mut *tx)
        .await?;
    let lock_pdi_sql = format!(
        "SELECT id FROM {pdi_table} WHERE team_id = $1 AND person_id = ANY($2) ORDER BY id FOR UPDATE",
        pdi_table = tables.person_distinct_id,
    );
    sqlx::query(&lock_pdi_sql)
        .bind(team_id)
        .bind(&victims)
        .execute(&mut *tx)
        .await?;

    let tombstone_pdi_sql = format!(
        r#"
        UPDATE {pdi_table}
        SET is_deleted = true, version = COALESCE(version, 0) + 1
        WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
        RETURNING person_id, distinct_id, version
        "#,
        pdi_table = tables.person_distinct_id,
    );
    let tombstoned: Vec<(i64, String, i64)> = sqlx::query_as(&tombstone_pdi_sql)
        .bind(team_id)
        .bind(&victims)
        .fetch_all(&mut *tx)
        .await?;

    // Record the tombstoned mappings per victim in the same commit — this is
    // what a later ClickHouse emission (or an operator) reads back.
    let mut moved_ids: Vec<i64> = Vec::new();
    let mut moved_json: Vec<Value> = Vec::new();
    for victim in &victims {
        let rows: Vec<Value> = tombstoned
            .iter()
            .filter(|(person_id, _, _)| person_id == victim)
            .map(|(_, distinct_id, version)| {
                serde_json::json!({"distinct_id": distinct_id, "version": version})
            })
            .collect();
        if !rows.is_empty() {
            moved_ids.push(*victim);
            moved_json.push(Value::Array(rows));
        }
    }
    if !moved_ids.is_empty() {
        sqlx::query!(
            r#"
            UPDATE lifecycle_op_person lop
            SET moved = u.moved
            FROM unnest($2::bigint[], $3::jsonb[]) AS u(person_id, moved)
            WHERE lop.op_id = $1 AND lop.person_id = u.person_id
            "#,
            op.op_id,
            &moved_ids,
            &moved_json,
        )
        .execute(&mut *tx)
        .await?;
    }

    // posthog_cohortpeople has no shadow mirror and no team_id column, so it
    // is only addressable by real posthog_person ids. On any other person
    // table the victim ids come from that table's own sequence and would
    // collide with unrelated persons' cohort rows — skip the clear entirely.
    if tables.person == "posthog_person" {
        sqlx::query!(
            "DELETE FROM posthog_cohortpeople WHERE person_id = ANY($1)",
            &victims
        )
        .execute(&mut *tx)
        .await?;
    }

    let delete_overrides_sql = format!(
        "DELETE FROM {} WHERE team_id = $1 AND person_id = ANY($2)",
        tables.ff_hash_key_override
    );
    sqlx::query(&delete_overrides_sql)
        .bind(team_id)
        .bind(&victims)
        .execute(&mut *tx)
        .await?;

    let tombstone_sql = format!(
        r#"
        UPDATE {person_table} p
        SET is_deleted = true,
            properties = '{{}}'::jsonb,
            properties_last_updated_at = '{{}}'::jsonb,
            properties_last_operation = '{{}}'::jsonb,
            version = (lop.sealed->>'version')::bigint + 1
        FROM lifecycle_op_person lop
        WHERE lop.op_id = $1 AND lop.status = 'sealed'
          AND p.team_id = $2 AND p.id = lop.person_id
        "#,
        person_table = tables.person,
    );
    sqlx::query(&tombstone_sql)
        .bind(op.op_id)
        .bind(team_id)
        .execute(&mut *tx)
        .await?;

    if !advance_step_in_tx(
        &mut tx,
        op.op_id,
        DeleteStep::Sealed.as_str(),
        DeleteStep::Unmapped.as_str(),
    )
    .await?
    {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    record_transition(DeleteStep::Sealed.as_str(), DeleteStep::Unmapped.as_str());
    Ok(())
}

/// `unmapped → completed`: release each fenced victim with the committed
/// outcome — the leader produces the death document into the changelog and
/// evicts its cache entry — then settle the per-person rows to `deleted`
/// (which releases their marks), record the outcome, and stamp completion.
///
/// The releases run before the settle transaction because the leader
/// verifies a committed release against a live mark (`marked`/`sealed`)
/// and fails closed without one; a mark already settled as `deleted`
/// absorbs a retried release without a second death document. Only victims
/// whose sealed jsonb carries `created_at` are released: that key exists
/// exactly when `FencePerson` sealed them, so an op sealed pre-fence (or
/// across a kill-switch flip) completes without phantom release calls.
async fn complete(
    pool: &PgPool,
    leader: &dyn LifecycleLeader,
    op: &OpRow,
) -> Result<(), SagaError> {
    let request = parse_request(op)?;

    let fenced = sqlx::query!(
        r#"
        SELECT person_id, person_uuid,
               (sealed->>'version')::bigint AS "sealed_version!",
               (sealed->>'created_at')::bigint AS "sealed_created_at!"
        FROM lifecycle_op_person
        WHERE op_id = $1 AND status = 'sealed' AND sealed ? 'created_at'
        ORDER BY person_id
        "#,
        op.op_id
    )
    .fetch_all(pool)
    .await?;
    let release_calls: Vec<_> = fenced
        .iter()
        .map(|victim| {
            let request = ReleaseFenceRequest {
                team_id: op.team_id,
                person_id: victim.person_id,
                person_uuid: victim.person_uuid.to_string(),
                op_id: op.op_id.to_string(),
                outcome: ReleaseOutcome::Committed.into(),
                sealed_version: Some(victim.sealed_version),
                created_at: victim.sealed_created_at,
            };
            async move { leader.release_fence(request).await }
        })
        .collect();
    let release_results: Vec<_> = stream::iter(release_calls)
        .buffer_unordered(LEADER_CALL_CONCURRENCY)
        .collect()
        .await;
    for result in release_results {
        result.map_err(SagaError::leader)?;
    }

    let mut tx = pool.begin().await?;

    sqlx::query!(
        "UPDATE lifecycle_op_person SET status = $2 WHERE op_id = $1 AND status = 'sealed'",
        op.op_id,
        STATUS_DELETED,
    )
    .execute(&mut *tx)
    .await?;

    let outcome = build_outcome(&mut tx, op.op_id, &request.person_ids).await?;
    if !complete_op_in_tx(
        &mut tx,
        op.op_id,
        DeleteStep::Unmapped.as_str(),
        STEP_COMPLETED,
        &outcome,
    )
    .await?
    {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    record_transition(DeleteStep::Unmapped.as_str(), STEP_COMPLETED);
    record_outcomes(&outcome);
    Ok(())
}

/// One outcome entry per requested person id, in request order, from the
/// per-person rows: `deleted` and `skipped_conflict` map to themselves; a
/// missing row means no live person existed at claim time (`not_found`).
/// A row still `marked`/`sealed` at completion should be unreachable and
/// reports `not_found`.
async fn build_outcome(
    tx: &mut Tx<'_>,
    op_id: Uuid,
    requested: &[i64],
) -> Result<Value, SagaError> {
    let rows = sqlx::query!(
        "SELECT person_id, status FROM lifecycle_op_person WHERE op_id = $1",
        op_id
    )
    .fetch_all(&mut **tx)
    .await?;

    let results = requested
        .iter()
        .map(|person_id| {
            let outcome = match rows.iter().find(|r| r.person_id == *person_id) {
                Some(row) if row.status == STATUS_DELETED => OUTCOME_DELETED,
                Some(row) if row.status == STATUS_SKIPPED_CONFLICT => OUTCOME_SKIPPED_CONFLICT,
                _ => OUTCOME_NOT_FOUND,
            };
            DeletePersonRecord {
                person_id: *person_id,
                outcome: outcome.to_string(),
            }
        })
        .collect();

    serde_json::to_value(DeleteOutcome { results })
        .map_err(|e| SagaError::CorruptState(format!("failed to serialize delete outcome: {e}")))
}
