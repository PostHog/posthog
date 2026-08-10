//! The delete saga's step handlers: `started → marked → sealed → unmapped →
//! completed`, with `aborted` reachable only from `started` (before anything
//! was mutated). Each step is one transaction that commits its work together
//! with the step advance — see the engine's correctness model.
//!
//! Pre-leader-fencing mode: the leader's `FencePerson` / `ReleaseFence` RPCs
//! have not landed yet, so this driver runs the saga without a fence.
//! Sealing reads the person's version from Postgres and adds
//! [`SEAL_VERSION_MARGIN`] (the same margin the legacy delete path uses) so
//! the death version outranks any write that lands between the seal and the
//! tombstone. The unmapped transaction writes the person tombstone directly
//! — once the leader produces death documents and the writer projects them
//! (RFC stages 6–7), that direct write becomes the fence-gated fallback and
//! the leader/writer path takes over ClickHouse emission. Until then the
//! distinct-id rows tombstoned by an op are recorded in each victim row's
//! `moved` column, so nothing needed for later emission is lost.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::postgres::PgPool;
use uuid::Uuid;

use personhog_proto::personhog::types::v1::LifecycleOpType;

use crate::lifecycle::engine::{
    advance_step_in_tx, complete_op_in_tx, OpDriver, OpRow, SagaError, Tx, STEP_ABORTED,
    STEP_COMPLETED,
};

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

/// Added to the person's Postgres version at seal time. Without a fence a
/// concurrent write can still bump the version between the seal and the
/// tombstone; the margin parks the death version far above anything such a
/// write can reach, exactly like the legacy delete path's +100. Once sealing
/// goes through `FencePerson` no write can follow the seal and the margin
/// can drop to zero.
pub const SEAL_VERSION_MARGIN: i64 = 100;

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

pub struct DeleteDriver;

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
            DeleteStep::Started => mark(pool, op).await,
            DeleteStep::Marked => seal(pool, op).await,
            DeleteStep::Sealed => unmap(pool, op).await,
            DeleteStep::Unmapped => complete(pool, op).await,
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
async fn mark(pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
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

    let live = sqlx::query!(
        r#"
        SELECT id, uuid FROM posthog_person
        WHERE team_id = $1 AND id = ANY($2) AND is_deleted = false
        ORDER BY id
        "#,
        team_id,
        &to_claim,
    )
    .fetch_all(&mut *tx)
    .await?;
    let live_ids: Vec<i64> = live.iter().map(|p| p.id).collect();
    let live_uuids: Vec<Uuid> = live.iter().map(|p| p.uuid).collect();

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
        .filter(|p| conflicted_ids.contains(&p.id))
        .map(|p| p.uuid)
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

/// `marked → sealed`: freeze each victim's final version. Pre-fence this
/// reads the version from Postgres and adds [`SEAL_VERSION_MARGIN`]; with
/// leader fencing (RFC stage 6) this becomes a `FencePerson` call per victim
/// and the sealed version is exact.
async fn seal(pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
    let team_id = op.team_id as i32;
    let mut tx = pool.begin().await?;

    sqlx::query!(
        r#"
        UPDATE lifecycle_op_person lop
        SET status = $3, sealed = jsonb_build_object('version', COALESCE(p.version, 0) + $4)
        FROM posthog_person p
        WHERE lop.op_id = $1 AND lop.status IN ('marked', 'sealed')
          AND p.team_id = $2 AND p.id = lop.person_id
        "#,
        op.op_id,
        team_id,
        STATUS_SEALED,
        SEAL_VERSION_MARGIN,
    )
    .execute(&mut *tx)
    .await?;

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
async fn unmap(pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
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

    let tombstoned = sqlx::query!(
        r#"
        UPDATE posthog_persondistinctid
        SET is_deleted = true, version = COALESCE(version, 0) + 1
        WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
        RETURNING person_id, distinct_id, version as "version!"
        "#,
        team_id,
        &victims,
    )
    .fetch_all(&mut *tx)
    .await?;

    // Record the tombstoned mappings per victim in the same commit — this is
    // what a later ClickHouse emission (or an operator) reads back.
    let mut moved_ids: Vec<i64> = Vec::new();
    let mut moved_json: Vec<Value> = Vec::new();
    for victim in &victims {
        let rows: Vec<Value> = tombstoned
            .iter()
            .filter(|r| r.person_id == *victim)
            .map(|r| serde_json::json!({"distinct_id": r.distinct_id, "version": r.version}))
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

    sqlx::query!(
        "DELETE FROM posthog_cohortpeople WHERE person_id = ANY($1)",
        &victims
    )
    .execute(&mut *tx)
    .await?;

    sqlx::query!(
        "DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = ANY($2)",
        team_id,
        &victims
    )
    .execute(&mut *tx)
    .await?;

    sqlx::query!(
        r#"
        UPDATE posthog_person p
        SET is_deleted = true,
            properties = '{}'::jsonb,
            properties_last_updated_at = '{}'::jsonb,
            properties_last_operation = '{}'::jsonb,
            version = (lop.sealed->>'version')::bigint + 1
        FROM lifecycle_op_person lop
        WHERE lop.op_id = $1 AND lop.status = 'sealed'
          AND p.team_id = $2 AND p.id = lop.person_id
        "#,
        op.op_id,
        team_id,
    )
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

/// `unmapped → completed`: settle the per-person rows to `deleted` (which
/// releases their marks), record the outcome, and stamp completion. With
/// leader fencing (RFC stage 6) the per-victim `ReleaseFence(committed)`
/// calls — the leader producing each death document — happen before this
/// transaction.
async fn complete(pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
    let request = parse_request(op)?;
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
/// missing row means no live person existed at mark time (`not_found`). A
/// row still `marked`/`sealed` at completion means the person row vanished
/// under us mid-saga — impossible while the saga is the only deleter (the
/// per-team exclusivity rollout) — and is reported `not_found`.
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
