//! Async facade over [`CohortStore`]: the only store surface async production code sees.
//!
//! Synchronous RocksDB I/O blocks the thread that issues it. On the runtime's worker threads that
//! is fatal to throughput — a thread parked in a read is a core that computes nothing. This facade
//! moves store I/O onto Tokio's blocking pool via `spawn_blocking`, so the runtime worker threads
//! stay CPU-only (HogVM eval, serde, plumbing) while store I/O runs elsewhere with bounded,
//! observable concurrency.
//!
//! Bounding is two independent permit lanes ([`ReadLane`]): a maintenance storm (tz-midnight sweep
//! waves, boot rebuild scans, GC) draws only on the maintenance lane and cannot starve event-path
//! reads through a single shared FIFO pool. Writes take no permit — the commit cadence must never
//! queue behind reads.
//!
//! [`CohortStore`] (sync) stays the surface for blocking contexts that cannot `.await`: whole-section
//! state machines run through [`StoreHandle::run_section`], and checkpoint/tests call it directly.

// This module is the sanctioned wrapper: every async method funnels one direct `CohortStore` I/O
// call onto the blocking pool, so the lint must not fire on the wrapper itself.
#![allow(clippy::disallowed_methods)]

use std::str::FromStr;
use std::sync::Arc;
use std::time::Instant;

use metrics::{gauge, histogram};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use tokio::task::JoinError;

use super::keys::{PendingTransferKey, Stage2Key, TombstoneKey};
use super::keyspace::{BehavioralKey, PersonPrefix, PersonRecordKey};
use super::rocks::{CohortStore, EventSnapshotRaw, StoreError, StoreStats};
use super::staged::StagedBatch;
use crate::observability::metrics::{
    STORE_OFFLOAD_EXEC_DURATION_SECONDS, STORE_OFFLOAD_INFLIGHT,
    STORE_OFFLOAD_PERMIT_WAIT_DURATION_SECONDS, STORE_OFFLOAD_QUEUE_WAIT_DURATION_SECONDS,
};

const LANE_EVENT: &str = "event";
const LANE_MAINTENANCE: &str = "maintenance";
const LANE_WRITE: &str = "write";
const LANE_SECTION: &str = "section";

/// Where each store op runs — one env knob (`COHORT_STORE_OFFLOAD_MODE`) with three operating points.
///
/// The mode is matched only inside the facade's private executors, never at call sites, so switching
/// it re-routes every op at once.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum OffloadMode {
    /// Every op runs inline on the caller's thread. The operator kill switch.
    Off,
    /// Maintenance-lane reads, `flush_wal_sync`, `run_section`, and `stats_snapshot` offload;
    /// Event-lane reads and every other write run inline. Keeps the event path off the blocking pool
    /// while still isolating maintenance storms and the fsync syscall.
    Maintenance,
    /// Every op offloads. The default operating point.
    #[default]
    All,
}

impl FromStr for OffloadMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().as_str() {
            "off" => Ok(Self::Off),
            "maintenance" => Ok(Self::Maintenance),
            "all" => Ok(Self::All),
            other => Err(format!(
                "invalid COHORT_STORE_OFFLOAD_MODE {other:?}: expected \"off\", \"maintenance\", or \"all\""
            )),
        }
    }
}

/// The two independent permit lanes. Separating them keeps a maintenance storm from starving
/// event-path reads through one FIFO pool.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReadLane {
    /// Event-path reads on the hot path (event fold pre-read, stage-2 compose, tombstone redirect).
    Event,
    /// Bulk/background reads (sweep prefetch, boot rebuild scans, GC/redrive scans).
    Maintenance,
}

impl ReadLane {
    /// The `lane` label value for the in-flight gauge.
    fn label(self) -> &'static str {
        match self {
            ReadLane::Event => LANE_EVENT,
            ReadLane::Maintenance => LANE_MAINTENANCE,
        }
    }
}

/// Resolved offload settings. `0` permits disables the bound on that lane (no semaphore).
#[derive(Clone, Copy, Debug)]
pub struct OffloadConfig {
    pub mode: OffloadMode,
    pub event_read_permits: usize,
    pub maintenance_permits: usize,
}

/// The async store surface handed to production code. Cheap to clone: the inner [`CohortStore`] is
/// `Arc`-backed and the permit lanes are shared `Arc<Semaphore>`s.
#[derive(Clone)]
pub struct StoreHandle {
    store: CohortStore,
    mode: OffloadMode,
    /// `None` = the lane is unbounded (no permit acquired).
    event_permits: Option<Arc<Semaphore>>,
    maintenance_permits: Option<Arc<Semaphore>>,
}

impl StoreHandle {
    pub fn new(store: CohortStore, config: OffloadConfig) -> Self {
        // `0` = unbounded: model it as the absence of a semaphore so the offload path skips permit
        // acquisition entirely.
        let lane = |permits: usize| (permits > 0).then(|| Arc::new(Semaphore::new(permits)));
        Self {
            store,
            mode: config.mode,
            event_permits: lane(config.event_read_permits),
            maintenance_permits: lane(config.maintenance_permits),
        }
    }

    fn lane_permits(&self, lane: ReadLane) -> Option<&Arc<Semaphore>> {
        match lane {
            ReadLane::Event => self.event_permits.as_ref(),
            ReadLane::Maintenance => self.maintenance_permits.as_ref(),
        }
    }

    /// Whether a read on `lane` runs inline under the current mode. Off is always inline; under
    /// Maintenance only the Event lane is inline (maintenance offloads); under All nothing is inline.
    fn read_runs_inline(&self, lane: ReadLane) -> bool {
        match self.mode {
            OffloadMode::Off => true,
            OffloadMode::Maintenance => matches!(lane, ReadLane::Event),
            OffloadMode::All => false,
        }
    }

    // --- Internal executors: the only places `mode` is matched. ---

    /// Run a read op, offloading per mode + lane. Inline runs record no offload metrics, so Off adds
    /// no measurement overhead; the rocks-level metrics inside `CohortStore` fire on both paths.
    async fn read<T, F>(&self, op: &'static str, lane: ReadLane, f: F) -> Result<T, StoreError>
    where
        T: Send + 'static,
        F: FnOnce(&CohortStore) -> Result<T, StoreError> + Send + 'static,
    {
        if self.read_runs_inline(lane) {
            return f(&self.store);
        }
        self.offload(op, lane.label(), self.lane_permits(lane).cloned(), f)
            .await
    }

    /// Run a write op. Writes take no permit. Under Maintenance every write runs inline *except*
    /// `flush_wal_sync` (`is_fsync`): the fsync is the expensive syscall, memtable writes are cheap,
    /// so the fsync offloads while ordinary commits stay on the caller's thread. Under Off all
    /// inline, under All all offloaded.
    async fn write<T, F>(&self, op: &'static str, is_fsync: bool, f: F) -> Result<T, StoreError>
    where
        T: Send + 'static,
        F: FnOnce(&CohortStore) -> Result<T, StoreError> + Send + 'static,
    {
        let inline = match self.mode {
            OffloadMode::Off => true,
            OffloadMode::Maintenance => !is_fsync,
            OffloadMode::All => false,
        };
        if inline {
            return f(&self.store);
        }
        self.offload(op, LANE_WRITE, None, f).await
    }

    /// Run a whole infallible sync section (reads + writes mixed) under the [`LANE_SECTION`] label:
    /// offloads under Maintenance and All, inline under Off. `permits` is the lane the section draws
    /// from — the maintenance lane for [`Self::run_section`], `None` for the permit-free
    /// observability snapshot ([`Self::stats_snapshot`]). Keeping stats on this executor is what lets
    /// `mode` stay matched in exactly the three executors (`read`, `write`, `section`).
    async fn section<T, F>(
        &self,
        op: &'static str,
        permits: Option<Arc<Semaphore>>,
        f: F,
    ) -> Result<T, StoreError>
    where
        T: Send + 'static,
        F: FnOnce(&CohortStore) -> T + Send + 'static,
    {
        if matches!(self.mode, OffloadMode::Off) {
            return Ok(f(&self.store));
        }
        // A section's closure is infallible (it returns `T`, not `Result`); wrap it so it shares the
        // one offload path. Only teardown cancellation can then make the outer result an `Err`.
        self.offload(op, LANE_SECTION, permits, move |store| Ok(f(store)))
            .await
    }

    /// The single offload path. Acquires the lane permit on the async side (cancellable), then moves
    /// it into the blocking closure so its hold time is exactly the op's execution — never spanning
    /// the post-spawn wake, which would couple hold time to runtime saturation.
    async fn offload<T, F>(
        &self,
        op: &'static str,
        lane_label: &'static str,
        permits: Option<Arc<Semaphore>>,
        f: F,
    ) -> Result<T, StoreError>
    where
        T: Send + 'static,
        F: FnOnce(&CohortStore) -> Result<T, StoreError> + Send + 'static,
    {
        // Acquire the lane permit before spawning. We never close these semaphores, so the only
        // error variant (`AcquireError` from a closed semaphore) is unreachable.
        let permit: Option<OwnedSemaphorePermit> = match permits {
            Some(semaphore) => {
                let started = Instant::now();
                let permit = semaphore
                    .acquire_owned()
                    .await
                    .expect("store offload semaphore is never closed");
                histogram!(STORE_OFFLOAD_PERMIT_WAIT_DURATION_SECONDS, "op" => op)
                    .record(started.elapsed().as_secs_f64());
                Some(permit)
            }
            None => None,
        };

        let store = self.store.clone();
        let spawned_at = Instant::now();
        let join = tokio::task::spawn_blocking(move || {
            // First thing on the blocking thread: the spawn→start gap is the pool-queue wait.
            histogram!(STORE_OFFLOAD_QUEUE_WAIT_DURATION_SECONDS, "op" => op)
                .record(spawned_at.elapsed().as_secs_f64());

            // The in-flight gauge is maintained here, inside the closure, so it stays balanced even
            // if the caller future is dropped: the increment and its RAII decrement both live on the
            // blocking thread, which always runs to completion.
            let _inflight = InflightGuard::enter(lane_label);

            let exec_started = Instant::now();
            let result = f(&store);
            histogram!(STORE_OFFLOAD_EXEC_DURATION_SECONDS, "op" => op)
                .record(exec_started.elapsed().as_secs_f64());

            // Drop the permit here at the end of execution — moved in, released on this thread, so it
            // is held for exactly the op, never into the caller's post-await continuation.
            drop(permit);
            result
        })
        .await;

        unwrap_offload(join)?
    }

    // --- Public async surface. Each method wraps exactly one sync `CohortStore` method. ---

    /// Point-read one `cf_behavioral` value. Lane-parameterized: the event fold reads on
    /// [`ReadLane::Event`], background scans/prefetch on [`ReadLane::Maintenance`].
    pub async fn get_behavioral(
        &self,
        key: &BehavioralKey,
        lane: ReadLane,
    ) -> Result<Option<Vec<u8>>, StoreError> {
        let key = *key;
        self.read("get_behavioral", lane, move |store| {
            store.get_behavioral(&key)
        })
        .await
    }

    /// Batch-read `cf_behavioral` values, preserving input order. Lane-parameterized (event fold =
    /// Event, sweep prefetch = Maintenance). Keys are taken by value so the closure is trivially
    /// `'static`.
    pub async fn multi_get_behavioral(
        &self,
        keys: Vec<BehavioralKey>,
        lane: ReadLane,
    ) -> Result<Vec<Option<Vec<u8>>>, StoreError> {
        self.read("multi_get_behavioral", lane, move |store| {
            store.multi_get_behavioral(&keys)
        })
        .await
    }

    /// Point-read one person's `cf_person_records` value as raw bytes. The event fold reads this on
    /// the hot path (Event lane); decoding lives with the caller.
    pub async fn get_person_record(
        &self,
        key: &PersonRecordKey,
    ) -> Result<Option<Vec<u8>>, StoreError> {
        let key = *key;
        self.read("get_person_record", ReadLane::Event, move |store| {
            store.get_person_record(&key)
        })
        .await
    }

    /// Read one event's full state snapshot in a single mixed-CF `multi_get` (behavioral keys plus
    /// the optional person-record key). The event fold's hot-path read, on the Event lane. Keys are
    /// taken by value so the closure is trivially `'static`.
    pub async fn read_event_snapshot(
        &self,
        behavioral: Vec<BehavioralKey>,
        record: Option<PersonRecordKey>,
    ) -> Result<EventSnapshotRaw, StoreError> {
        self.read("read_event_snapshot", ReadLane::Event, move |store| {
            store.read_event_snapshot(&behavioral, record.as_ref())
        })
        .await
    }

    /// Point-read one `cf_stage2` value (stage-2 compose is an event-path read).
    pub async fn get_stage2(&self, key: &Stage2Key) -> Result<Option<Vec<u8>>, StoreError> {
        let key = *key;
        self.read("get_stage2", ReadLane::Event, move |store| {
            store.get_stage2(&key)
        })
        .await
    }

    /// Batch-read `cf_stage2` values, preserving input order (stage-2 compose, event path).
    pub async fn multi_get_stage2(
        &self,
        keys: Vec<Stage2Key>,
    ) -> Result<Vec<Option<Vec<u8>>>, StoreError> {
        self.read("multi_get_stage2", ReadLane::Event, move |store| {
            store.multi_get_stage2(&keys)
        })
        .await
    }

    /// Point-read one redirect tombstone (the tombstone-redirect hop is an event-path read).
    pub async fn get_tombstone(&self, key: &TombstoneKey) -> Result<Option<Vec<u8>>, StoreError> {
        let key = *key;
        self.read("get_tombstone", ReadLane::Event, move |store| {
            store.get_tombstone(&key)
        })
        .await
    }

    /// Point-read one pending-transfer outbox slot (maintenance/merge path).
    pub async fn get_pending_transfer(
        &self,
        key: &PendingTransferKey,
    ) -> Result<Option<Vec<u8>>, StoreError> {
        let key = *key;
        self.read(
            "get_pending_transfer",
            ReadLane::Maintenance,
            move |store| store.get_pending_transfer(&key),
        )
        .await
    }

    /// Scan a page of one partition's `cf_behavioral` slice (boot rebuild, maintenance lane).
    pub async fn scan_behavioral(
        &self,
        partition_id: u16,
        start_after: Option<Vec<u8>>,
        limit: usize,
    ) -> Result<Vec<(BehavioralKey, Vec<u8>)>, StoreError> {
        self.read("scan_behavioral", ReadLane::Maintenance, move |store| {
            store.scan_behavioral(partition_id, start_after.as_deref(), limit)
        })
        .await
    }

    /// Scan one person's whole `cf_behavioral` slice in lsk order (merge drain, maintenance lane).
    pub async fn scan_behavioral_prefix(
        &self,
        prefix: PersonPrefix,
    ) -> Result<Vec<(BehavioralKey, Vec<u8>)>, StoreError> {
        self.read(
            "scan_behavioral_prefix",
            ReadLane::Maintenance,
            move |store| store.scan_behavioral_prefix(prefix),
        )
        .await
    }

    /// Scan a page of one partition's `cf_pending_transfers` slice (redrive, maintenance lane).
    pub async fn scan_pending_transfers(
        &self,
        partition_id: u16,
        start_after: Option<Vec<u8>>,
        limit: usize,
    ) -> Result<Vec<(PendingTransferKey, Vec<u8>)>, StoreError> {
        self.read(
            "scan_pending_transfers",
            ReadLane::Maintenance,
            move |store| store.scan_pending_transfers(partition_id, start_after.as_deref(), limit),
        )
        .await
    }

    /// Commit an owned [`StagedBatch`] atomically. Consumes the batch, moving it into the closure.
    /// No permit — the commit cadence must never queue behind reads.
    pub async fn commit(&self, staged: StagedBatch) -> Result<(), StoreError> {
        self.write("commit", false, move |store| store.apply(&staged))
            .await
    }

    /// Clear one pending-transfer outbox slot once its transfer is acked. No permit.
    pub async fn clear_pending_transfer(&self, key: &PendingTransferKey) -> Result<(), StoreError> {
        let key = *key;
        self.write("clear_pending_transfer", false, move |store| {
            store.clear_pending_transfer(&key)
        })
        .await
    }

    /// Reclaim all state for one partition on rebalance. No permit.
    pub async fn delete_partition(&self, partition_id: u16) -> Result<(), StoreError> {
        self.write("delete_partition", false, move |store| {
            store.delete_partition(partition_id)
        })
        .await
    }

    /// Synchronously fsync the WAL, making every write so far durable. No permit — the commit cadence
    /// must not queue behind reads. Under Maintenance this offloads (the fsync is the expensive
    /// syscall) even though ordinary writes run inline.
    pub async fn flush_wal_sync(&self) -> Result<(), StoreError> {
        self.write("flush_wal_sync", true, |store| store.flush_wal_sync())
            .await
    }

    /// Run a self-contained sync store state machine (mixed reads and writes) on the blocking pool:
    /// the sanctioned context for merge drain/apply and GC, whose deep sync cores are not worth
    /// async-ifying. Draws a maintenance permit. The result is `Err` only on runtime-teardown
    /// cancellation ([`StoreError::OffloadCancelled`]).
    ///
    /// Keep each section individually short: a started blocking task cannot be cancelled, and
    /// shutdown joins started tasks — a long section extends the effective drain time.
    pub async fn run_section<T, F>(&self, op: &'static str, f: F) -> Result<T, StoreError>
    where
        T: Send + 'static,
        F: FnOnce(&CohortStore) -> T + Send + 'static,
    {
        self.section(op, self.maintenance_permits.clone(), f).await
    }

    /// Snapshot the store's cache tickers and per-CF sizes. No permit — observability must not queue
    /// behind a permit-starved maintenance lane, which is exactly when the stats matter most. Offloads
    /// under Maintenance and All (it reads many RocksDB properties, so keep it off the runtime
    /// threads); only teardown cancellation can `Err`.
    pub async fn stats_snapshot(&self) -> Result<StoreStats, StoreError> {
        // Routed through `section` with the `None` lane (no permit) so the mode match stays in the
        // three executors rather than being open-coded here.
        self.section("stats_snapshot", None, |store| store.stats_snapshot())
            .await
    }

    /// SYNCHRONOUS escape hatch: delete one partition's state on the caller's thread, bypassing the
    /// offload path entirely.
    ///
    /// The single sanctioned caller is `EventDispatcher::reclaim_stale_slice`, which runs under a
    /// DashMap shard guard where no `.await` is possible. It is rare (a post-boot partition move-in)
    /// and fast (one range tombstone per CF). Any new caller must justify the same no-await
    /// constraint — prefer the async [`Self::delete_partition`] everywhere else.
    pub fn delete_partition_blocking(&self, partition_id: u16) -> Result<(), StoreError> {
        self.store.delete_partition(partition_id)
    }
}

/// RAII in-flight gauge guard, incremented on construction and decremented on drop, both on the
/// blocking thread. Kept inside the offload closure so the gauge is balanced regardless of the
/// caller future's fate.
struct InflightGuard {
    lane: &'static str,
}

impl InflightGuard {
    fn enter(lane: &'static str) -> Self {
        gauge!(STORE_OFFLOAD_INFLIGHT, "lane" => lane).increment(1.0);
        Self { lane }
    }
}

impl Drop for InflightGuard {
    fn drop(&mut self) {
        gauge!(STORE_OFFLOAD_INFLIGHT, "lane" => self.lane).decrement(1.0);
    }
}

/// Map a `spawn_blocking` join result into a store result. A pure seam so the panic/cancel policy is
/// unit-testable.
///
/// - Panic → resume the unwind on the caller's thread: a store panic must still kill the calling
///   worker task (partition stall → lag alert). Never swallowed.
/// - Cancellation → [`StoreError::OffloadCancelled`]: reachable only at runtime teardown, when the
///   runtime cancels queued blocking tasks. Mapping it to an error (not a panic) avoids fake panic
///   telemetry during a clean shutdown.
fn unwrap_offload<T>(result: Result<T, JoinError>) -> Result<T, StoreError> {
    match result {
        Ok(value) => Ok(value),
        Err(err) if err.is_panic() => std::panic::resume_unwind(err.into_panic()),
        Err(err) if err.is_cancelled() => Err(StoreError::OffloadCancelled),
        Err(_) => unreachable!("a spawn_blocking JoinError is either a panic or a cancellation"),
    }
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;
    use std::thread::ThreadId;
    use std::time::Duration;

    use tempfile::TempDir;

    use super::*;
    use crate::store::rocks::StoreConfig;

    fn open_store(dir: &TempDir) -> CohortStore {
        CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap()
    }

    fn handle(store: CohortStore, mode: OffloadMode, permits: usize) -> StoreHandle {
        StoreHandle::new(
            store,
            OffloadConfig {
                mode,
                event_read_permits: permits,
                maintenance_permits: permits,
            },
        )
    }

    /// A single permit must serialize two concurrently-offloaded ops: the second closure must not
    /// enter while the first holds the permit, and must proceed once the first releases it. Catches a
    /// permit acquired *after* the spawn, or dropped before the op finishes — either would let the
    /// second op run concurrently.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn read_permits_bound_in_flight_ops() {
        let dir = TempDir::new().unwrap();
        let handle = handle(open_store(&dir), OffloadMode::All, 1);

        // First op: signal entry, then block until released.
        let (first_entered_tx, first_entered_rx) = mpsc::channel::<()>();
        let (release_first_tx, release_first_rx) = mpsc::channel::<()>();
        let h1 = handle.clone();
        let first = tokio::spawn(async move {
            h1.read("probe", ReadLane::Event, move |_store| {
                first_entered_tx.send(()).unwrap();
                // Hold the permit until the test releases us.
                release_first_rx.recv().unwrap();
                Ok::<_, StoreError>(())
            })
            .await
            .unwrap();
        });

        // Wait until the first op is actually inside its closure (holding the permit).
        first_entered_rx
            .recv_timeout(Duration::from_secs(5))
            .unwrap();

        // Second op: signal entry. It should be blocked on the permit and never enter yet.
        let (second_entered_tx, second_entered_rx) = mpsc::channel::<()>();
        let h2 = handle.clone();
        let second = tokio::spawn(async move {
            h2.read("probe", ReadLane::Event, move |_store| {
                second_entered_tx.send(()).unwrap();
                Ok::<_, StoreError>(())
            })
            .await
            .unwrap();
        });

        assert!(
            second_entered_rx
                .recv_timeout(Duration::from_millis(300))
                .is_err(),
            "second op entered while the first held the only permit",
        );

        // Release the first; now the second must acquire the permit and enter.
        release_first_tx.send(()).unwrap();
        second_entered_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("second op did not enter after the first released the permit");

        first.await.unwrap();
        second.await.unwrap();
    }

    /// A panic inside an offloaded op must resume-unwind on the caller, so the calling task's
    /// `JoinError` reports a panic. Catches panic-swallowing — a worker that keeps running on
    /// corrupted store invariants instead of dying.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn offload_panic_resumes_unwind_in_the_caller() {
        let dir = TempDir::new().unwrap();
        let handle = handle(open_store(&dir), OffloadMode::All, 1);

        // `run_section` draws the maintenance permit; keep a clone of the semaphore so we can confirm
        // the permit is returned after the panic — a leak would let one store panic permanently
        // starve the lane.
        let maintenance = handle.maintenance_permits.clone().unwrap();
        assert_eq!(maintenance.available_permits(), 1);

        let task = tokio::spawn(async move {
            handle
                .run_section::<(), _>("boom", |_store| panic!("store invariant violated"))
                .await
        });

        let join_err = task
            .await
            .expect_err("the panic must cross the offload boundary");
        assert!(
            join_err.is_panic(),
            "the calling task's JoinError must be a panic, not a swallowed error",
        );
        assert_eq!(
            maintenance.available_permits(),
            1,
            "the permit the panicking section held must drop back to the lane as the closure unwinds",
        );
    }

    /// `unwrap_offload` maps a cancelled join to [`StoreError::OffloadCancelled`] and re-raises a
    /// panic join. Catches a cancel misclassified as Ok or as a panic (either would corrupt shutdown
    /// telemetry or hide a real store panic).
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn cancelled_offload_maps_to_offload_cancelled() {
        // A cancelled JoinError: spawn a task that never finishes, abort it, await its handle.
        let never = tokio::spawn(async {
            std::future::pending::<()>().await;
        });
        never.abort();
        let cancelled = never.await;
        assert!(
            matches!(unwrap_offload(cancelled), Err(StoreError::OffloadCancelled)),
            "a cancelled join must map to OffloadCancelled",
        );

        // A panic JoinError: `unwrap_offload` must resume the unwind. Catch it so the test survives.
        let panicked = tokio::spawn(async { panic!("boom") }).await;
        let unwound = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            drop(unwrap_offload::<()>(panicked));
        }));
        assert!(
            unwound.is_err(),
            "a panic join must resume the unwind, not return an Err or Ok",
        );
    }

    /// In Off mode an op runs on the caller's thread and acquires no permit, even when permits are
    /// configured. Catches an Off mode that still offloads or takes a permit.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn off_mode_runs_on_the_caller_thread_without_permits() {
        let dir = TempDir::new().unwrap();
        let handle = handle(open_store(&dir), OffloadMode::Off, 1);
        let caller_thread = std::thread::current().id();

        // Snapshot permits before: 1 configured on each lane.
        let event_before = handle.event_permits.as_ref().unwrap().available_permits();
        let maint_before = handle
            .maintenance_permits
            .as_ref()
            .unwrap()
            .available_permits();
        assert_eq!(event_before, 1);
        assert_eq!(maint_before, 1);

        let ran_on: ThreadId = handle
            .read("probe", ReadLane::Event, |_store| {
                Ok::<_, StoreError>(std::thread::current().id())
            })
            .await
            .unwrap();

        assert_eq!(
            ran_on, caller_thread,
            "Off mode must run the op inline on the caller's thread, not spawn_blocking",
        );
        // Neither lane's permit count moved: Off never acquires.
        assert_eq!(
            handle.event_permits.as_ref().unwrap().available_permits(),
            1,
            "Off mode must not acquire an event-lane permit",
        );
        assert_eq!(
            handle
                .maintenance_permits
                .as_ref()
                .unwrap()
                .available_permits(),
            1,
            "Off mode must not acquire a maintenance-lane permit",
        );
    }

    #[test]
    fn offload_mode_parses_case_insensitively_and_rejects_junk() {
        assert_eq!("off".parse::<OffloadMode>().unwrap(), OffloadMode::Off);
        assert_eq!("ALL".parse::<OffloadMode>().unwrap(), OffloadMode::All);
        assert_eq!(
            "Maintenance".parse::<OffloadMode>().unwrap(),
            OffloadMode::Maintenance,
        );
        assert!("sometimes".parse::<OffloadMode>().is_err());
    }

    #[test]
    fn offload_mode_default_is_all() {
        assert_eq!(OffloadMode::default(), OffloadMode::All);
    }

    // The handle is cloned into every worker task and shared across the consume/commit loops: a
    // non-Send member must fail here, not at the distant spawn sites.
    #[test]
    fn store_handle_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<StoreHandle>();
    }
}
