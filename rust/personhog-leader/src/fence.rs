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

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use dashmap::DashMap;
use metrics::{counter, gauge, histogram};
use sqlx::{PgPool, Row};
use tokio::sync::OnceCell;
use tonic::Status;
use uuid::Uuid;

use personhog_common::partitioning::partition_for_person;
use personhog_proto::personhog::types::v1::LifecycleOpType;

use crate::cache::PersonCacheKey;
use crate::pg::PgFallback;

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
    fallback: &PgFallback,
    fences: &FenceMap,
    partition: u32,
    num_partitions: u32,
) -> Result<usize, sqlx::Error> {
    let start = std::time::Instant::now();
    let tables = &fallback.lifecycle;
    let sql = format!(
        r#"
        SELECT lop.team_id, lop.person_id, lop.op_id, o.op_type
        FROM {op_person} lop
        JOIN {op} o ON o.op_id = lop.op_id
        WHERE lop.mark_active
          AND lop.role <> 'target'
        "#,
        op_person = tables.op_person,
        op = tables.op,
    );
    let query = sqlx::query(&sql).fetch_all(&fallback.pool);

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
        let op_type: String = row.get("op_type");
        fences.insert(
            PersonCacheKey {
                team_id: team_id as i64,
                person_id,
            },
            FenceState {
                op_id: row.get("op_id"),
                op_type: LifecycleOpType::from_op_type_str(&op_type),
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
    fallback: PgFallback,
    fences: FenceMap,
    /// Per-person stamp of the last triggered check, for the cooldown.
    last_checked: DashMap<PersonCacheKey, std::time::Instant>,
}

impl FenceHealer {
    pub fn new(fallback: PgFallback, fences: FenceMap) -> Self {
        Self {
            fallback,
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
        let status = match mark_status(&self.fallback, state.op_id, key.team_id, key.person_id)
            .await
        {
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
    fallback: &PgFallback,
    op_id: Uuid,
    team_id: i64,
    person_id: i64,
) -> Result<Option<String>, sqlx::Error> {
    let mut conn = crate::pg::acquire_timed(&fallback.pool, "mark_status").await?;
    let sql = format!(
        "SELECT status FROM {} \
         WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role <> 'target'",
        fallback.lifecycle.op_person
    );
    sqlx::query_scalar(&sql)
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_id)
        .fetch_optional(&mut *conn)
        .await
}

/// [`mark_status`] for a whole batch in one pool acquire, keyed by person
/// id. A person with no row is absent from the map, which the caller
/// reads as it reads `None` from the single lookup.
pub async fn mark_statuses(
    fallback: &PgFallback,
    op_id: Uuid,
    team_id: i64,
    person_ids: &[i64],
) -> Result<HashMap<i64, String>, sqlx::Error> {
    let mut conn = crate::pg::acquire_timed(&fallback.pool, "mark_statuses").await?;
    let sql = format!(
        "SELECT person_id, status FROM {} \
         WHERE op_id = $1 AND team_id = $2 AND person_id = ANY($3) AND role <> 'target'",
        fallback.lifecycle.op_person
    );
    let rows: Vec<(i64, String)> = sqlx::query_as(&sql)
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_ids)
        .fetch_all(&mut *conn)
        .await?;
    Ok(rows.into_iter().collect())
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
    fallback: &PgFallback,
    op_id: Uuid,
    team_id: i64,
    person_id: i64,
) -> Result<Option<String>, sqlx::Error> {
    let mut conn = crate::pg::acquire_timed(&fallback.pool, "target_mark_status").await?;
    let sql = format!(
        "SELECT status FROM {} \
         WHERE op_id = $1 AND team_id = $2 AND person_id = $3 AND role = 'target'",
        fallback.lifecycle.op_person
    );
    sqlx::query_scalar(&sql)
        .bind(op_id)
        .bind(team_id as i32)
        .bind(person_id)
        .fetch_optional(&mut *conn)
        .await
}

/// Bounds how long a re-driven op can be answered from rows read for an
/// earlier attempt; an op's releases run within one saga step.
const MARK_SNAPSHOT_TTL: Duration = Duration::from_secs(30);

/// Keeps the snapshot map bounded without a sweeper task.
const MARK_SNAPSHOT_PRUNE_THRESHOLD: usize = 1_000;

const MARK_SNAPSHOTS_TOTAL: &str = "personhog_leader_mark_snapshots_total";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarkRow {
    pub team_id: i64,
    pub person_id: i64,
    pub status: String,
}

#[async_trait]
pub trait MarkSource: Send + Sync {
    async fn load_op(&self, op_id: Uuid) -> Result<Vec<MarkRow>, sqlx::Error>;
}

/// Merge targets are excluded because targets are never destroyed.
pub struct PgMarkSource {
    pool: PgPool,
    op_person_table: String,
}

#[async_trait]
impl MarkSource for PgMarkSource {
    async fn load_op(&self, op_id: Uuid) -> Result<Vec<MarkRow>, sqlx::Error> {
        let mut conn = crate::pg::acquire_timed(&self.pool, "mark_snapshot").await?;
        let sql = format!(
            "SELECT team_id, person_id, status FROM {} \
             WHERE op_id = $1 AND role <> 'target'",
            self.op_person_table
        );
        let rows = sqlx::query(&sql).bind(op_id).fetch_all(&mut *conn).await?;
        Ok(rows
            .into_iter()
            .map(|row| MarkRow {
                team_id: i64::from(row.get::<i32, _>("team_id")),
                person_id: row.get("person_id"),
                status: row.get("status"),
            })
            .collect())
    }
}

struct MarkSnapshot {
    fetched_at: Instant,
    rows: HashMap<(i64, i64), String>,
}

/// The committed-release check, answered from one read of the op's rows
/// per op per pod. The op's victim set is fixed once its claim commits,
/// and releases only start after the destroying step commits, so a
/// snapshot taken at the first release is final for every victim of the
/// op. The row still has to vouch for the (op, person) pair, so the
/// request alone is never enough.
pub struct MarkVerifier {
    source: Arc<dyn MarkSource>,
    ttl: Duration,
    snapshots: DashMap<Uuid, Arc<OnceCell<MarkSnapshot>>>,
}

impl MarkVerifier {
    pub fn new(fallback: &PgFallback) -> Self {
        let source = PgMarkSource {
            pool: fallback.pool.clone(),
            op_person_table: fallback.lifecycle.op_person.clone(),
        };
        Self::with_source(Arc::new(source), MARK_SNAPSHOT_TTL)
    }

    pub fn with_source(source: Arc<dyn MarkSource>, ttl: Duration) -> Self {
        Self {
            source,
            ttl,
            snapshots: DashMap::new(),
        }
    }

    pub async fn status(
        &self,
        op_id: Uuid,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<String>, sqlx::Error> {
        loop {
            let cell = self.cell(op_id);
            let loaded_now = AtomicBool::new(false);
            let snapshot = cell
                .get_or_try_init(|| async {
                    loaded_now.store(true, Ordering::Relaxed);
                    counter!(MARK_SNAPSHOTS_TOTAL, "outcome" => "load").increment(1);
                    let rows = self.source.load_op(op_id).await?;
                    Ok::<_, sqlx::Error>(MarkSnapshot {
                        fetched_at: Instant::now(),
                        rows: rows
                            .into_iter()
                            .map(|row| ((row.team_id, row.person_id), row.status))
                            .collect(),
                    })
                })
                .await?;
            if loaded_now.load(Ordering::Relaxed) {
                return Ok(snapshot.rows.get(&(team_id, person_id)).cloned());
            }
            // Only a snapshot someone else loaded can expire here, so a TTL
            // shorter than one load cannot make this loop spin.
            if snapshot.fetched_at.elapsed() > self.ttl {
                counter!(MARK_SNAPSHOTS_TOTAL, "outcome" => "expired").increment(1);
                self.snapshots
                    .remove_if(&op_id, |_, current| Arc::ptr_eq(current, &cell));
                continue;
            }
            counter!(MARK_SNAPSHOTS_TOTAL, "outcome" => "hit").increment(1);
            return Ok(snapshot.rows.get(&(team_id, person_id)).cloned());
        }
    }

    fn cell(&self, op_id: Uuid) -> Arc<OnceCell<MarkSnapshot>> {
        if let Some(cell) = self.snapshots.get(&op_id) {
            return Arc::clone(&cell);
        }
        if self.snapshots.len() >= MARK_SNAPSHOT_PRUNE_THRESHOLD {
            let ttl = self.ttl;
            self.snapshots.retain(|_, cell| {
                cell.get()
                    .is_none_or(|snapshot| snapshot.fetched_at.elapsed() <= ttl)
            });
        }
        Arc::clone(&self.snapshots.entry(op_id).or_default())
    }
}

#[cfg(test)]
mod mark_verifier_tests {
    use std::sync::atomic::AtomicUsize;

    use super::*;

    struct CountingSource {
        rows: Vec<MarkRow>,
        loads: AtomicUsize,
        fail_next_load: AtomicBool,
    }

    impl CountingSource {
        fn sealed(persons: i64) -> Arc<Self> {
            Arc::new(Self {
                rows: (1..=persons)
                    .map(|person_id| MarkRow {
                        team_id: 1,
                        person_id,
                        status: "sealed".to_string(),
                    })
                    .collect(),
                loads: AtomicUsize::new(0),
                fail_next_load: AtomicBool::new(false),
            })
        }

        fn loads(&self) -> usize {
            self.loads.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl MarkSource for CountingSource {
        async fn load_op(&self, _op_id: Uuid) -> Result<Vec<MarkRow>, sqlx::Error> {
            self.loads.fetch_add(1, Ordering::SeqCst);
            if self.fail_next_load.swap(false, Ordering::SeqCst) {
                return Err(sqlx::Error::PoolTimedOut);
            }
            Ok(self.rows.clone())
        }
    }

    #[tokio::test]
    async fn releases_of_one_op_share_one_load_and_unknown_persons_stay_unverified() {
        let source = CountingSource::sealed(50);
        let verifier = Arc::new(MarkVerifier::with_source(source.clone(), MARK_SNAPSHOT_TTL));
        let op = Uuid::now_v7();

        let mut releases = tokio::task::JoinSet::new();
        for person_id in 1..=50 {
            let verifier = Arc::clone(&verifier);
            releases.spawn(async move { verifier.status(op, 1, person_id).await });
        }
        while let Some(joined) = releases.join_next().await {
            let status = joined.expect("lookup task").expect("lookup succeeds");
            assert_eq!(status.as_deref(), Some("sealed"));
        }
        assert_eq!(source.loads(), 1, "one load serves every victim of the op");

        let outside_op = verifier.status(op, 1, 51).await.expect("lookup succeeds");
        let other_team = verifier.status(op, 2, 1).await.expect("lookup succeeds");
        assert_eq!(
            outside_op, None,
            "a person the op never claimed is unverified"
        );
        assert_eq!(other_team, None, "the row must match the team too");
        assert_eq!(source.loads(), 1);
    }

    #[tokio::test]
    async fn an_expired_snapshot_is_read_again() {
        let source = CountingSource::sealed(1);
        let verifier = MarkVerifier::with_source(source.clone(), Duration::ZERO);
        let op = Uuid::now_v7();

        verifier.status(op, 1, 1).await.expect("first lookup");
        assert_eq!(source.loads(), 1, "the loader keeps its own snapshot");
        let status = verifier.status(op, 1, 1).await.expect("second lookup");
        assert_eq!(status.as_deref(), Some("sealed"));
        assert_eq!(source.loads(), 2, "an expired snapshot is replaced");
    }

    #[tokio::test]
    async fn a_failed_load_is_retried_by_the_next_release() {
        let source = CountingSource::sealed(1);
        source.fail_next_load.store(true, Ordering::SeqCst);
        let verifier = MarkVerifier::with_source(source.clone(), MARK_SNAPSHOT_TTL);
        let op = Uuid::now_v7();

        verifier
            .status(op, 1, 1)
            .await
            .expect_err("the failed load surfaces to the release");
        let status = verifier.status(op, 1, 1).await.expect("second lookup");
        assert_eq!(status.as_deref(), Some("sealed"));
        assert_eq!(source.loads(), 2, "nothing from the failed load is trusted");
    }
}
