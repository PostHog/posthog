//! Lifecycle fence state: which persons are frozen by a live lifecycle
//! operation, and how a leader rebuilds that knowledge across ownership
//! changes.
//!
//! The fence's source of truth is not this map — it is the saga's mark row
//! (`lifecycle_op_person` in `marked`/`sealed`), committed on the persons
//! primary before `FencePerson` is ever called. The map is the leader's
//! in-process copy so the write path can reject without a database read.
//! It is filled from two sources that together cover every mark: partition
//! takeover reads the live marks from Postgres (before the partition
//! accepts writes), and each `FencePerson` call adds an entry. Entries
//! leave in exactly three ways: a `ReleaseFence`, the lazy liveness check
//! (a rejected write finds the op finished and drops the stale entry), and
//! dropping the whole partition. The map is NOT a cache: it has no
//! capacity limit and no eviction path — losing an entry while continuing
//! to serve would violate consistency, not degrade it.

use std::sync::Arc;

use dashmap::DashMap;
use sqlx::postgres::PgPool;
use sqlx::Row;
use tonic::Status;
use uuid::Uuid;

use personhog_common::partitioning::partition_for_person;
use personhog_proto::personhog::types::v1::LifecycleOpType;

use crate::cache::PersonCacheKey;

/// A person's live fence: the operation that froze it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FenceState {
    pub op_id: Uuid,
    pub op_type: LifecycleOpType,
}

pub type FenceMap = Arc<DashMap<PersonCacheKey, FenceState>>;

/// Metadata key carried on fenced-write rejections: `delete` or `merge`.
/// Callers distinguish "this person is being destroyed, back off" from
/// ordinary precondition failures by this key's presence.
pub const FENCED_METADATA_KEY: &str = "x-person-fenced";
/// Metadata key carrying the fencing operation's id on rejections.
pub const FENCED_OP_ID_METADATA_KEY: &str = "x-person-fenced-op-id";

/// The typed rejection for a write to a fenced person: PERSON_DELETING /
/// PERSON_MERGING per the RFC, encoded as FAILED_PRECONDITION plus
/// metadata (gRPC has no custom codes).
pub fn fenced_status(state: &FenceState) -> Status {
    let what = match state.op_type {
        LifecycleOpType::Delete => "PERSON_DELETING",
        LifecycleOpType::Merge => "PERSON_MERGING",
        LifecycleOpType::Unspecified => "PERSON_FENCED",
    };
    let label = state.op_type.as_op_type_str();
    let mut status = Status::failed_precondition(format!(
        "{what}: person is fenced by lifecycle op {}",
        state.op_id
    ));
    if let Ok(value) = label.parse() {
        status.metadata_mut().insert(FENCED_METADATA_KEY, value);
    }
    if let Ok(value) = state.op_id.to_string().parse() {
        status
            .metadata_mut()
            .insert(FENCED_OP_ID_METADATA_KEY, value);
    }
    status
}

/// The takeover scan: load every live mark belonging to `partition` and
/// install it in the fence map, before the partition accepts writes.
///
/// The scan cannot target a partition (the partition is a murmur2 hash
/// Postgres cannot compute), so it reads the whole live-mark set — an
/// index-only read of the covering partial mark index, which contains
/// nothing but live marks and is small by construction (live marks =
/// op arrival rate × op duration) — and filters in-process with the same
/// partition function and count request validation uses. Merge targets are
/// claimed but never fenced, so they are excluded. Returns how many fences
/// were installed.
pub async fn rebuild_partition_fences(
    pool: &PgPool,
    fences: &FenceMap,
    partition: u32,
    num_partitions: u32,
) -> Result<usize, sqlx::Error> {
    let rows = sqlx::query(
        r#"
        SELECT lop.team_id, lop.person_id, lop.op_id, o.op_type
        FROM lifecycle_op_person lop
        JOIN lifecycle_op o ON o.op_id = lop.op_id
        WHERE lop.status IN ('marked', 'sealed')
          AND lop.role <> 'target'
        "#,
    )
    .fetch_all(pool)
    .await?;

    let mut installed = 0usize;
    for row in rows {
        let team_id: i32 = row.get("team_id");
        let person_id: i64 = row.get("person_id");
        if partition_for_person(team_id as i64, person_id, num_partitions) != partition {
            continue;
        }
        let op_id: Uuid = row.get("op_id");
        let op_type: String = row.get("op_type");
        fences.insert(
            PersonCacheKey {
                team_id: team_id as i64,
                person_id,
            },
            FenceState {
                op_id,
                op_type: LifecycleOpType::from_op_type_str(&op_type),
            },
        );
        installed += 1;
    }
    Ok(installed)
}

/// Drop every fence belonging to `partition` — the counterpart of
/// [`rebuild_partition_fences`] for partition release. The new owner
/// rebuilds its own; stale entries here would only pin memory for persons
/// this pod no longer serves (misrouted requests are already rejected by
/// partition validation).
pub fn drop_partition_fences(fences: &FenceMap, partition: u32, num_partitions: u32) -> usize {
    let before = fences.len();
    fences.retain(|key, _| {
        partition_for_person(key.team_id, key.person_id, num_partitions) != partition
    });
    before - fences.len()
}

/// The lazy liveness check: a map entry can briefly outlive its op (the op
/// finished just after the takeover scan read the marks). A rejected write
/// triggers this check; a finished or GC'd op means the entry is stale and
/// must be dropped so the person resumes normal life. Returns true when
/// the op is still live (the rejection stands).
pub async fn op_is_live(pool: &PgPool, op_id: Uuid) -> Result<bool, sqlx::Error> {
    let live: Option<bool> =
        sqlx::query_scalar("SELECT completed_at IS NULL FROM lifecycle_op WHERE op_id = $1")
            .bind(op_id)
            .fetch_optional(pool)
            .await?;
    // An absent row means the op completed and was GC'd past retention.
    Ok(live.unwrap_or(false))
}
