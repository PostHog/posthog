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
//! always eventually arrives, with one exception: an op whose committed
//! release this leader definitively refused (a semantic refusal) is
//! parked by the saga engine and stops retrying, so its fences hold
//! until an operator re-drives it. The person stays frozen rather than
//! half-destroyed. An entry that outlives a crashed saga is not stale —
//! the mark is still live, the op really is unfinished, and the person
//! really should stay frozen. For that guarantee to hold, a
//! release must never *vacuously* succeed: both fence RPCs verify this
//! pod serves the partition, so a misrouted call fails and identity's
//! retry reaches the pod whose map actually gates the writes.
//!
//! The map is NOT a cache: it has no capacity limit and no eviction path
//! — losing an entry while continuing to serve would violate consistency,
//! not degrade it.
//!
//! One known window: a takeover that runs between a release being acked
//! and the saga settling its mark row installs a fence for an op that is
//! already done — a ghost no `ReleaseFence` will ever clear. The
//! [`FenceHealer`] closes it lazily: a write rejected by a fence triggers
//! a non-blocking mark-row read, and a fence whose op has settled is
//! dropped, so the next write goes through instead of waiting for the
//! partition to change hands.

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
    /// The uuid of the event whose merge installed the fence, where the
    /// saga supplied one. Advisory: echoed on rejections so callers can
    /// attribute the fence to its event; ownership keys on the op id.
    pub creator_event_uuid: Option<Uuid>,
}

pub type FenceMap = Arc<DashMap<PersonCacheKey, FenceState>>;

/// Metadata key carried on fenced-write rejections: `delete` or `merge`.
/// Callers distinguish "this person is being destroyed, back off" from
/// ordinary precondition failures by this key's presence.
pub const FENCED_METADATA_KEY: &str = "x-person-fenced";
/// Metadata key carrying the fencing operation's id on rejections.
pub const FENCED_OP_ID_METADATA_KEY: &str = "x-person-fenced-op-id";
/// Metadata key carrying the fencing operation's creator event uuid on
/// rejections, absent where the fence carries none (delete ops, and merge
/// ops frozen before the field existed).
pub const FENCED_CREATOR_METADATA_KEY: &str = "x-person-fenced-creator";

/// A definitive FAILED_PRECONDITION the router passes through to the
/// caller instead of bouncing. Bare FAILED_PRECONDITION classifies as a
/// routing-race bounce and exhausts into retriable UNAVAILABLE, which
/// would turn a fail-closed verification refusal into an infinite saga
/// retry loop; the marker (see
/// `personhog_common::grpc::SEMANTIC_REFUSAL_METADATA_KEY`) makes the
/// refusal survive the trip.
pub use personhog_common::grpc::semantic_refusal;

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
    if let Some(creator) = state.creator_event_uuid {
        if let Ok(value) = creator.to_string().parse() {
            status
                .metadata_mut()
                .insert(FENCED_CREATOR_METADATA_KEY, value);
        }
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
        SELECT lop.team_id, lop.person_id, lop.op_id, o.op_type,
               o.request->>'creator_event_uuid' AS creator_event_uuid
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
    // Read next to installed is the scan's amplification: it reads the
    // whole live-mark set (the partition is a hash Postgres cannot
    // compute) and keeps ~1/num_partitions of it. This ratio growing is
    // the signal that the scan-the-world design needs revisiting.
    counter!("personhog_leader_fence_scan_rows_read_total").increment(rows.len() as u64);

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
        // Frozen requests predating the field, and delete ops, carry none.
        let creator_event_uuid = row
            .get::<Option<String>, _>("creator_event_uuid")
            .and_then(|raw| Uuid::parse_str(&raw).ok());
        fences.insert(
            PersonCacheKey {
                team_id: team_id as i64,
                person_id,
            },
            FenceState {
                op_id,
                op_type: LifecycleOpType::from_op_type_str(&op_type),
                creator_event_uuid,
            },
        );
        installed += 1;
    }
    counter!("personhog_leader_fence_scan_fences_installed_total").increment(installed as u64);
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

/// How long a person's heal verdict stands before a rejected write may
/// trigger another mark-row read. Bounds the PG read rate for a person
/// that is legitimately fenced and still receiving writes: at most one
/// point read per person per cooldown, however hot the write storm.
const HEAL_COOLDOWN: Duration = Duration::from_secs(5);

/// Above this many tracked persons, expired cooldown stamps are pruned on
/// the next trigger. Keeps the tracker bounded without a sweeper task.
const HEAL_TRACKER_PRUNE_THRESHOLD: usize = 10_000;

/// Lazily removes ghost fences — entries whose op has already settled its
/// mark row, so no `ReleaseFence` will ever arrive for them (see the
/// module docs for how the takeover scan creates these).
///
/// Triggered from the write path when a fence rejects a write, but never
/// on it: the check runs on a spawned task, the write fails as fenced
/// either way, and the caller's retry finds the fence gone. Fail-closed
/// by construction — the fence is only dropped when Postgres, the source
/// of truth, says the mark is no longer live, and only if the entry still
/// belongs to the op that was checked (a newer op's fence is never
/// touched).
pub struct FenceHealer {
    pool: PgPool,
    fences: FenceMap,
    /// Per-person stamp of the last triggered check, for the cooldown.
    last_checked: DashMap<PersonCacheKey, std::time::Instant>,
}

impl FenceHealer {
    pub fn new(pool: PgPool, fences: FenceMap) -> Self {
        Self {
            pool,
            fences,
            last_checked: DashMap::new(),
        }
    }

    /// Kick off a background ghost check for `key`, unless one ran within
    /// the cooldown. Called after a write was rejected by `state`.
    pub fn maybe_heal(self: &Arc<Self>, key: PersonCacheKey, state: FenceState) {
        let now = std::time::Instant::now();
        if self.last_checked.len() > HEAL_TRACKER_PRUNE_THRESHOLD {
            self.last_checked
                .retain(|_, stamp| now.duration_since(*stamp) < HEAL_COOLDOWN);
        }
        // The entry API keeps check-and-stamp atomic: one write storm
        // triggers one check per cooldown, not one per rejection.
        match self.last_checked.entry(key.clone()) {
            dashmap::mapref::entry::Entry::Occupied(mut entry)
                if now.duration_since(*entry.get()) >= HEAL_COOLDOWN =>
            {
                entry.insert(now);
            }
            dashmap::mapref::entry::Entry::Vacant(entry) => {
                entry.insert(now);
            }
            dashmap::mapref::entry::Entry::Occupied(_) => return,
        }
        let healer = Arc::clone(self);
        tokio::spawn(async move {
            healer.check_and_heal(key, state).await;
        });
    }

    async fn check_and_heal(&self, key: PersonCacheKey, state: FenceState) {
        let status = match mark_status(&self.pool, state.op_id, key.team_id, key.person_id).await {
            Ok(status) => status,
            Err(e) => {
                counter!("personhog_leader_fence_heals_total", "outcome" => "error").increment(1);
                tracing::warn!(
                    team_id = key.team_id,
                    person_id = key.person_id,
                    op_id = %state.op_id,
                    error = %e,
                    "ghost-fence check failed; fence kept"
                );
                return;
            }
        };
        // Live is what the takeover scan installs from; anything else —
        // a terminal status or no row at all — means the op has settled
        // and its release already happened somewhere.
        if matches!(status.as_deref(), Some("marked") | Some("sealed")) {
            counter!("personhog_leader_fence_heals_total", "outcome" => "still_live").increment(1);
            return;
        }
        // Conditional on the op id: a fence re-installed by a newer op in
        // the meantime is someone else's and stays.
        let removed = self
            .fences
            .remove_if(&key, |_, current| current.op_id == state.op_id)
            .is_some();
        if removed {
            self.last_checked.remove(&key);
            gauge!("personhog_leader_fences_active").set(self.fences.len() as f64);
            counter!("personhog_leader_fence_heals_total", "outcome" => "removed").increment(1);
            tracing::info!(
                team_id = key.team_id,
                person_id = key.person_id,
                op_id = %state.op_id,
                "removed a ghost fence: its op has already settled"
            );
        }
    }
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

/// The fold's check: the status of the op's mark row claiming this person
/// as its merge target. `None` when the op never claimed the person as
/// target — including when it holds the person under another role, which
/// would make a fold into it a saga bug. A fold must find a live mark here
/// before it may write. The check is read-time only: a fold already past
/// it when the op settles can still land (the window spans the fold
/// computation and the produce), so it closes late re-drives, not the
/// full race — the same at-least-once residual the op_id proto comment
/// states.
pub async fn target_mark_status(
    pool: &PgPool,
    op_id: Uuid,
    team_id: i64,
    person_id: i64,
) -> Result<Option<String>, sqlx::Error> {
    sqlx::query_scalar(
        "SELECT status FROM lifecycle_op_person \
         WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role = 'target'",
    )
    .bind(op_id)
    .bind(team_id as i32)
    .bind(person_id)
    .fetch_optional(pool)
    .await
}
