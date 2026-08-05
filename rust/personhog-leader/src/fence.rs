//! Lifecycle fence state: which persons are frozen by a live lifecycle
//! operation, and how a leader rebuilds that knowledge across ownership
//! changes.
//!
//! The fence's source of truth is not this map — it is the saga's mark row
//! (`lifecycle_op_person` in `marked`/`sealed`), committed on the persons
//! primary before `FencePerson` is ever called. The map is the leader's
//! in-process copy, and on the write path it is authoritative: a fenced
//! write is rejected from memory alone, never a database read.
//!
//! Postgres is read in exactly one place — the takeover scan, once per
//! partition acquisition, before the partition accepts writes. That plus
//! the `FencePerson` RPC are the only two ways an entry gets in, and
//! together they cover every mark. Entries leave in exactly two ways: a
//! `ReleaseFence`, or dropping the whole partition.
//!
//! The leader never reclaims a fence on its own, and deliberately so.
//! personhog-identity owns lifecycle correctness: every op is driven to a
//! terminal state (lease steal, sweeper resumption), so a `ReleaseFence`
//! always eventually arrives. An entry that outlives a crashed saga is
//! not stale — the mark is still live, the op really is unfinished, and
//! the person really should stay frozen. For that guarantee to hold, a
//! release must never *vacuously* succeed: both fence RPCs verify this
//! pod serves the partition, so a misrouted call fails and identity's
//! retry reaches the pod whose map actually gates the writes.
//!
//! The map is NOT a cache: it has no capacity limit and no eviction path
//! — losing an entry while continuing to serve would violate consistency,
//! not degrade it.
//!
//! One known bound: a takeover that runs between a release being acked
//! and the saga settling its mark row installs a fence for an op that is
//! already done. The next partition movement or restart clears it.

use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use metrics::{counter, gauge, histogram};
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

/// How long the takeover scan may run before the handoff gives up. The
/// scan gates a partition's return to service, and it reads a set whose
/// size depends on another service's liveness (marks stay live while
/// their op does), so it is bounded here rather than trusted to be
/// small. Expiry fails the handoff — a partition whose fences cannot be
/// known must not serve writes.
const SCAN_TIMEOUT: Duration = Duration::from_secs(10);

/// The takeover scan: load every live mark belonging to `partition` and
/// install it in the fence map, before the partition accepts writes.
///
/// The scan cannot target a partition (the partition is a murmur2 hash
/// Postgres cannot compute), so it reads the whole live-mark set — the
/// partial mark index contains nothing but live marks — and filters
/// in-process with the same partition function request validation uses.
/// The join to `lifecycle_op` for the op type costs a lookup per row, so
/// this is not an index-only read; it stays cheap because the live-mark
/// set is small while ops complete. Merge targets are claimed but never
/// fenced, so they are excluded.
///
/// The partition's existing entries are dropped first, so a re-warm
/// (a handoff cancelled after warming, then re-acquired) converges
/// instead of accumulating. Returns how many fences were installed.
pub async fn rebuild_partition_fences(
    pool: &PgPool,
    fences: &FenceMap,
    partition: u32,
    num_partitions: u32,
) -> Result<usize, sqlx::Error> {
    let start = std::time::Instant::now();
    let query = sqlx::query(
        r#"
        SELECT lop.team_id, lop.person_id, lop.op_id, o.op_type
        FROM lifecycle_op_person lop
        JOIN lifecycle_op o ON o.op_id = lop.op_id
        WHERE lop.status IN ('marked', 'sealed')
          AND lop.role <> 'target'
        "#,
    )
    .fetch_all(pool);

    let rows = match tokio::time::timeout(SCAN_TIMEOUT, query).await {
        Ok(result) => result?,
        Err(_) => {
            counter!("personhog_leader_fence_scan_timeouts_total").increment(1);
            return Err(sqlx::Error::PoolTimedOut);
        }
    };
    histogram!("personhog_leader_fence_scan_duration_seconds")
        .record(start.elapsed().as_secs_f64());

    // Converge rather than accumulate: this partition's fences are
    // exactly what the marks say, not that plus whatever a previous warm
    // left behind.
    drop_partition_fences(fences, partition, num_partitions);

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
    gauge!("personhog_leader_fences_active").set(fences.len() as f64);
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
    gauge!("personhog_leader_fences_active").set(fences.len() as f64);
    before - fences.len()
}

/// The committed-release check: the status of the op's mark row for this
/// person, straight from the source of truth. `None` when the op never
/// claimed the person (or claimed it only as a merge target — targets are
/// never destroyed). A committed release must find a live mark here before
/// it may produce a death document: the request alone must never be enough
/// to destroy a person.
pub async fn mark_status(
    pool: &PgPool,
    op_id: Uuid,
    team_id: i64,
    person_id: i64,
) -> Result<Option<String>, sqlx::Error> {
    sqlx::query_scalar(
        "SELECT status FROM lifecycle_op_person \
         WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role <> 'target'",
    )
    .bind(op_id)
    .bind(team_id as i32)
    .bind(person_id)
    .fetch_optional(pool)
    .await
}
