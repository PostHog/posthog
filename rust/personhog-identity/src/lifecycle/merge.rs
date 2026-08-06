//! The merge saga's step handlers: `started → claimed → sources_sealed →
//! document_folded → flipped → completed`, with `aborted` reachable only
//! from the claim and seal handlers (before anything was mutated). Each
//! step commits its Postgres work together with the step advance — see the
//! engine's correctness model — and every leader call (fence, fold,
//! release) is convergent under repetition, which is what keeps the steps
//! safe to re-run even though those calls cannot roll back with a lost CAS.
//!
//! The driver receives the classified case-3 set of a MergePersons call:
//! source distinct ids that resolved to persons distinct from the target.
//! The claim step re-resolves everything authoritatively — the handler's
//! classification is advisory, and the world can change between the two.
//!
//! Durable per-op state beyond the step column lives on the op's
//! `lifecycle_op_person` rows. The target row's JSONB columns are
//! deliberately repurposed as the op's scratch anchor — a target's dids
//! never move (`moved` is free) and a target is never fenced (`sealed` is
//! free): `moved` holds the per-did claim dispositions, `sealed` holds the
//! folded survivor document. Sources use the columns as the schema
//! intends: `sealed` freezes the fence snapshot, `moved` records the
//! repointed mapping rows for later ClickHouse emission (delete parity).
//!
//! Known residual (pending the revival/birth-document RFC stage): the
//! death documents this saga has the leader produce stay in the leader's
//! cache as authoritative not-found entries, and a later Postgres revival
//! of the same person key (the stub-create conflict path) never notifies
//! the leader — until eviction or a partition handoff, the revived person
//! answers NOT_FOUND at the leader, and a merge claiming it mis-drops it
//! as vanished. Closed when revival produces a birth document through the
//! leader like every other creation.

use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;
use futures::future::join_all;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::postgres::PgPool;
use tonic::Code;
use uuid::Uuid;

use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FoldPersonDocumentRequest, LifecycleOpType, Person, ReleaseFenceRequest,
    ReleaseOutcome,
};

use crate::leader::LifecycleLeader;
use crate::lifecycle::engine::{
    advance_step_in_tx, complete_op_in_tx, OpDriver, OpRow, SagaError, Tx, STEP_ABORTED,
    STEP_COMPLETED,
};

// Derived from the shared enum so the op-type string cannot drift from
// the leader's fence records or the lifecycle_op CHECK constraint.
pub const OP_TYPE_MERGE: &str = LifecycleOpType::Merge.as_op_type_str();

/// The merge saga's non-terminal steps, in order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeStep {
    Started,
    Claimed,
    SourcesSealed,
    DocumentFolded,
    Flipped,
}

impl MergeStep {
    pub fn as_str(self) -> &'static str {
        match self {
            MergeStep::Started => "started",
            MergeStep::Claimed => "claimed",
            MergeStep::SourcesSealed => "sources_sealed",
            MergeStep::DocumentFolded => "document_folded",
            MergeStep::Flipped => "flipped",
        }
    }

    fn parse(step: &str) -> Option<Self> {
        match step {
            "started" => Some(MergeStep::Started),
            "claimed" => Some(MergeStep::Claimed),
            "sources_sealed" => Some(MergeStep::SourcesSealed),
            "document_folded" => Some(MergeStep::DocumentFolded),
            "flipped" => Some(MergeStep::Flipped),
            _ => None,
        }
    }
}

/// The frozen `lifecycle_op.request` payload for a merge op: the case-3
/// set the handler classified, plus the merge event's property payloads.
/// `sources` order is property precedence (earlier beats later).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeRequest {
    pub target_distinct_id: String,
    pub sources: Vec<MergeSourceEntry>,
    #[serde(default)]
    pub event_set: Value,
    #[serde(default)]
    pub event_set_once: Value,
    /// `$merge_dangerously` legally merges identified sources; `$identify`
    /// does not.
    #[serde(default)]
    pub allow_identified_sources: bool,
    /// Per-source distinct-id count guard. Absent = unlimited.
    #[serde(default)]
    pub move_limit: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeSourceEntry {
    pub distinct_id: String,
    /// The `$identify` event that contributed this pair; carried for the
    /// caller's warning correlation, unused by the saga itself.
    #[serde(default)]
    pub event_uuid: String,
}

/// The recorded `lifecycle_op.outcome` payload: one entry per requested
/// source distinct id, in request order, plus the survivor document when
/// the merge committed.
#[derive(Debug, Serialize, Deserialize)]
pub struct MergeOutcome {
    pub aborted: bool,
    /// The folded survivor document (id, uuid, properties, created_at,
    /// is_identified, version). Absent when the op aborted.
    pub survivor: Option<Value>,
    pub results: Vec<MergeSourceRecord>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct MergeSourceRecord {
    pub distinct_id: String,
    pub outcome: String,
}

pub const OUTCOME_MERGED: &str = "merged";
pub const OUTCOME_NOOP_SAME_PERSON: &str = "noop_same_person";
pub const OUTCOME_SKIPPED_ALREADY_IDENTIFIED: &str = "skipped_already_identified";
pub const OUTCOME_SKIPPED_CONFLICT: &str = "skipped_conflict";
pub const OUTCOME_SKIPPED_MOVE_LIMIT: &str = "skipped_move_limit";
pub const OUTCOME_ERROR: &str = "error";

/// Per-person row statuses this driver writes. `marked`/`sealed` are the
/// mark-covered set (the partial unique index); everything else releases
/// the mark. `dropped` and `aborted` are merge-specific settlements the
/// schema comment does not list — the column is unconstrained TEXT and the
/// mark index only cares that they are outside `('marked','sealed')`.
const STATUS_MARKED: &str = "marked";
const STATUS_SEALED: &str = "sealed";
const STATUS_DELETED: &str = "deleted";
const STATUS_CLEARED: &str = "cleared";
const STATUS_DROPPED: &str = "dropped";
const STATUS_ABORTED: &str = "aborted";
const STATUS_SKIPPED_CONFLICT: &str = "skipped_conflict";

const ROLE_TARGET: &str = "target";
const ROLE_SOURCE: &str = "source";

const STEPS_TOTAL: &str = "personhog_lifecycle_merge_steps_total";
const OUTCOMES_TOTAL: &str = "personhog_lifecycle_merge_outcomes_total";

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

fn record_outcomes(outcome: &Value) {
    let Ok(parsed) = serde_json::from_value::<MergeOutcome>(outcome.clone()) else {
        return;
    };
    for label in [
        OUTCOME_MERGED,
        OUTCOME_NOOP_SAME_PERSON,
        OUTCOME_SKIPPED_ALREADY_IDENTIFIED,
        OUTCOME_SKIPPED_CONFLICT,
        OUTCOME_SKIPPED_MOVE_LIMIT,
        OUTCOME_ERROR,
    ] {
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

/// One requested source did's claim-time decision, persisted in the target
/// row's `moved` column so the terminal outcome can be rebuilt after any
/// crash. `pending_merge` resolves to `merged` (row settled `deleted`) or
/// to the drop reason recorded when the source fell out.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Disposition {
    distinct_id: String,
    /// The person the did resolved to at claim time; absent when it
    /// resolved to nothing.
    person_id: Option<i64>,
    decision: String,
}

const DECISION_PENDING_MERGE: &str = "pending_merge";

#[derive(Debug, Serialize, Deserialize)]
struct ClaimRecord {
    dispositions: Vec<Disposition>,
}

/// The fence snapshot persisted per source row (`sealed`), and the exact
/// inputs the fold and the committed release replay from. `created_at` is
/// in the unit `Person.created_at` carries (epoch seconds today).
#[derive(Debug, Clone, Serialize, Deserialize)]
struct SealedSnapshot {
    version: i64,
    created_at: i64,
    is_identified: bool,
    properties: Value,
}

pub struct MergeDriver {
    leader: Arc<dyn LifecycleLeader>,
}

impl MergeDriver {
    pub fn new(leader: Arc<dyn LifecycleLeader>) -> Self {
        Self { leader }
    }
}

#[async_trait]
impl OpDriver for MergeDriver {
    fn op_type(&self) -> &'static str {
        OP_TYPE_MERGE
    }

    fn initial_step(&self) -> &'static str {
        MergeStep::Started.as_str()
    }

    async fn run_step(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let step = MergeStep::parse(&op.step).ok_or_else(|| {
            SagaError::CorruptState(format!(
                "merge op {} is on unknown step '{}'",
                op.op_id, op.step
            ))
        })?;
        match step {
            MergeStep::Started => self.claim(pool, op).await,
            MergeStep::Claimed => self.seal(pool, op).await,
            MergeStep::SourcesSealed => self.fold(pool, op).await,
            MergeStep::DocumentFolded => flip(pool, op).await,
            MergeStep::Flipped => self.complete(pool, op).await,
        }
    }
}

fn parse_request(op: &OpRow) -> Result<MergeRequest, SagaError> {
    serde_json::from_value(op.request.clone()).map_err(|e| {
        SagaError::CorruptState(format!(
            "merge op {} has a malformed request: {e}",
            op.op_id
        ))
    })
}

/// A did's resolution on the primary: the live person its live mapping row
/// points at.
struct Resolution {
    person_id: i64,
    person_uuid: Uuid,
    is_identified: bool,
}

async fn resolve_dids(
    tx: &mut Tx<'_>,
    team_id: i32,
    dids: &[String],
) -> Result<HashMap<String, Resolution>, SagaError> {
    let rows = sqlx::query!(
        r#"
        SELECT d.distinct_id, d.person_id as "person_id!", p.uuid as "person_uuid!",
               p.is_identified as "is_identified!"
        FROM posthog_persondistinctid d
        JOIN posthog_person p ON p.team_id = d.team_id AND p.id = d.person_id
        WHERE d.team_id = $1 AND d.distinct_id = ANY($2)
          AND d.is_deleted = false AND p.is_deleted = false
        "#,
        team_id,
        dids,
    )
    .fetch_all(&mut **tx)
    .await?;
    Ok(rows
        .into_iter()
        .map(|r| {
            (
                r.distinct_id,
                Resolution {
                    person_id: r.person_id,
                    person_uuid: r.person_uuid,
                    is_identified: r.is_identified,
                },
            )
        })
        .collect())
}

impl MergeDriver {
    /// `started → claimed` (or `→ aborted`): re-resolve authoritatively,
    /// classify every source did, and claim the target plus every
    /// still-mergeable source person via the mark index — all in one
    /// transaction. Nothing outside this op's own rows is mutated, so the
    /// abort branch can end the op in the same commit.
    async fn claim(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let request = parse_request(op)?;
        let team_id = op.team_id as i32;
        let mut tx = pool.begin().await?;

        // Authoritative resolution: the handler's classification aged while
        // the op row traveled here.
        let mut all_dids: Vec<String> = Vec::with_capacity(request.sources.len() + 1);
        all_dids.push(request.target_distinct_id.clone());
        all_dids.extend(request.sources.iter().map(|s| s.distinct_id.clone()));
        all_dids.sort_unstable();
        all_dids.dedup();
        let resolved = resolve_dids(&mut tx, team_id, &all_dids).await?;

        let Some(target) = resolved.get(&request.target_distinct_id) else {
            // The target person vanished between classification and now. The
            // caller's re-drive (new op) re-classifies; this op has changed
            // nothing.
            let dispositions = request
                .sources
                .iter()
                .map(|s| Disposition {
                    distinct_id: s.distinct_id.clone(),
                    person_id: None,
                    decision: OUTCOME_SKIPPED_CONFLICT.to_string(),
                })
                .collect();
            return abort_in_claim_tx(tx, op, dispositions).await;
        };
        let (target_person_id, target_person_uuid) = (target.person_id, target.person_uuid);

        // Classify each source did; collect the distinct persons to claim.
        // Two dids resolving to one person share a claim (first ordinal
        // wins the row's ordinal; both dids ride its fate).
        let mut dispositions: Vec<Disposition> = Vec::with_capacity(request.sources.len());
        let mut claim_persons: Vec<(i64, Uuid, i32)> = Vec::new();
        for (ordinal, source) in request.sources.iter().enumerate() {
            let Some(resolution) = resolved.get(&source.distinct_id) else {
                // Consumed by another lifecycle op (or never existed): a
                // retryable signal — the caller's re-drive re-classifies it.
                dispositions.push(Disposition {
                    distinct_id: source.distinct_id.clone(),
                    person_id: None,
                    decision: OUTCOME_SKIPPED_CONFLICT.to_string(),
                });
                continue;
            };
            if resolution.person_id == target_person_id {
                dispositions.push(Disposition {
                    distinct_id: source.distinct_id.clone(),
                    person_id: Some(resolution.person_id),
                    decision: OUTCOME_NOOP_SAME_PERSON.to_string(),
                });
                continue;
            }
            if resolution.is_identified && !request.allow_identified_sources {
                // Cheap Postgres pre-filter; the authoritative re-check runs
                // on the sealed state (Postgres lags the leader, and
                // is_identified only ever flips true, so this can only
                // under-drop, never over-drop).
                dispositions.push(Disposition {
                    distinct_id: source.distinct_id.clone(),
                    person_id: Some(resolution.person_id),
                    decision: OUTCOME_SKIPPED_ALREADY_IDENTIFIED.to_string(),
                });
                continue;
            }
            if !claim_persons
                .iter()
                .any(|(id, _, _)| *id == resolution.person_id)
            {
                claim_persons.push((resolution.person_id, resolution.person_uuid, ordinal as i32));
            }
            dispositions.push(Disposition {
                distinct_id: source.distinct_id.clone(),
                person_id: Some(resolution.person_id),
                decision: DECISION_PENDING_MERGE.to_string(),
            });
        }

        // The move-limit guard: a source with more distinct ids than the
        // caller's limit is skipped, not chunked — the caller applies its
        // merge-mode policy to the skip.
        if let Some(limit) = request.move_limit {
            let candidate_ids: Vec<i64> = claim_persons.iter().map(|(id, _, _)| *id).collect();
            let counts = sqlx::query!(
                r#"
                SELECT person_id as "person_id!", count(*) as "count!"
                FROM posthog_persondistinctid
                WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
                GROUP BY person_id
                "#,
                team_id,
                &candidate_ids,
            )
            .fetch_all(&mut *tx)
            .await?;
            let over: Vec<i64> = counts
                .iter()
                .filter(|c| c.count > limit)
                .map(|c| c.person_id)
                .collect();
            if !over.is_empty() {
                claim_persons.retain(|(id, _, _)| !over.contains(id));
                for d in dispositions.iter_mut() {
                    if d.decision == DECISION_PENDING_MERGE
                        && d.person_id.is_some_and(|id| over.contains(&id))
                    {
                        d.decision = OUTCOME_SKIPPED_MOVE_LIMIT.to_string();
                    }
                }
            }
        }

        // The mark: one sorted insert covering the target and every source
        // person, so concurrent ops touching the same persons take row
        // locks in the same order. Inserting is claiming; a unique
        // violation on the partial mark index IS the conflict.
        let mut rows: Vec<(i64, Uuid, &str, Option<i32>)> = claim_persons
            .iter()
            .map(|(id, uuid, ordinal)| (*id, *uuid, ROLE_SOURCE, Some(*ordinal)))
            .collect();
        rows.push((target_person_id, target_person_uuid, ROLE_TARGET, None));
        rows.sort_unstable_by_key(|(id, _, _, _)| *id);
        let ids: Vec<i64> = rows.iter().map(|r| r.0).collect();
        let uuids: Vec<Uuid> = rows.iter().map(|r| r.1).collect();
        let roles: Vec<String> = rows.iter().map(|r| r.2.to_string()).collect();
        let ordinals: Vec<Option<i32>> = rows.iter().map(|r| r.3).collect();

        let marked: Vec<i64> = sqlx::query_scalar!(
            r#"
            INSERT INTO lifecycle_op_person
                (op_id, team_id, person_id, person_uuid, role, ordinal, status)
            SELECT $1, $2, u.person_id, u.person_uuid, u.role, u.ordinal, $6
            FROM unnest($3::bigint[], $4::uuid[], $5::text[], $7::int[])
                AS u(person_id, person_uuid, role, ordinal)
            ON CONFLICT (team_id, person_id) WHERE status IN ('marked', 'sealed') DO NOTHING
            RETURNING person_id
            "#,
            op.op_id,
            team_id,
            &ids,
            &uuids,
            roles.as_slice(),
            STATUS_MARKED,
            ordinals.as_slice() as _,
        )
        .fetch_all(&mut *tx)
        .await?;

        if !marked.contains(&target_person_id) {
            // Another live op holds the target: abort. Flip whatever this
            // insert claimed back out of the mark set in the same commit —
            // nothing outside our rows has happened.
            sqlx::query!(
                "UPDATE lifecycle_op_person SET status = $2 WHERE op_id = $1 AND status = $3",
                op.op_id,
                STATUS_ABORTED,
                STATUS_MARKED,
            )
            .execute(&mut *tx)
            .await?;
            for d in dispositions.iter_mut() {
                if d.decision == DECISION_PENDING_MERGE {
                    d.decision = OUTCOME_SKIPPED_CONFLICT.to_string();
                }
            }
            return abort_in_claim_tx(tx, op, dispositions).await;
        }

        // Sources another live op holds: record the skip (the status keeps
        // the row outside the mark index). ON CONFLICT on the primary key
        // covers a concurrent driver of this same op racing us.
        let conflicted: Vec<(i64, Uuid)> = claim_persons
            .iter()
            .filter(|(id, _, _)| !marked.contains(id))
            .map(|(id, uuid, _)| (*id, *uuid))
            .collect();
        if !conflicted.is_empty() {
            let conflicted_ids: Vec<i64> = conflicted.iter().map(|c| c.0).collect();
            let conflicted_uuids: Vec<Uuid> = conflicted.iter().map(|c| c.1).collect();
            sqlx::query!(
                r#"
                INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, status)
                SELECT $1, $2, u.person_id, u.person_uuid, $5, $6
                FROM unnest($3::bigint[], $4::uuid[]) AS u(person_id, person_uuid)
                ON CONFLICT (op_id, person_id) DO NOTHING
                "#,
                op.op_id,
                team_id,
                &conflicted_ids,
                &conflicted_uuids,
                ROLE_SOURCE,
                STATUS_SKIPPED_CONFLICT,
            )
            .execute(&mut *tx)
            .await?;
            for d in dispositions.iter_mut() {
                if d.decision == DECISION_PENDING_MERGE
                    && d.person_id.is_some_and(|id| conflicted_ids.contains(&id))
                {
                    d.decision = OUTCOME_SKIPPED_CONFLICT.to_string();
                }
            }
        }

        // Post-insert liveness recheck. The resolve above and the insert run
        // in different statement snapshots, so a destroyer that tombstoned a
        // person and settled its mark between them makes our insert succeed
        // on a corpse. One fresh statement re-verifies person liveness and
        // mapping stability; after it, mark + liveness hold in one snapshot
        // and nothing can destroy or re-map a claimed person (the mark
        // blocks every lifecycle op and identity mutation).
        let fresh = resolve_dids(&mut tx, team_id, &all_dids).await?;
        let target_still_live = fresh
            .get(&request.target_distinct_id)
            .is_some_and(|r| r.person_id == target_person_id);
        if !target_still_live {
            sqlx::query!(
                "UPDATE lifecycle_op_person SET status = $2 WHERE op_id = $1 AND status = $3",
                op.op_id,
                STATUS_ABORTED,
                STATUS_MARKED,
            )
            .execute(&mut *tx)
            .await?;
            for d in dispositions.iter_mut() {
                if d.decision == DECISION_PENDING_MERGE {
                    d.decision = OUTCOME_SKIPPED_CONFLICT.to_string();
                }
            }
            return abort_in_claim_tx(tx, op, dispositions).await;
        }
        let mut dropped: Vec<i64> = Vec::new();
        for (person_id, _, _) in &claim_persons {
            if !marked.contains(person_id) {
                continue;
            }
            let still_reachable = dispositions.iter().any(|d| {
                d.decision == DECISION_PENDING_MERGE
                    && d.person_id == Some(*person_id)
                    && fresh
                        .get(&d.distinct_id)
                        .is_some_and(|r| r.person_id == *person_id)
            });
            if !still_reachable {
                dropped.push(*person_id);
            }
        }
        if !dropped.is_empty() {
            sqlx::query!(
                r#"
                UPDATE lifecycle_op_person SET status = $2
                WHERE op_id = $1 AND person_id = ANY($3) AND status = $4
                "#,
                op.op_id,
                STATUS_DROPPED,
                &dropped,
                STATUS_MARKED,
            )
            .execute(&mut *tx)
            .await?;
            for d in dispositions.iter_mut() {
                if d.decision == DECISION_PENDING_MERGE
                    && d.person_id.is_some_and(|id| dropped.contains(&id))
                {
                    d.decision = OUTCOME_SKIPPED_CONFLICT.to_string();
                }
            }
        }

        if !dispositions
            .iter()
            .any(|d| d.decision == DECISION_PENDING_MERGE)
        {
            // Every source fell out: release the target's just-taken mark
            // and end the op. No fences exist yet.
            sqlx::query!(
                r#"
                UPDATE lifecycle_op_person SET status = $2
                WHERE op_id = $1 AND role = $3 AND status = $4
                "#,
                op.op_id,
                STATUS_CLEARED,
                ROLE_TARGET,
                STATUS_MARKED,
            )
            .execute(&mut *tx)
            .await?;
            return abort_in_claim_tx(tx, op, dispositions).await;
        }

        // Persist the claim record on the target row; the terminal outcome
        // is rebuilt from it after any crash.
        let claim_record = serde_json::to_value(ClaimRecord { dispositions }).map_err(|e| {
            SagaError::CorruptState(format!("failed to serialize claim record: {e}"))
        })?;
        sqlx::query!(
            "UPDATE lifecycle_op_person SET moved = $2 WHERE op_id = $1 AND role = $3",
            op.op_id,
            claim_record,
            ROLE_TARGET,
        )
        .execute(&mut *tx)
        .await?;

        if !advance_step_in_tx(
            &mut tx,
            op.op_id,
            MergeStep::Started.as_str(),
            MergeStep::Claimed.as_str(),
        )
        .await?
        {
            tx.rollback().await?;
            return Ok(());
        }
        tx.commit().await?;
        record_transition(MergeStep::Started.as_str(), MergeStep::Claimed.as_str());
        Ok(())
    }

    /// `claimed → sources_sealed` (or `→ aborted`): fence every claimed
    /// source's owning leader and persist the sealed snapshots. The fences
    /// are the step's only external effect and re-fencing with the same
    /// op_id is a re-seal returning identical state (the fence itself
    /// froze the person), so the fan-out is safe to repeat; the snapshots
    /// and the step CAS commit together afterwards.
    ///
    /// Known residual: a stale duplicate driver can re-fence a source the
    /// winner already dropped (its settling TX loses the CAS, but its
    /// fence call does not roll back). No later step releases a dropped
    /// source, so the orphan clears via the leader's ghost-fence healer on
    /// the next rejected write (or a partition handoff) — the same class
    /// the takeover scan can mint, bounded the same way.
    async fn seal(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let request = parse_request(op)?;
        let sources = sqlx::query!(
            r#"
            SELECT person_id, person_uuid FROM lifecycle_op_person
            WHERE op_id = $1 AND role = $2 AND status IN ('marked', 'sealed')
            "#,
            op.op_id,
            ROLE_SOURCE,
        )
        .fetch_all(pool)
        .await?;

        let mut sealed: Vec<(i64, SealedSnapshot)> = Vec::new();
        let mut vanished: Vec<i64> = Vec::new();
        let fence_calls: Vec<_> = sources
            .iter()
            .map(|source| {
                let leader = Arc::clone(&self.leader);
                let request = FencePersonRequest {
                    team_id: op.team_id,
                    person_id: source.person_id,
                    op_id: op.op_id.to_string(),
                    op_type: LifecycleOpType::Merge.into(),
                };
                let person_id = source.person_id;
                async move { (person_id, leader.fence_person(request).await) }
            })
            .collect();
        for (person_id, result) in join_all(fence_calls).await {
            match result {
                Ok(response) => {
                    let person = response.sealed.ok_or_else(|| {
                        SagaError::CorruptState(format!(
                            "fence response for person {person_id} carries no sealed state"
                        ))
                    })?;
                    sealed.push((person_id, snapshot_from_sealed(&person)?));
                }
                Err(status) if status.code() == Code::NotFound => {
                    // Unreachable while the mark holds (the claim recheck
                    // closed the pre-mark race), so a hit here is an
                    // anomaly worth shouting about — but dropping the
                    // source is still the correct settlement: it no longer
                    // exists, and no fence was installed.
                    tracing::error!(
                        op_id = %op.op_id,
                        person_id,
                        "marked merge source vanished before its fence; dropping it"
                    );
                    vanished.push(person_id);
                }
                Err(status) => {
                    // Fenced-by-another-op can only be a ghost fence (a
                    // real foreign op would need a live mark we hold); the
                    // leader's healer clears it on observation. Every
                    // failure here retries the step.
                    return Err(SagaError::Leader(Box::new(status)));
                }
            }
        }

        // The authoritative is_identified check, on the sealed state the
        // fold would consume. An identified source drops out; its fence is
        // released (produce nothing) before its mark settles below.
        let mut identified: Vec<i64> = Vec::new();
        if !request.allow_identified_sources {
            let (keep, drop_identified): (Vec<_>, Vec<_>) = sealed
                .into_iter()
                .partition(|(_, snapshot)| !snapshot.is_identified);
            sealed = keep;
            identified = drop_identified.iter().map(|(id, _)| *id).collect();
            let identified_pairs: Vec<(i64, Uuid)> = sources
                .iter()
                .filter(|s| identified.contains(&s.person_id))
                .map(|s| (s.person_id, s.person_uuid))
                .collect();
            self.release_fences(op, &identified_pairs).await?;
        }

        if sealed.is_empty() {
            // Every source fell out between claim and seal: abort. Fences
            // for remaining marked sources were never installed (vanished)
            // or already released (identified); release again vacuously for
            // crash-resilience, then settle the rows.
            let remaining: Vec<(i64, Uuid)> = sources
                .iter()
                .map(|s| (s.person_id, s.person_uuid))
                .collect();
            self.release_fences(op, &remaining).await?;
            let mut tx = pool.begin().await?;
            settle_drops(&mut tx, op, &vanished, &identified).await?;
            sqlx::query!(
                r#"
                UPDATE lifecycle_op_person SET status = $2
                WHERE op_id = $1 AND role = $3 AND status IN ('marked', 'sealed')
                "#,
                op.op_id,
                STATUS_ABORTED,
                ROLE_SOURCE,
            )
            .execute(&mut *tx)
            .await?;
            sqlx::query!(
                "UPDATE lifecycle_op_person SET status = $2 WHERE op_id = $1 AND role = $3",
                op.op_id,
                STATUS_CLEARED,
                ROLE_TARGET,
            )
            .execute(&mut *tx)
            .await?;
            let outcome = build_outcome(&mut tx, op, true).await?;
            if !complete_op_in_tx(
                &mut tx,
                op.op_id,
                MergeStep::Claimed.as_str(),
                STEP_ABORTED,
                &outcome,
            )
            .await?
            {
                tx.rollback().await?;
                return Ok(());
            }
            tx.commit().await?;
            record_transition(MergeStep::Claimed.as_str(), STEP_ABORTED);
            record_outcomes(&outcome);
            return Ok(());
        }

        let mut tx = pool.begin().await?;
        settle_drops(&mut tx, op, &vanished, &identified).await?;
        let sealed_ids: Vec<i64> = sealed.iter().map(|(id, _)| *id).collect();
        let sealed_jsons: Vec<Value> = sealed
            .iter()
            .map(|(_, snapshot)| serde_json::to_value(snapshot))
            .collect::<Result<_, _>>()
            .map_err(|e| SagaError::CorruptState(format!("failed to serialize seal: {e}")))?;
        sqlx::query!(
            r#"
            UPDATE lifecycle_op_person lop
            SET status = $4, sealed = u.sealed
            FROM unnest($2::bigint[], $3::jsonb[]) AS u(person_id, sealed)
            WHERE lop.op_id = $1 AND lop.person_id = u.person_id
              AND lop.status IN ('marked', 'sealed')
            "#,
            op.op_id,
            &sealed_ids,
            &sealed_jsons,
            STATUS_SEALED,
        )
        .execute(&mut *tx)
        .await?;

        if !advance_step_in_tx(
            &mut tx,
            op.op_id,
            MergeStep::Claimed.as_str(),
            MergeStep::SourcesSealed.as_str(),
        )
        .await?
        {
            tx.rollback().await?;
            return Ok(());
        }
        tx.commit().await?;
        record_transition(
            MergeStep::Claimed.as_str(),
            MergeStep::SourcesSealed.as_str(),
        );
        Ok(())
    }

    /// `sources_sealed → document_folded`: one FoldPersonDocument call to
    /// the target's leader with the sealed snapshots in precedence order.
    /// A re-driven fold on unchanged target state changes no content and
    /// only bumps the version, so a crash between the fold and the CAS is
    /// absorbed — up to the accepted re-appliable-merge residual: the
    /// target is never fenced, so a re-fold recomputes over writes that
    /// landed in between (see FoldPersonDocumentRequest.op_id in the
    /// proto). The folded document persists on the target row: the
    /// terminal outcome's survivor, durable without ever re-folding.
    async fn fold(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let request = parse_request(op)?;
        let target = target_row(pool, op).await?;
        let sources = sqlx::query!(
            r#"
            SELECT person_id, sealed as "sealed!" FROM lifecycle_op_person
            WHERE op_id = $1 AND role = $2 AND status = $3
            ORDER BY ordinal
            "#,
            op.op_id,
            ROLE_SOURCE,
            STATUS_SEALED,
        )
        .fetch_all(pool)
        .await?;

        let mut snapshots: Vec<Person> = Vec::with_capacity(sources.len());
        for source in &sources {
            let snapshot: SealedSnapshot =
                serde_json::from_value(source.sealed.clone()).map_err(|e| {
                    SagaError::CorruptState(format!(
                        "merge op {} source {} has a malformed seal: {e}",
                        op.op_id, source.person_id
                    ))
                })?;
            snapshots.push(Person {
                properties: serde_json::to_vec(&snapshot.properties).map_err(|e| {
                    SagaError::CorruptState(format!("failed to serialize seal properties: {e}"))
                })?,
                version: snapshot.version,
                created_at: snapshot.created_at,
                is_identified: snapshot.is_identified,
                ..Default::default()
            });
        }

        let response = self
            .leader
            .fold_person_document(FoldPersonDocumentRequest {
                team_id: op.team_id,
                person_id: target.person_id,
                sealed_snapshots: snapshots,
                event_set: encode_json_map(&request.event_set)?,
                event_set_once: encode_json_map(&request.event_set_once)?,
                op_id: op.op_id.to_string(),
            })
            .await
            .map_err(|status| SagaError::Leader(Box::new(status)))?;
        let folded = response.person.ok_or_else(|| {
            SagaError::CorruptState(format!(
                "fold response for merge op {} carries no document",
                op.op_id
            ))
        })?;
        let survivor = serde_json::json!({
            "id": folded.id,
            "uuid": folded.uuid,
            "properties": serde_json::from_slice::<Value>(&folded.properties)
                .unwrap_or_else(|_| Value::Object(serde_json::Map::new())),
            "created_at": folded.created_at,
            "is_identified": folded.is_identified,
            "version": folded.version,
        });

        let mut tx = pool.begin().await?;
        sqlx::query!(
            "UPDATE lifecycle_op_person SET sealed = $2 WHERE op_id = $1 AND role = $3",
            op.op_id,
            survivor,
            ROLE_TARGET,
        )
        .execute(&mut *tx)
        .await?;
        if !advance_step_in_tx(
            &mut tx,
            op.op_id,
            MergeStep::SourcesSealed.as_str(),
            MergeStep::DocumentFolded.as_str(),
        )
        .await?
        {
            tx.rollback().await?;
            return Ok(());
        }
        tx.commit().await?;
        record_transition(
            MergeStep::SourcesSealed.as_str(),
            MergeStep::DocumentFolded.as_str(),
        );
        Ok(())
    }

    /// `flipped → completed`: release every source fence with outcome
    /// committed — the leader verifies the live mark and produces each
    /// death document — then settle the rows and record the outcome. The
    /// order is load-bearing: the mark flip to `deleted` must follow the
    /// release ack, because to the leader a `deleted` mark means "the
    /// death document already exists; absorb the retry". Flipping first
    /// would make the first-ever release absorb and never produce.
    async fn complete(&self, pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
        let sources = sqlx::query!(
            r#"
            SELECT person_id, person_uuid, sealed as "sealed!" FROM lifecycle_op_person
            WHERE op_id = $1 AND role = $2 AND status = $3
            "#,
            op.op_id,
            ROLE_SOURCE,
            STATUS_SEALED,
        )
        .fetch_all(pool)
        .await?;

        let release_calls: Vec<_> = sources
            .iter()
            .map(|source| {
                let snapshot: Result<SealedSnapshot, _> =
                    serde_json::from_value(source.sealed.clone());
                let leader = Arc::clone(&self.leader);
                let op_id = op.op_id.to_string();
                let team_id = op.team_id;
                let person_id = source.person_id;
                let person_uuid = source.person_uuid.to_string();
                async move {
                    let snapshot = match snapshot {
                        Ok(snapshot) => snapshot,
                        Err(e) => {
                            return (
                                person_id,
                                Err(SagaError::CorruptState(format!(
                                    "merge source {person_id} has a malformed seal: {e}"
                                ))),
                            )
                        }
                    };
                    let result = leader
                        .release_fence(ReleaseFenceRequest {
                            team_id,
                            person_id,
                            person_uuid,
                            op_id,
                            outcome: ReleaseOutcome::Committed.into(),
                            sealed_version: Some(snapshot.version),
                            created_at: snapshot.created_at,
                        })
                        .await
                        .map(|_| ())
                        .map_err(|status| SagaError::Leader(Box::new(status)));
                    (person_id, result)
                }
            })
            .collect();
        for (_, result) in join_all(release_calls).await {
            result?;
        }

        let mut tx = pool.begin().await?;
        sqlx::query!(
            r#"
            UPDATE lifecycle_op_person SET status = $2
            WHERE op_id = $1 AND role = $3 AND status = $4
            "#,
            op.op_id,
            STATUS_DELETED,
            ROLE_SOURCE,
            STATUS_SEALED,
        )
        .execute(&mut *tx)
        .await?;
        let outcome = build_outcome(&mut tx, op, false).await?;
        if !complete_op_in_tx(
            &mut tx,
            op.op_id,
            MergeStep::Flipped.as_str(),
            STEP_COMPLETED,
            &outcome,
        )
        .await?
        {
            tx.rollback().await?;
            return Ok(());
        }
        tx.commit().await?;
        record_transition(MergeStep::Flipped.as_str(), STEP_COMPLETED);
        record_outcomes(&outcome);
        Ok(())
    }

    /// Release fences with outcome `aborted` for the given persons,
    /// bounded-concurrently. Releasing a never-fenced person is a no-op at
    /// the leader, so callers pass every candidate rather than tracking
    /// which fences actually installed.
    async fn release_fences(&self, op: &OpRow, persons: &[(i64, Uuid)]) -> Result<(), SagaError> {
        let calls: Vec<_> = persons
            .iter()
            .map(|(person_id, person_uuid)| {
                let leader = Arc::clone(&self.leader);
                let request = ReleaseFenceRequest {
                    team_id: op.team_id,
                    person_id: *person_id,
                    person_uuid: person_uuid.to_string(),
                    op_id: op.op_id.to_string(),
                    outcome: ReleaseOutcome::Aborted.into(),
                    sealed_version: None,
                    created_at: 0,
                };
                async move { leader.release_fence(request).await }
            })
            .collect();
        for result in join_all(calls).await {
            result.map_err(|status| SagaError::Leader(Box::new(status)))?;
        }
        Ok(())
    }
}

/// `document_folded → flipped`: the destroying transaction, all Postgres.
/// Repoint every sealed source's distinct ids to the target (recording the
/// moves per source row in the same commit), move cohort membership and
/// hash-key overrides target-wins, scrub and tombstone the source person
/// rows at their exact death versions, and clear the target's mark. The
/// source marks stay: they are the fences' durable record until release.
async fn flip(pool: &PgPool, op: &OpRow) -> Result<(), SagaError> {
    let team_id = op.team_id as i32;
    let mut tx = pool.begin().await?;

    let target = {
        let row = sqlx::query!(
            "SELECT person_id FROM lifecycle_op_person WHERE op_id = $1 AND role = $2",
            op.op_id,
            ROLE_TARGET,
        )
        .fetch_one(&mut *tx)
        .await?;
        row.person_id
    };
    let mut sources: Vec<i64> = sqlx::query_scalar!(
        r#"
        SELECT person_id FROM lifecycle_op_person
        WHERE op_id = $1 AND role = $2 AND status = $3
        "#,
        op.op_id,
        ROLE_SOURCE,
        STATUS_SEALED,
    )
    .fetch_all(&mut *tx)
    .await?;
    sources.sort_unstable();

    let repointed = sqlx::query!(
        r#"
        UPDATE posthog_persondistinctid
        SET person_id = $3, version = COALESCE(version, 0) + 1
        WHERE team_id = $1 AND person_id = ANY($2) AND is_deleted = false
        RETURNING person_id as "old_person_id!", distinct_id, version as "version!"
        "#,
        team_id,
        &sources,
        target,
    )
    .fetch_all(&mut *tx)
    .await?;

    // Record the repointed mappings per source in the same commit — what a
    // later ClickHouse emission (or an operator) reads back (delete parity).
    let mut moved_ids: Vec<i64> = Vec::new();
    let mut moved_json: Vec<Value> = Vec::new();
    for source in &sources {
        let rows: Vec<Value> = repointed
            .iter()
            .filter(|r| r.old_person_id == *source)
            .map(|r| serde_json::json!({"distinct_id": r.distinct_id, "version": r.version}))
            .collect();
        if !rows.is_empty() {
            moved_ids.push(*source);
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

    // Cohort membership moves wholesale. The table has no unique
    // constraint, so a target already in a cohort ends up with duplicate
    // rows — deliberately matching the production merge path, whose
    // recalculation heals the rare duplicate.
    sqlx::query!(
        "UPDATE posthog_cohortpeople SET person_id = $2 WHERE person_id = ANY($1)",
        &sources,
        target,
    )
    .execute(&mut *tx)
    .await?;

    // Hash-key overrides move target-wins: the target's existing override
    // for a flag beats any source's.
    sqlx::query!(
        r#"
        WITH removed AS (
            DELETE FROM posthog_featureflaghashkeyoverride
            WHERE team_id = $1 AND person_id = ANY($2)
            RETURNING feature_flag_key, hash_key
        )
        INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
        SELECT $1, $3, feature_flag_key, hash_key FROM removed
        ON CONFLICT (team_id, person_id, feature_flag_key) DO NOTHING
        "#,
        team_id,
        &sources,
        target,
    )
    .execute(&mut *tx)
    .await?;

    // Scrub and tombstone the source person rows at the death version the
    // leader derives from the same seal (sealed + 1; the leader max-merges
    // with its current version as defense in depth), so a reused key
    // revives above it. Exact PG/CH agreement additionally assumes no
    // spent-but-unconfirmed version sits above the seal — the fence path
    // does not consult the leader's emitted-version floor today.
    sqlx::query!(
        r#"
        UPDATE posthog_person p
        SET is_deleted = true,
            properties = '{}'::jsonb,
            properties_last_updated_at = '{}'::jsonb,
            properties_last_operation = '{}'::jsonb,
            version = (lop.sealed->>'version')::bigint + 1
        FROM lifecycle_op_person lop
        WHERE lop.op_id = $1 AND lop.role = $3 AND lop.status = $4
          AND p.team_id = $2 AND p.id = lop.person_id
        "#,
        op.op_id,
        team_id,
        ROLE_SOURCE,
        STATUS_SEALED,
    )
    .execute(&mut *tx)
    .await?;

    // The target's own person row is untouched: the folded document
    // reaches Postgres through the writer's projection (single-writer
    // rule). Only its mark clears — from here the merged person is
    // claimable by other lifecycle ops.
    sqlx::query!(
        "UPDATE lifecycle_op_person SET status = $2 WHERE op_id = $1 AND role = $3",
        op.op_id,
        STATUS_CLEARED,
        ROLE_TARGET,
    )
    .execute(&mut *tx)
    .await?;

    if !advance_step_in_tx(
        &mut tx,
        op.op_id,
        MergeStep::DocumentFolded.as_str(),
        MergeStep::Flipped.as_str(),
    )
    .await?
    {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    record_transition(
        MergeStep::DocumentFolded.as_str(),
        MergeStep::Flipped.as_str(),
    );
    Ok(())
}

struct TargetRow {
    person_id: i64,
}

async fn target_row(pool: &PgPool, op: &OpRow) -> Result<TargetRow, SagaError> {
    let row = sqlx::query!(
        "SELECT person_id FROM lifecycle_op_person WHERE op_id = $1 AND role = $2",
        op.op_id,
        ROLE_TARGET,
    )
    .fetch_one(pool)
    .await?;
    Ok(TargetRow {
        person_id: row.person_id,
    })
}

/// End an op inside the claim transaction: nothing outside this op's own
/// rows has been mutated, so recording the outcome and the terminal step
/// in the same commit is the whole abort.
async fn abort_in_claim_tx(
    mut tx: Tx<'_>,
    op: &OpRow,
    dispositions: Vec<Disposition>,
) -> Result<(), SagaError> {
    let outcome = outcome_from_dispositions(&dispositions, true, None, &HashMap::new())?;
    if !complete_op_in_tx(
        &mut tx,
        op.op_id,
        MergeStep::Started.as_str(),
        STEP_ABORTED,
        &outcome,
    )
    .await?
    {
        tx.rollback().await?;
        return Ok(());
    }
    tx.commit().await?;
    record_transition(MergeStep::Started.as_str(), STEP_ABORTED);
    record_outcomes(&outcome);
    Ok(())
}

/// Settle sources that dropped out during the seal: `dropped` releases
/// their marks; the claim record's decisions flip to the drop reason.
async fn settle_drops(
    tx: &mut Tx<'_>,
    op: &OpRow,
    vanished: &[i64],
    identified: &[i64],
) -> Result<(), SagaError> {
    let all: Vec<i64> = vanished.iter().chain(identified.iter()).copied().collect();
    if all.is_empty() {
        return Ok(());
    }
    sqlx::query!(
        r#"
        UPDATE lifecycle_op_person SET status = $2
        WHERE op_id = $1 AND person_id = ANY($3) AND status IN ('marked', 'sealed')
        "#,
        op.op_id,
        STATUS_DROPPED,
        &all,
    )
    .execute(&mut **tx)
    .await?;

    let mut record = claim_record(tx, op).await?;
    for disposition in record.dispositions.iter_mut() {
        if disposition.decision != DECISION_PENDING_MERGE {
            continue;
        }
        let Some(person_id) = disposition.person_id else {
            continue;
        };
        if vanished.contains(&person_id) {
            disposition.decision = OUTCOME_ERROR.to_string();
        } else if identified.contains(&person_id) {
            disposition.decision = OUTCOME_SKIPPED_ALREADY_IDENTIFIED.to_string();
        }
    }
    let updated = serde_json::to_value(&record)
        .map_err(|e| SagaError::CorruptState(format!("failed to serialize claim record: {e}")))?;
    sqlx::query!(
        "UPDATE lifecycle_op_person SET moved = $2 WHERE op_id = $1 AND role = $3",
        op.op_id,
        updated,
        ROLE_TARGET,
    )
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn claim_record(tx: &mut Tx<'_>, op: &OpRow) -> Result<ClaimRecord, SagaError> {
    let row = sqlx::query!(
        r#"SELECT moved FROM lifecycle_op_person WHERE op_id = $1 AND role = $2"#,
        op.op_id,
        ROLE_TARGET,
    )
    .fetch_one(&mut **tx)
    .await?;
    let moved = row.moved.ok_or_else(|| {
        SagaError::CorruptState(format!("merge op {} has no claim record", op.op_id))
    })?;
    serde_json::from_value(moved).map_err(|e| {
        SagaError::CorruptState(format!(
            "merge op {} claim record is malformed: {e}",
            op.op_id
        ))
    })
}

/// Build the terminal outcome from the persisted claim record and the
/// settled per-person rows. `pending_merge` decisions resolve through
/// their row's status: `deleted` means the merge committed for that
/// person; anything else on a non-aborted path is an anomaly reported as
/// `error`.
async fn build_outcome(tx: &mut Tx<'_>, op: &OpRow, aborted: bool) -> Result<Value, SagaError> {
    let record = claim_record(tx, op).await?;
    let statuses: HashMap<i64, String> = sqlx::query!(
        "SELECT person_id, status FROM lifecycle_op_person WHERE op_id = $1 AND role = $2",
        op.op_id,
        ROLE_SOURCE,
    )
    .fetch_all(&mut **tx)
    .await?
    .into_iter()
    .map(|r| (r.person_id, r.status))
    .collect();

    let survivor = if aborted {
        None
    } else {
        let row = sqlx::query!(
            r#"SELECT sealed FROM lifecycle_op_person WHERE op_id = $1 AND role = $2"#,
            op.op_id,
            ROLE_TARGET,
        )
        .fetch_one(&mut **tx)
        .await?;
        row.sealed
    };

    outcome_from_dispositions(&record.dispositions, aborted, survivor, &statuses)
}

fn outcome_from_dispositions(
    dispositions: &[Disposition],
    aborted: bool,
    survivor: Option<Value>,
    statuses: &HashMap<i64, String>,
) -> Result<Value, SagaError> {
    let results = dispositions
        .iter()
        .map(|d| {
            let outcome = if d.decision == DECISION_PENDING_MERGE {
                let status = d
                    .person_id
                    .and_then(|id| statuses.get(&id))
                    .map(String::as_str);
                match (aborted, status) {
                    (true, _) => OUTCOME_SKIPPED_CONFLICT,
                    (false, Some(STATUS_DELETED)) => OUTCOME_MERGED,
                    (false, _) => OUTCOME_ERROR,
                }
            } else {
                d.decision.as_str()
            };
            MergeSourceRecord {
                distinct_id: d.distinct_id.clone(),
                outcome: outcome.to_string(),
            }
        })
        .collect();
    serde_json::to_value(MergeOutcome {
        aborted,
        survivor,
        results,
    })
    .map_err(|e| SagaError::CorruptState(format!("failed to serialize merge outcome: {e}")))
}

fn snapshot_from_sealed(person: &Person) -> Result<SealedSnapshot, SagaError> {
    let properties = if person.properties.is_empty() {
        Value::Object(serde_json::Map::new())
    } else {
        serde_json::from_slice(&person.properties).map_err(|e| {
            SagaError::CorruptState(format!("sealed properties do not parse as JSON: {e}"))
        })?
    };
    Ok(SealedSnapshot {
        version: person.version,
        created_at: person.created_at,
        is_identified: person.is_identified,
        properties,
    })
}

fn encode_json_map(value: &Value) -> Result<Vec<u8>, SagaError> {
    if value.is_null() {
        return Ok(Vec::new());
    }
    serde_json::to_vec(value)
        .map_err(|e| SagaError::CorruptState(format!("failed to serialize event payload: {e}")))
}
