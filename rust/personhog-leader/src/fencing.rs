//! Broker-enforced epoch fencing for the changelog, via per-partition
//! transactional producers.
//!
//! Each partition's owner holds a producer whose `transactional.id` is
//! derived from the partition alone. Taking ownership initializes
//! transactions for that id, which bumps the broker-side producer epoch
//! and fences every predecessor: a zombie old owner that missed its own
//! drain can no longer append to the changelog — its next produce or
//! commit fails with a fenced error at the broker, loudly, instead of
//! silently corrupting the partition's history.
//!
//! Writes are grouped into transaction windows rather than one
//! transaction each. A transactional producer admits one open
//! transaction at a time, so per-write transactions would serialize a
//! partition's writes on the commit round trip. A window opens on the
//! first write, admits concurrent writes (their records ride
//! librdkafka's normal batching), then commits once and resolves every
//! waiter. The window closes on whichever comes first: its timer, which
//! bounds ack latency at light load, or its fill threshold, so a
//! backlog commits at once instead of idling out the timer. Under light
//! load a window holds one write and costs one commit; under load the
//! commit amortizes across the window and a drain cycle is bounded by
//! the commit round trip rather than the window.
//!
//! The price of sharing a transaction is shared failure: an aborted
//! window fails all of its writes together. Readers never observe
//! aborted records (consumers run `read_committed`), so the coupling is
//! visible only as grouped retryable errors.

#[cfg(any(test, feature = "test-support"))]
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::{fmt, mem};

use common_kafka::config::KafkaConfig;
use common_kafka::transaction::{ConnectedTransactionalProducer, TransactionalProducer};
use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::client::ClientContext;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use tokio::sync::{oneshot, Notify};
use tokio::task::spawn_blocking;
use tokio::time::{sleep, timeout};
use tracing::{debug, error, warn};

use personhog_proto::personhog::types::v1::Person;

use personhog_coordination::authority::AuthorityClock;

use crate::config::{FENCING_ABORT_ATTEMPTS, FENCING_COMMIT_ATTEMPTS};
use crate::inflight::InflightTracker;
use crate::kafka::changelog_message_key;

/// The fencing scope is the partition: every owner of partition `p`
/// shares this id, so a new owner's init fences the old one.
fn transactional_id(topic: &str, partition: u32) -> String {
    format!("personhog-changelog-{topic}-p{partition}")
}

#[derive(Debug)]
pub enum FencedProduceError {
    /// This pod holds no fenced producer for the partition — ownership
    /// was never taken or was released.
    NotAcquired,
    /// The broker fenced this producer: a newer owner has initialized
    /// the partition's transactional id. This pod's claim is stale, and
    /// the records demonstrably never became visible.
    Fenced,
    /// Fenced, but the window's own outcome was never settled — so the
    /// partition has moved *and* whether these records landed is unknown.
    ///
    /// The two are independent facts and the caller needs both: the
    /// router still wants the ownership answer, while the version must
    /// stay spent because a commit that was re-issued may have succeeded
    /// on an earlier attempt. Collapsing this into `Fenced` is what let a
    /// committed record's version be handed back for reuse.
    FencedUncertain(String),
    /// Send or commit failed for an ordinary, retryable reason; the
    /// window was aborted and no record became visible.
    Failed(String),
    /// The commit neither succeeded nor demonstrably aborted, so whether
    /// the records became visible is unknown.
    ///
    /// This is not the same as failure and must not be reported as one.
    /// A caller told "aborted" retries against a cache still holding the
    /// pre-write version, and produces a second record carrying the same
    /// version as the one that may already have committed — which the
    /// writer's strict version guard resolves in favour of whichever
    /// arrived first, discarding the acked one.
    Indeterminate(String),
}

impl fmt::Display for FencedProduceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FencedProduceError::NotAcquired => write!(f, "partition fence not acquired"),
            FencedProduceError::Fenced => {
                write!(f, "producer fenced by a newer owner of the partition")
            }
            FencedProduceError::FencedUncertain(e) => write!(
                f,
                "producer fenced by a newer owner; this window's outcome is unknown: {e}"
            ),
            FencedProduceError::Failed(e) => write!(f, "fenced produce failed: {e}"),
            FencedProduceError::Indeterminate(e) => {
                write!(f, "changelog commit outcome unknown: {e}")
            }
        }
    }
}

/// State of a partition's current transaction window.
struct Gate {
    /// A window is open and accepting joiners.
    open: bool,
    /// Sends still in flight for the open window; the committer waits
    /// for zero before committing so no record can miss its own commit.
    in_flight: usize,
    /// A send in this window failed; the committer aborts instead of
    /// committing, and every waiter fails together.
    poisoned: bool,
    /// The committer is between closing the window and finishing the
    /// commit. Once it drains `in_flight` and takes `waiters`, the other
    /// fields read as idle even though `commit_transaction` is still
    /// running — this flag keeps the next window from beginning until
    /// the producer is actually free.
    committing: bool,
    /// Commit-outcome subscribers for the open window.
    waiters: Vec<oneshot::Sender<Result<(), FencedProduceError>>>,
    /// Writes admitted to the open window. Counted against the fill
    /// threshold; unlike `in_flight` it never decrements, so a window
    /// whose early writes settle quickly still fills.
    joined: usize,
    /// Fires the open window's fill close. Armed at open, consumed by
    /// the seat that reaches the threshold, cleared when the window
    /// closes.
    fill_tx: Option<oneshot::Sender<()>>,
}

impl Gate {
    /// Count a seat toward the fill threshold, closing the window early
    /// when it is reached. A close trigger, not a hard cap: seats taken
    /// while the close propagates still ride the window.
    fn admit(&mut self, fill_threshold: usize) {
        self.joined += 1;
        if self.joined >= fill_threshold {
            if let Some(tx) = self.fill_tx.take() {
                let _ = tx.send(());
            }
        }
    }
}

/// Initialize a connected producer on the blocking pool, claiming the
/// partition's transactional id. On failure the connection is discarded
/// there too — librdkafka teardown blocks — and only the error comes
/// back.
async fn init_producer(
    connected: ConnectedTransactionalProducer,
    timeout: Duration,
) -> Result<TransactionalProducer, String> {
    match spawn_blocking(move || connected.init(timeout)).await {
        Ok(Ok(ready)) => Ok(ready),
        Ok(Err((e, connected))) => {
            spawn_blocking(move || drop(connected));
            Err(format!("fence init: {e}"))
        }
        Err(e) => Err(format!("fence init join: {e}")),
    }
}

/// Send a fence to the blocking pool to die. Dropping the last
/// reference runs librdkafka's destroy, which blocks while the client
/// tears down — up to hundreds of milliseconds — and both removal sites
/// run on async workers. Best-effort: a caller (an in-flight write, the
/// settle wait) still holding the Arc pays the destroy wherever it drops
/// last, which is rarer than the common case this moves.
fn drop_fence_off_worker(fence: Arc<PartitionFence>) {
    tokio::task::spawn_blocking(move || drop(fence));
}

struct PartitionFence {
    producer: TransactionalProducer,
    /// Makes the next commit task panic, so tests can reach the arm that
    /// handles a committer which never reports. Scoped to the fence
    /// rather than a global: the tests in this binary run concurrently.
    #[cfg(any(test, feature = "test-support"))]
    panic_next_commit: AtomicBool,
    /// A std mutex, deliberately: every critical section is a handful of
    /// field updates with no await inside, and `WindowSlot`'s `Drop` must
    /// be able to release its seat synchronously.
    gate: Mutex<Gate>,
    /// Signalled when `in_flight` reaches zero.
    sends_settled: Notify,
    /// Signalled when a committing window finishes, letting blocked
    /// writers open the next one.
    window_closed: Notify,
    /// Set when the producer is left in a transaction state no later
    /// `begin_transaction` can recover from — an abort that did not land,
    /// or a commit whose outcome stayed unknown.
    ///
    /// Such a producer is still installed, so presence alone cannot tell
    /// a working fence from a dead one. This flag is what makes the
    /// distinction visible: a condemned partition answers as unowned, so
    /// the router bounces instead of retrying a dead producer, and
    /// `holds()` reports the fence missing — which is what lets
    /// `heal_fence`, on the next convergence to Serving, re-take the
    /// epoch once the pod's claim is confirmed.
    unusable: AtomicBool,
    commit_timeout: Duration,
    /// Clone of the map's repair nudge; a condemnation must be able to
    /// announce itself from wherever the commit task discovers it.
    repair_nudge: Option<Arc<Notify>>,
}

impl PartitionFence {
    /// Retire the producer: writes stop attempting it and the partition
    /// stops counting as fenced by this pod.
    fn condemn(&self, partition: u32, reason: &'static str) {
        if !self.unusable.swap(true, Ordering::Relaxed) {
            counter!(
                "personhog_leader_fence_condemned_total",
                "reason" => reason
            )
            .increment(1);
            error!(
                partition,
                reason, "changelog producer left unusable; awaiting re-acquisition"
            );
            // The only way back is a heal on a convergence to Serving, and
            // the reconcile tick that would otherwise carry it is seconds
            // away — writes bounce for that whole gap. The nudge lets the
            // coordination loop run its repair pass now; Notify stores
            // the permit, so a nudge landing before the loop listens is
            // not lost.
            if let Some(nudge) = &self.repair_nudge {
                nudge.notify_one();
            }
        }
    }

    fn is_usable(&self) -> bool {
        !self.unusable.load(Ordering::Relaxed)
    }
}

/// One seat in the open window, released on drop.
///
/// A request can vanish at any await — tonic drops the handler future
/// when the client's deadline expires or its stream resets — and the
/// seat has to come back even then, or the committer waits on an
/// in-flight count that never reaches zero and every later write on the
/// partition parks forever behind it.
struct WindowSlot {
    fence: Arc<PartitionFence>,
    released: bool,
}

impl WindowSlot {
    /// Take a seat in a window already counted as in-flight.
    fn held(fence: Arc<PartitionFence>) -> Self {
        Self {
            fence,
            released: false,
        }
    }

    /// Release the seat, optionally poisoning the window, and report
    /// whether the window is now settled.
    fn release_inner(&mut self, poison: bool) -> bool {
        let mut gate = self.fence.gate.lock().unwrap();
        gate.in_flight -= 1;
        if poison {
            gate.poisoned = true;
        }
        let settled = gate.in_flight == 0;
        drop(gate);
        if settled {
            self.fence.sends_settled.notify_waiters();
        }
        self.released = true;
        settled
    }

    /// Subscribe to the window's commit outcome and release the seat in
    /// one critical section. Both must be atomic: if the committer could
    /// take the waiter list between them, this write's record would be
    /// committed with no one left to tell.
    fn subscribe(mut self) -> oneshot::Receiver<Result<(), FencedProduceError>> {
        let (tx, rx) = oneshot::channel();
        let mut gate = self.fence.gate.lock().unwrap();
        gate.waiters.push(tx);
        gate.in_flight -= 1;
        let settled = gate.in_flight == 0;
        drop(gate);
        if settled {
            self.fence.sends_settled.notify_waiters();
        }
        self.released = true;
        rx
    }

    /// Release the seat after a failed send: the window aborts, failing
    /// this write and its window-mates together.
    fn poison(mut self) {
        self.release_inner(true);
    }
}

impl Drop for WindowSlot {
    fn drop(&mut self) {
        if !self.released {
            // A cancelled request: release the seat but do not poison.
            // Its record may already be enqueued and will ride the
            // commit; nobody is waiting for the ack, and failing the
            // window would punish the writes that are still waiting.
            //
            // The record therefore becomes durable without ever being
            // acked, and it can still sit in an open window when the
            // partition moves. That is safe because the new owner
            // acquires this partition's transactional id before reading
            // the changelog: the abandoned window can no longer commit,
            // so the record is either already below the new owner's
            // cutoff or never visible at all.
            counter!("personhog_leader_fence_slots_abandoned_total").increment(1);
            self.release_inner(false);
        }
    }
}

/// Marks a window as committing, and clears the mark on drop.
///
/// Between closing a window and finishing its commit the gate reads as
/// idle — `in_flight` is zero and the waiters have been taken — so only
/// this mark keeps the next writer from beginning a transaction the
/// producer is not free for. If the committer unwinds while it is set,
/// nothing else ever clears it: every later write parks on
/// `window_closed` until its own deadline expires, forever, and no
/// repair path looks at a gate.
struct CommittingMark {
    fence: Arc<PartitionFence>,
    partition: u32,
}

impl CommittingMark {
    fn take(fence: Arc<PartitionFence>, partition: u32) -> Self {
        {
            let mut gate = fence.gate.lock().unwrap();
            gate.open = false;
            gate.committing = true;
            // The window is closed; an unfired fill sender is stale and
            // must not linger into the next window's gate state.
            gate.fill_tx = None;
        }
        Self { fence, partition }
    }
}

impl Drop for CommittingMark {
    fn drop(&mut self) {
        // Deliberately tolerant of a poisoned gate: the mark existing is
        // what wedges the partition, so it has to come off even when the
        // lock's last holder panicked.
        let orphans = match self.fence.gate.lock() {
            Ok(mut gate) => {
                gate.committing = false;
                mem::take(&mut gate.waiters)
            }
            Err(poisoned) => {
                let mut gate = poisoned.into_inner();
                gate.committing = false;
                mem::take(&mut gate.waiters)
            }
        };
        // On the ordinary path the committer took the waiters before this
        // drops, so the list is empty. Waiters still here mean the
        // committer unwound between taking the mark and answering anyone
        // — their outcomes are unobservable, and leaving them queued
        // would park every later write forever: nothing can open a window
        // while waiters remain, and nothing would notify again. Dropping
        // their senders answers each with the doubt it earned (a closed
        // channel reads as an unobserved commit), and condemning routes
        // the partition into the same bounce-and-recover story as every
        // other producer no window can be begun from.
        if !orphans.is_empty() {
            self.fence.condemn(self.partition, "committer_unwound");
        }
        drop(orphans);
        self.fence.window_closed.notify_waiters();
    }
}

/// Holds a freshly acquired fence until the work that justified taking
/// it succeeds, and gives it back otherwise.
///
/// A warm can end without returning — its future is dropped when the
/// pod's coordination attempt is torn down, which is exactly what a lost
/// lease does. The pod records a partition as held only once the warm
/// returns, so a fence taken by a warm that never finishes belongs to no
/// partition the local self-fence knows to release: the process would
/// keep the partition's broker epoch while owning nothing, and the real
/// owner's writes would fail as fenced until it re-acquired.
pub struct FenceGuard {
    fenced: Arc<FencedChangelogProducers>,
    partition: u32,
    /// The fence this guard is answerable for. Releasing by partition
    /// alone would drop whatever happens to be installed at drop time,
    /// which after a release and a re-acquire is somebody else's
    /// producer — the same hazard `forget_fence` checks for.
    taken: Option<Arc<PartitionFence>>,
    /// Names the work the fence was taken for, so an abandon names the
    /// path that dropped mid-flight.
    context: &'static str,
    armed: bool,
}

impl FenceGuard {
    pub fn new(
        fenced: Arc<FencedChangelogProducers>,
        partition: u32,
        context: &'static str,
    ) -> Self {
        let taken = fenced.installed(partition);
        Self {
            fenced,
            partition,
            taken,
            context,
            armed: true,
        }
    }

    /// The work succeeded; the fence is now the caller's to hold.
    pub fn keep(mut self) {
        self.armed = false;
    }
}

impl Drop for FenceGuard {
    fn drop(&mut self) {
        if self.armed {
            counter!("personhog_leader_fence_abandoned_total").increment(1);
            warn!(
                partition = self.partition,
                context = self.context,
                "releasing a fence taken for work that did not finish"
            );
            match &self.taken {
                Some(fence) => self.fenced.forget_fence(self.partition, fence),
                None => self.fenced.release(self.partition),
            }
        }
    }
}

/// A partition's slot in the pre-connect pipeline: claimed while a
/// dial is in flight, then holding the parked connection.
enum Prepared {
    /// A preconnect owns the slot and is dialing. Concurrent
    /// preconnects seeing this return immediately, so at most one dial
    /// runs per partition. The claim is what bounds connection churn:
    /// the trigger fires on every convergence pass through a drain
    /// window, and without it those passes stack concurrent dials
    /// until the pod runs out of memory.
    ///
    /// The token identifies the owning dial. A dial resolves only its
    /// own claim: a stale dial whose claim was removed mid-flight (by
    /// an acquire, a release, or the sweep) must neither usurp a
    /// replacement dial's claim on success nor release it on failure —
    /// either would let convergence start extra dials, which is the
    /// churn the claim exists to prevent.
    Connecting { token: u64, since: Instant },
    /// A finished dial, parked for the next acquire to consume.
    Ready(ConnectedTransactionalProducer),
}

/// Per-partition fenced producers for the changelog. Constructed once
/// and shared; partitions are acquired at warm completion and released
/// with ownership.
pub struct FencedChangelogProducers {
    kafka: KafkaConfig,
    topic: String,
    init_timeout: Duration,
    commit_timeout: Duration,
    /// How long the broker keeps one of our windows open before
    /// abandoning it; distinct from `commit_timeout`, which bounds only
    /// this process's wait on the commit call.
    broker_txn_timeout: Duration,
    /// How long an open window admits joiners before committing, when
    /// it does not fill first.
    window: Duration,
    /// Fill threshold: joiners that close the window early. Bounds a
    /// backlog's drain cycle by the commit round trip instead of the
    /// window.
    window_max_writes: usize,
    /// Ceiling on the drain's wait for an open window to commit. Set
    /// well under the pre-revoke self-fence's allowance for a whole
    /// drain, so a shutdown with an open window does not truncate here
    /// and report a failed drain.
    settle_budget: Duration,
    partitions: DashMap<u32, Arc<PartitionFence>>,
    /// Nudged on condemnation, so the coordination loop can run a
    /// repair pass now instead of on its next reconcile tick. Carries no
    /// payload: the pass re-derives what needs converging, the same way
    /// the tick does. `None` leaves repair to the tick alone.
    repair_nudge: Option<Arc<Notify>>,
    /// Connected-but-uninitialized producers, one per partition at most,
    /// parked by `preconnect` for a later `acquire` to claim. Connection
    /// setup is the slow half of acquisition and touches no broker
    /// transactional state, so it can run ahead of the authority
    /// transition; `init_transactions` — the fencing action — still
    /// happens only inside `acquire`.
    prepared: DashMap<u32, Prepared>,
    /// Distinguishes dials, so each resolves only its own claim.
    dial_token: AtomicU64,

    /// Dials attempted, so tests can pin single-flight: the storm this
    /// guards against is invisible through public behavior until the
    /// pod is already dying.
    #[cfg(any(test, feature = "test-support"))]
    connect_attempts: AtomicUsize,

    /// Outcomes a test stages for the next produce on a partition.
    ///
    /// The uncertain outcomes need a broker fault landing inside a
    /// transaction, which no test can stage against a healthy cluster —
    /// but what the caller *does* with them is the reason they are
    /// distinguished at all, so the answers have to be reachable.
    #[cfg(any(test, feature = "test-support"))]
    staged_failures: DashMap<u32, FencedProduceError>,
}

/// Construction parameters for [`FencedChangelogProducers`], named
/// because five of them are `Duration`s: a transposed pair at a call
/// site compiles, and `main`'s wiring is executed by no test — a swapped
/// window and settle budget would ship as a 2s admission window on
/// every fenced write.
pub struct FencedProducerConfig {
    pub kafka: KafkaConfig,
    pub topic: String,
    pub init_timeout: Duration,
    pub commit_timeout: Duration,
    pub broker_txn_timeout: Duration,
    pub window: Duration,
    pub window_max_writes: usize,
    pub settle_budget: Duration,
}

impl FencedChangelogProducers {
    pub fn new(config: FencedProducerConfig) -> Self {
        let FencedProducerConfig {
            kafka,
            topic,
            init_timeout,
            commit_timeout,
            broker_txn_timeout,
            window,
            window_max_writes,
            settle_budget,
        } = config;
        Self {
            kafka,
            topic,
            init_timeout,
            commit_timeout,
            broker_txn_timeout,
            window,
            window_max_writes,
            settle_budget,
            partitions: DashMap::new(),
            repair_nudge: None,
            prepared: DashMap::new(),
            dial_token: AtomicU64::new(0),
            #[cfg(any(test, feature = "test-support"))]
            connect_attempts: AtomicUsize::new(0),
            #[cfg(any(test, feature = "test-support"))]
            staged_failures: DashMap::new(),
        }
    }

    /// Announce condemnations on `nudge`, so the coordination loop can
    /// run a repair pass immediately instead of on its next reconcile
    /// tick. The listening end is [`PodHandle::
    /// with_repair_nudge`](personhog_coordination::pod::PodHandle).
    pub fn with_repair_nudge(mut self, nudge: Arc<Notify>) -> Self {
        self.repair_nudge = Some(nudge);
        self
    }

    /// Take the partition's fence: create the transactional producer and
    /// initialize transactions, which fences every previous owner of the
    /// partition's transactional id. Runs on the blocking pool — init is
    /// a synchronous broker round trip.
    async fn acquire_installed(&self, partition: u32) -> Result<Arc<PartitionFence>, String> {
        let timeout = self.init_timeout;
        let mut start = Instant::now();
        // The two acquisition shapes differ only in when the connect
        // happened: a parked connection pays only the init round trip
        // here, and one whose init fails (it may simply have gone
        // stale) gets a single fresh connect-and-init rather than
        // failing the acquisition.
        let mut path = "cold";
        let mut producer = None;
        // The removal also clears a Connecting claim: acquisition is
        // happening now, so a dial still in flight is too late to help,
        // and losing its claim makes it discard on completion instead
        // of parking a connection nothing will consume.
        if let Some((_, Prepared::Ready(parked))) = self.prepared.remove(&partition) {
            match init_producer(parked, timeout).await {
                Ok(ready) => {
                    path = "prepared";
                    producer = Some(ready);
                }
                Err(e) => {
                    counter!("personhog_leader_fence_preconnect_total", "outcome" => "init_failed")
                        .increment(1);
                    warn!(
                        partition,
                        error = %e,
                        "prepared connection failed to init; connecting fresh"
                    );
                }
            }
        }
        let producer = match producer {
            Some(ready) => ready,
            None => {
                // Timed from here so a failed prepared attempt cannot
                // contaminate the cold path's histogram.
                start = Instant::now();
                let count_error = |e: String| {
                    counter!("personhog_leader_fence_init_total", "outcome" => "error")
                        .increment(1);
                    e
                };
                let connected = self
                    .connect_producer(partition)
                    .await
                    .map_err(count_error)?;
                init_producer(connected, timeout)
                    .await
                    .map_err(count_error)?
            }
        };
        counter!("personhog_leader_fence_init_total", "outcome" => "ok").increment(1);
        histogram!("personhog_leader_fence_init_ms", "path" => path)
            .record(start.elapsed().as_secs_f64() * 1000.0);
        let installed = Arc::new(PartitionFence {
            producer,
            gate: Mutex::new(Gate {
                open: false,
                in_flight: 0,
                joined: 0,
                fill_tx: None,
                poisoned: false,
                committing: false,
                waiters: Vec::new(),
            }),
            sends_settled: Notify::new(),
            window_closed: Notify::new(),
            #[cfg(any(test, feature = "test-support"))]
            panic_next_commit: AtomicBool::new(false),
            unusable: AtomicBool::new(false),
            commit_timeout: self.commit_timeout,
            repair_nudge: self.repair_nudge.clone(),
        });
        if let Some(replaced) = self.partitions.insert(partition, Arc::clone(&installed)) {
            // The heal path installs over a still-present condemned
            // fence, and by then the commit task has usually dropped its
            // clones — making this insert the last reference and its
            // drop a blocking librdkafka destroy. Send it to the
            // blocking pool like every other eviction site.
            drop_fence_off_worker(replaced);
        }
        Ok(installed)
    }

    /// Take the partition's fence, discarding the handle. The caller
    /// relies on the map rather than on holding the fence itself.
    pub async fn acquire(&self, partition: u32) -> Result<(), String> {
        self.acquire_installed(partition).await.map(|_| ())
    }

    /// The fence currently installed for a partition, if any.
    fn installed(&self, partition: u32) -> Option<Arc<PartitionFence>> {
        self.partitions.get(&partition).map(|f| Arc::clone(&f))
    }

    /// Drop the partition's fence with ownership. The broker-side epoch
    /// survives; only a future owner's init advances it.
    pub fn release(&self, partition: u32) {
        if let Some((_, fence)) = self.partitions.remove(&partition) {
            drop_fence_off_worker(fence);
        }
        self.discard_prepared(partition);
    }

    /// Connect the partition's producer ahead of acquisition, so the
    /// acquire that follows pays only the init round trip. Runs the
    /// connection on the blocking pool and parks it; a failure is only
    /// logged and counted, because the cold acquire path covers it.
    /// Single-flight per partition: the slot is claimed before the dial
    /// begins, so however often convergence fires this through a drain
    /// window, one dial runs and the rest return as coalesced.
    pub async fn preconnect(&self, partition: u32) {
        // The claim must precede the dial, and the entry guard must not
        // be held across it: the guard holds a shard lock.
        let token = self.dial_token.fetch_add(1, Ordering::Relaxed);
        match self.prepared.entry(partition) {
            Entry::Occupied(_) => {
                // Another preconnect is dialing or already parked a
                // connection; either way this call has nothing to add.
                counter!("personhog_leader_fence_preconnect_total", "outcome" => "coalesced")
                    .increment(1);
                return;
            }
            Entry::Vacant(slot) => {
                slot.insert(Prepared::Connecting {
                    token,
                    since: Instant::now(),
                });
            }
        }
        let start = Instant::now();
        match self.connect_producer(partition).await {
            Ok(connected) => {
                counter!("personhog_leader_fence_preconnect_total", "outcome" => "ok").increment(1);
                histogram!("personhog_leader_fence_preconnect_ms")
                    .record(start.elapsed().as_secs_f64() * 1000.0);
                self.park(partition, token, connected);
            }
            Err(e) => {
                counter!("personhog_leader_fence_preconnect_total", "outcome" => "error")
                    .increment(1);
                warn!(partition, error = %e, "fence preconnect failed; acquisition will connect cold");
                // Release the claim so a later preconnect can retry —
                // but only this dial's own claim. A replacement dial's
                // claim, or a parked connection, stays.
                self.prepared.remove_if(
                    &partition,
                    |_, slot| matches!(slot, Prepared::Connecting { token: t, .. } if *t == token),
                );
            }
        }
    }

    /// Park a finished dial, unless its claim is gone (a release, a
    /// sweep, or an acquire that went cold discarded it): a discarded
    /// partition must not resurrect, so the late connection is dropped
    /// instead. The token check makes ownership exact — a stale dial
    /// finding a replacement dial's claim here must not usurp it, or
    /// the replacement's own park would discard the newer connection
    /// while later convergence passes see whatever raced in.
    fn park(&self, partition: u32, token: u64, connected: ConnectedTransactionalProducer) {
        match self.prepared.entry(partition) {
            Entry::Occupied(mut slot) if matches!(slot.get(), Prepared::Connecting { token: t, .. } if *t == token) =>
            {
                slot.insert(Prepared::Ready(connected));
            }
            _ => {
                counter!("personhog_leader_fence_preconnect_total", "outcome" => "discarded")
                    .increment(1);
                spawn_blocking(move || drop(connected));
            }
        }
    }

    /// Build the partition's connected-but-uninitialized producer on the
    /// blocking pool.
    async fn connect_producer(
        &self,
        partition: u32,
    ) -> Result<ConnectedTransactionalProducer, String> {
        #[cfg(any(test, feature = "test-support"))]
        self.connect_attempts.fetch_add(1, Ordering::SeqCst);
        let kafka = self.kafka.clone();
        let tid = transactional_id(&self.topic, partition);
        let timeout = self.init_timeout;
        let broker_txn_timeout = self.broker_txn_timeout;
        spawn_blocking(move || {
            ConnectedTransactionalProducer::connect_bounded(
                &kafka,
                &tid,
                timeout,
                broker_txn_timeout,
            )
        })
        .await
        .map_err(|e| format!("fence connect join: {e}"))?
        .map_err(|e| format!("fence connect: {e}"))
    }

    /// Drop a parked connection on the blocking pool — librdkafka's
    /// client teardown blocks, same as a full fence's. A Connecting
    /// claim is removed without a drop: its dial discards on
    /// completion once the claim is gone.
    fn discard_prepared(&self, partition: u32) {
        if let Some((_, Prepared::Ready(connected))) = self.prepared.remove(&partition) {
            spawn_blocking(move || drop(connected));
        }
    }

    /// Discard every parked connection. A connection is normally
    /// consumed within its drain window, seconds after parking; one
    /// still here at the periodic sweep belongs to an acquire that went
    /// cold first or to a cancelled inbound handoff — and a cancelled
    /// inbound handoff leaves no convergence behind to notice it, so
    /// the sweep is the only owner its lifetime has. A drain window
    /// that happens to straddle the sweep tick loses its head start and
    /// acquires cold, which is the behavior this whole path improves on
    /// rather than a failure.
    pub fn sweep_prepared(&self) {
        // Every live dial is bounded by the init timeout, so a claim
        // twice that old has no owner left to resolve it (its task
        // panicked or was torn down). Clearing it un-wedges preconnect
        // for the partition; correctness never depended on the claim,
        // acquisition just goes cold.
        let stale_claim_bound = self.init_timeout * 2;
        let now = Instant::now();
        let slots: Vec<u32> = self.prepared.iter().map(|entry| *entry.key()).collect();
        for partition in slots {
            // remove_if re-checks the slot under the shard lock, so a
            // dial that parks between the scan and this removal is not
            // swept as a stale claim.
            match self.prepared.remove_if(&partition, |_, slot| match slot {
                Prepared::Ready(_) => true,
                Prepared::Connecting { since, .. } => {
                    now.duration_since(*since) > stale_claim_bound
                }
            }) {
                Some((_, Prepared::Ready(connected))) => {
                    counter!("personhog_leader_fence_preconnect_total", "outcome" => "swept")
                        .increment(1);
                    warn!(
                        partition,
                        "swept a parked changelog connection nothing consumed"
                    );
                    spawn_blocking(move || drop(connected));
                }
                Some((_, Prepared::Connecting { .. })) => {
                    counter!("personhog_leader_fence_preconnect_total", "outcome" => "orphaned")
                        .increment(1);
                    warn!(partition, "cleared an orphaned preconnect claim");
                }
                None => {}
            }
        }
    }

    /// Whether a parked connection exists for the partition.
    #[cfg(any(test, feature = "test-support"))]
    pub fn has_prepared(&self, partition: u32) -> bool {
        self.prepared
            .get(&partition)
            .is_some_and(|slot| matches!(*slot, Prepared::Ready(_)))
    }

    /// How many dials have been attempted.
    #[cfg(any(test, feature = "test-support"))]
    pub fn connect_attempts_for_test(&self) -> usize {
        self.connect_attempts.load(Ordering::SeqCst)
    }

    /// Stage a Connecting claim of a given age, standing in for a dial
    /// whose task died without resolving it.
    #[cfg(any(test, feature = "test-support"))]
    pub fn stage_connecting_for_test(&self, partition: u32, age: Duration) {
        let token = self.dial_token.fetch_add(1, Ordering::Relaxed);
        self.prepared.insert(
            partition,
            Prepared::Connecting {
                token,
                since: Instant::now() - age,
            },
        );
    }

    /// Whether a Connecting claim holds the partition's slot.
    #[cfg(any(test, feature = "test-support"))]
    pub fn has_connecting_claim_for_test(&self, partition: u32) -> bool {
        self.prepared
            .get(&partition)
            .is_some_and(|slot| matches!(*slot, Prepared::Connecting { .. }))
    }

    /// Whether this pod holds a *usable* fence for the partition.
    ///
    /// Deliberately not mere presence. A condemned producer is still
    /// installed, and answering "yes" for one would tell the repair pass
    /// that a partition it must re-acquire needs nothing — which is
    /// exactly how such a partition stayed unwritable until a handoff
    /// moved it.
    pub fn holds(&self, partition: u32) -> bool {
        self.partitions
            .get(&partition)
            .is_some_and(|fence| fence.is_usable())
    }

    /// Commit the partition's open window before its owner gives it up.
    ///
    /// A request cancelled mid-produce takes its handler — and the
    /// drain's in-flight count — with it, leaving the record it enqueued
    /// in a window nobody is waiting on. Left alone, that window's fate
    /// falls to whichever acts first: this pod's own committer, or the
    /// successor's `init_transactions` aborting it at the broker. Waiting
    /// here settles it in the successor's favour, so a cancelled client's
    /// changes land instead of being discarded by a race.
    ///
    /// Deliberately best-effort. Refusing to hand over a partition whose
    /// window did not settle would buy nothing: a producer that cannot
    /// report its outcome is a producer the broker will not accept
    /// another record from, so the records cannot grow after this point
    /// whatever we do — and the successor's init aborts what is left,
    /// exactly as it did before this wait existed. What refusing *does*
    /// cost is the partition: the drain has already fenced writes, and
    /// there is no branch that un-fences one whose handoff never
    /// completed.
    pub async fn settle(&self, partition: u32) {
        let Some(fence) = self.installed(partition) else {
            // A write that met a condemned producer already gave the
            // fence up, which is the ordinary shape after a condemnation
            // — recorded rather than silent, or the series has no
            // denominator.
            counter!("personhog_leader_fence_settle_total", "outcome" => "absent").increment(1);
            return;
        };
        // Bounded well under the broker's own patience for the window.
        // The wait exists to catch a committer that is about to fire
        // anyway — it sleeps for the window, five milliseconds by
        // default, then commits — so seconds of budget only help when
        // the commit is retrying, which is the case where the
        // successor's abort is the right answer regardless. The cap
        // matters because the pre-revoke self-fence allows three seconds
        // for a whole drain: a budget derived from the lease alone
        // reaches about 6s at the production TTL, so every shutdown with an
        // open window would truncate here and report a failed drain.
        let budget = self.settle_budget;
        let waited = timeout(budget, async {
            loop {
                // Register before inspecting, or a close landing between
                // the two is lost and this waits on a wakeup already
                // spent.
                let closed = fence.window_closed.notified();
                tokio::pin!(closed);
                closed.as_mut().enable();
                {
                    let gate = fence.gate.lock().unwrap();
                    if !gate.open && !gate.committing && gate.in_flight == 0 {
                        return;
                    }
                }
                closed.await;
            }
        })
        .await;

        let outcome = if waited.is_err() {
            "timeout"
        } else if !fence.is_usable() {
            // Condemned somewhere in this partition's history, so this
            // producer has nothing left to give the changelog.
            "unusable"
        } else {
            "settled"
        };
        counter!("personhog_leader_fence_settle_total", "outcome" => outcome).increment(1);
        if outcome != "settled" {
            warn!(
                partition,
                outcome,
                "changelog window did not settle before the drain; leaving what remains to the \
                 incoming owner's init"
            );
        }
    }

    /// Put the partition's producer into the state a failed abort or an
    /// unknown commit leaves it in.
    ///
    /// Reaching that state for real takes a broker fault landing inside a
    /// transaction, which no test can stage against a healthy cluster —
    /// but what happens *afterwards* is the entire reason the state is
    /// tracked, so the aftermath has to be reachable.
    /// Hold the partition's gate in the state a commit in flight leaves
    /// it, so a writer arriving now parks instead of opening a window.
    ///
    /// The wake path is otherwise unreachable from a test: parking
    /// requires arriving inside the commit's own round trip, which is
    /// milliseconds wide and not something a test can aim at. Staging the
    /// gate directly is what makes the interleaving deterministic rather
    /// than statistical.
    #[cfg(any(test, feature = "test-support"))]
    pub fn begin_committing_for_test(&self, partition: u32) {
        if let Some(fence) = self.partitions.get(&partition) {
            let mut gate = fence.gate.lock().unwrap();
            gate.open = false;
            gate.committing = true;
        }
    }

    /// Release that gate and wake the parked writers, as a finishing
    /// commit does.
    #[cfg(any(test, feature = "test-support"))]
    pub fn finish_committing_for_test(&self, partition: u32) {
        if let Some(fence) = self.partitions.get(&partition) {
            fence.gate.lock().unwrap().committing = false;
            fence.window_closed.notify_waiters();
        }
    }

    /// Poison the partition's open window, as a send that failed inside
    /// it does.
    ///
    /// A real poisoning needs a produce to fail mid-window against a
    /// broker that is otherwise healthy enough to have opened one, which
    /// is not stageable — but what the commit path does with a poisoned
    /// window is the whole reason the flag exists.
    #[cfg(any(test, feature = "test-support"))]
    pub fn poison_window_for_test(&self, partition: u32) {
        if let Some(fence) = self.installed(partition) {
            fence.gate.lock().unwrap().poisoned = true;
        }
    }

    /// Stage a committer that unwound between taking the mark and
    /// answering its subscribers — the shape a runtime teardown or a
    /// panic in the settle wait leaves behind. Real unwinds are not
    /// stageable deterministically; what matters is the mark's cleanup.
    #[cfg(any(test, feature = "test-support"))]
    pub fn orphan_committer_for_test(&self, partition: u32) {
        if let Some(fence) = self.installed(partition) {
            let mark = CommittingMark::take(Arc::clone(&fence), partition);
            let (tx, _rx) = oneshot::channel();
            fence.gate.lock().unwrap().waiters.push(tx);
            drop(mark);
        }
    }

    /// Stage a committer that never reports its outcome. The real path
    /// needs the runtime to tear the task down mid-commit, which no test
    /// can arrange against a live producer.
    #[cfg(any(test, feature = "test-support"))]
    pub fn panic_next_commit_for_test(&self, partition: u32) {
        if let Some(fence) = self.installed(partition) {
            fence.panic_next_commit.store(true, Ordering::SeqCst);
        }
    }

    /// Drop the open window's commit-outcome subscribers without
    /// answering them, as a committer that vanished mid-commit leaves
    /// them. `spawn_blocking` work is not cancelled when its handle is
    /// dropped, so the commit it was running may well have landed.
    #[cfg(any(test, feature = "test-support"))]
    pub fn abandon_waiters_for_test(&self, partition: u32) {
        if let Some(fence) = self.partitions.get(&partition) {
            let taken = mem::take(&mut fence.gate.lock().unwrap().waiters);
            drop(taken);
        }
    }

    /// Make the next produce on this partition answer with `outcome`.
    #[cfg(any(test, feature = "test-support"))]
    pub fn stage_failure_for_test(&self, partition: u32, outcome: FencedProduceError) {
        self.staged_failures.insert(partition, outcome);
    }

    #[cfg(any(test, feature = "test-support"))]
    pub fn condemn_for_test(&self, partition: u32) {
        if let Some(fence) = self.partitions.get(&partition) {
            fence.condemn(partition, "test");
        }
    }

    /// Produce one changelog record inside the partition's current
    /// transaction window, returning its offset once the window commits.
    pub async fn produce(
        &self,
        partition: u32,
        person: &Person,
    ) -> Result<i64, FencedProduceError> {
        #[cfg(any(test, feature = "test-support"))]
        if let Some((_, staged)) = self.staged_failures.remove(&partition) {
            return Err(staged);
        }
        let durable_start = Instant::now();
        let fence = self
            .partitions
            .get(&partition)
            .map(|f| Arc::clone(&f))
            .ok_or_else(|| {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                FencedProduceError::NotAcquired
            })?;

        // Join the open window, or open one. A window mid-commit admits
        // no joiners; wait for it to close and retry.
        let join_start = Instant::now();
        let opened = loop {
            // Checked every iteration, not only on the way in. A
            // condemned producer cannot begin another transaction, and
            // the commit that condemns it is the same one whose end wakes
            // whoever is parked below — so a check placed after the park
            // is skipped by exactly the writer it exists for, which then
            // opens a window on a dead producer and answers with a
            // retryable failure instead of the ownership bounce that gets
            // the partition re-acquired.
            if !fence.is_usable() {
                self.forget_fence(partition, &fence);
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                return Err(FencedProduceError::NotAcquired);
            }
            // Register interest before inspecting the gate: a close that
            // fires between the check and the await must not be lost.
            let closed = fence.window_closed.notified();
            tokio::pin!(closed);
            closed.as_mut().enable();
            // Only the gate's own fields are touched under its lock.
            // Classifying a failure consults the producer's fatal state
            // and can evict the fence, so it happens after the guard is
            // gone: the gate is a std mutex, and a panic while it is held
            // poisons it for every writer on the partition.
            let begin_failed = {
                let mut gate = fence.gate.lock().unwrap();
                if gate.open {
                    gate.in_flight += 1;
                    gate.admit(self.window_max_writes);
                    break None;
                }
                if !gate.committing && gate.in_flight == 0 && gate.waiters.is_empty() {
                    // Idle: open a new window. BeginTxn is a local
                    // librdkafka state transition, safe inline.
                    match fence.producer.inner().begin_transaction() {
                        Ok(()) => {
                            let (fill_tx, fill_rx) = oneshot::channel();
                            gate.open = true;
                            gate.in_flight = 1;
                            gate.joined = 0;
                            gate.poisoned = false;
                            gate.fill_tx = Some(fill_tx);
                            gate.admit(self.window_max_writes);
                            break Some(fill_rx);
                        }
                        Err(e) => Some(e),
                    }
                } else {
                    None
                }
            };
            if let Some(e) = begin_failed {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                return Err(self.classify(&fence, partition, e));
            }
            closed.await;
        };
        // Near-zero when a window was open or the producer idle; the tail
        // is time parked behind a draining or committing window — the
        // queueing term of the fencing tax, and the first thing to grow
        // if commits slow down.
        // From here the window counts this write as in flight; the slot
        // returns the seat on every exit, including cancellation.
        let slot = WindowSlot::held(Arc::clone(&fence));
        histogram!("personhog_leader_fence_window_wait_ms", "partition" => partition.to_string())
            .record(join_start.elapsed().as_secs_f64() * 1000.0);

        if let Some(fill) = opened {
            let fence_for_commit = Arc::clone(&fence);
            let window = self.window;
            let topic = self.topic.clone();
            let part = partition;
            tokio::spawn(async move {
                commit_window_after(fence_for_commit, window, fill, topic, part).await;
            });
        }

        // Send within the open window; the record rides librdkafka's
        // ordinary batching alongside its window-mates.
        let key = changelog_message_key(person.team_id, person.id);
        let payload = person.encode_to_vec();
        // Same metric as the unfenced path in kafka.rs, so the size
        // distribution covers all changelog produces regardless of the
        // fencing rollout. Recorded before the send so a payload rejected
        // by the broker (message.max.bytes) still shows up.
        histogram!("personhog_leader_kafka_produce_bytes").record(payload.len() as f64);
        let record = FutureRecord::to(&self.topic)
            .partition(partition as i32)
            .key(&key)
            .payload(&payload);
        let produce_start = Instant::now();
        let delivery = fence.producer.inner().send_result(record);

        let offset = match delivery {
            Ok(fut) => match fut.await {
                Ok(Ok((_, offset))) => {
                    histogram!("personhog_leader_fence_send_ms")
                        .record(produce_start.elapsed().as_secs_f64() * 1000.0);
                    Ok(offset)
                }
                // These fire per write, and a broker outage fails every
                // write, so the aggregate is the useful signal and the
                // per-request detail belongs at debug. The caller logs
                // the classified outcome, and the counters below carry
                // the rate.
                Ok(Err((e, _))) => {
                    debug!(partition, error = %e, "fenced send delivery failed");
                    Err(Some(e))
                }
                Err(_cancelled) => {
                    debug!(partition, "fenced send cancelled");
                    Err(None)
                }
            },
            Err((e, _)) => {
                debug!(partition, error = %e, "fenced send enqueue failed");
                Err(Some(e))
            }
        };

        // A failed send poisons the window (the committer aborts it) and
        // returns immediately with its own classified error — a fenced
        // rejection must surface as `Fenced`, not as the window's
        // generic abort.
        if let Err(send_err) = offset {
            counter!("personhog_leader_kafka_produce_errors_total").increment(1);
            slot.poison();
            return Err(match send_err {
                Some(e) => self.classify(&fence, partition, e),
                None => FencedProduceError::Failed("send cancelled (timeout)".to_string()),
            });
        }
        let offset = offset.expect("checked above");

        let rx = slot.subscribe();

        // The record exists but is invisible until the window commits;
        // the ack must wait for the commit outcome. Together with the
        // window-wait and send spans this completes the caller-visible
        // decomposition of a fenced produce.
        let ack_wait_start = Instant::now();
        let outcome = rx.await;
        histogram!("personhog_leader_fence_ack_wait_ms", "partition" => partition.to_string())
            .record(ack_wait_start.elapsed().as_secs_f64() * 1000.0);
        match outcome {
            Ok(Ok(())) => {
                counter!("personhog_leader_kafka_produces_total").increment(1);
                // The same series the unfenced path records: time from
                // entering produce to a durable record, so the two flag
                // arms stay comparable.
                histogram!("personhog_leader_kafka_produce_duration_ms")
                    .record(durable_start.elapsed().as_secs_f64() * 1000.0);
                Ok(offset)
            }
            Ok(Err(e)) => {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                // The commit reported the fence, so the eviction has to
                // happen here: `commit_window_after` runs detached and
                // holds no handle to the fence map. Without this the dead
                // producer stays installed, later writes discover the
                // fence one failed `begin_transaction` at a time, and
                // `holds()` reports authority this pod no longer has.
                if matches!(
                    e,
                    FencedProduceError::Fenced | FencedProduceError::FencedUncertain(_)
                ) {
                    self.forget_fence(partition, &fence);
                }
                Err(e)
            }
            // The committer dropped its senders without answering, so
            // nobody observed whether the commit landed — and
            // `spawn_blocking` work is not cancelled when its handle is
            // dropped, so it may well have. Reporting a definite abort
            // here frees a version whose record may exist.
            Err(_) => {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                Err(FencedProduceError::Indeterminate(
                    "commit task dropped without reporting an outcome".to_string(),
                ))
            }
        }
    }

    /// Classify a transaction error, removing the fence on a broker
    /// fence rejection so subsequent writes fail fast as stale. The
    /// fenced signal often hides behind a local symptom — librdkafka
    /// purges queued messages once the producer turns fatal — so the
    /// producer's fatal error is consulted alongside the surface error.
    fn classify(
        &self,
        fence: &Arc<PartitionFence>,
        partition: u32,
        e: KafkaError,
    ) -> FencedProduceError {
        if is_fenced(&e) || producer_fenced(fence.producer.inner()) {
            counter!(
                "personhog_leader_produce_fenced_total",
                "partition" => partition.to_string()
            )
            .increment(1);
            error!(
                partition,
                error = %e,
                "changelog producer fenced by a newer owner — this pod's claim is stale"
            );
            self.forget_fence(partition, fence);
            FencedProduceError::Fenced
        } else {
            FencedProduceError::Failed(e.to_string())
        }
    }

    /// Drop a fence that the broker rejected, but only if it is still the
    /// one installed: a write can be in flight across a release and a
    /// re-acquire, and the stale producer's failure must not evict its
    /// live replacement.
    fn forget_fence(&self, partition: u32, fence: &Arc<PartitionFence>) {
        let removed = self
            .partitions
            .remove_if(&partition, |_, installed| Arc::ptr_eq(installed, fence));
        if let Some((_, evicted)) = removed {
            drop_fence_off_worker(evicted);
            // The escalation signal for a partition giving up its fence
            // outside the orderly release path — the series exists so a
            // deploy-window burst of these is visible.
            counter!(
                "personhog_leader_fenced_partition_drops_total",
                "partition" => partition.to_string()
            )
            .increment(1);
        }
    }
}

/// How many times a retriable commit is re-attempted before its outcome
/// is declared unknown.
///
/// Derived from the attempt budget the lease runway affords, rather than
/// chosen independently: `validate_fencing_timescales` sizes the fencing
/// timeouts so that exactly this many attempts still fit inside the
/// window the keepalive reserves for self-fencing.
const COMMIT_RETRIES: usize = FENCING_COMMIT_ATTEMPTS as usize - 1;

/// What is known about a window's records after a failed commit, and
/// whether the producer survived learning it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CommitOutcome {
    /// The transaction is definitely aborted; nothing became visible.
    Aborted,
    /// Definitely aborted, but the abort never landed, so the producer is
    /// stuck in a state it cannot begin another transaction from.
    AbortedProducerDead,
    /// Whether the records committed is not known.
    ///
    /// There is no healthy-producer form of this: a commit fails without
    /// a definite outcome only when the error is neither retriable nor
    /// abort-requiring, which is librdkafka's fatal class, or when the
    /// follow-up abort itself failed. Both leave the producer unusable.
    Unknown,
}

/// What a failed window means for its writers.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum WindowVerdict {
    /// A newer owner holds the partition; the records never landed.
    Fenced,
    /// A newer owner holds the partition and the records' fate is
    /// unknown — both facts, because they answer different questions.
    FencedUncertain,
    /// The window aborted for an ordinary reason; safe to retry.
    Aborted,
    /// Whether the records landed is unknown.
    Indeterminate,
}

/// Whether the partition moved and whether the records landed are
/// independent, so the verdict carries both.
///
/// A commit can time out, be re-issued by librdkafka itself, and only
/// then report the fence — by which point an earlier attempt may already
/// have succeeded. Reporting that as a plain fence tells the caller the
/// record does not exist, which frees its version and puts a second
/// record at the same number behind one that may be committed. Reporting
/// it as merely indeterminate throws away the ownership answer the router
/// bounces on. `FencedUncertain` is both.
/// Every reason production code passes to `condemn`, in one place so the
/// preregistration below cannot drift from the call sites: a reason
/// missing here first appears as a brand-new series mid-incident instead
/// of rising from zero.
const CONDEMN_REASONS: [&str; 6] = [
    "abort_fenced",
    "abort_failed",
    "commit_fenced",
    "commit_indeterminate",
    "commit_task_lost",
    "committer_unwound",
];

/// Why a window's outcome leaves the producer unusable, if it does.
///
/// Extracted so the arrow *into* the condemned state is reachable: the
/// tests could reach the aftermath through a staging hook, but the branch
/// that decides it could be deleted outright with the suite still green,
/// and it is the only path in production that ever sets the flag.
///
/// A dead producer carries two very different stories, split by
/// `fenced`: a producer fenced by a newer owner's init lost the epoch (a
/// handoff, a heal, a zombie being cut off — coordination working), while
/// an abort that failed on a producer nobody fenced means the broker
/// could not be reached in time (an infrastructure excursion). The panel
/// reading this label has to tell those apart without the logs.
fn condemn_reason(outcome: CommitOutcome, fenced: bool) -> Option<&'static str> {
    match outcome {
        CommitOutcome::Aborted => None,
        CommitOutcome::AbortedProducerDead if fenced => Some("abort_fenced"),
        CommitOutcome::AbortedProducerDead => Some("abort_failed"),
        // A commit killed by a newer owner's init reports librdkafka's
        // fatal class and lands here, not in AbortedProducerDead — the
        // fenced split must cover this arm or every deploy-shaped
        // condemnation reads as a broker excursion.
        CommitOutcome::Unknown if fenced => Some("commit_fenced"),
        CommitOutcome::Unknown => Some("commit_indeterminate"),
    }
}

fn window_verdict(outcome: CommitOutcome, fenced: bool) -> WindowVerdict {
    match (outcome.is_aborted(), fenced) {
        (true, true) => WindowVerdict::Fenced,
        (false, true) => WindowVerdict::FencedUncertain,
        (true, false) => WindowVerdict::Aborted,
        (false, false) => WindowVerdict::Indeterminate,
    }
}

impl CommitOutcome {
    /// Whether the records are known not to have become visible.
    fn is_aborted(self) -> bool {
        matches!(self, Self::Aborted | Self::AbortedProducerDead)
    }
}

fn is_fenced(e: &KafkaError) -> bool {
    matches!(
        e.rdkafka_error_code(),
        Some(RDKafkaErrorCode::Fenced) | Some(RDKafkaErrorCode::ProducerFenced)
    )
}

/// Whether the producer has entered the fatally-fenced state. Once a
/// newer owner initializes the transactional id, librdkafka marks this
/// client fatal and individual operations report local symptoms (purged
/// queues, aborted transactions) rather than the fence itself.
fn producer_fenced<C: ClientContext>(producer: &FutureProducer<C>) -> bool {
    producer
        .client()
        .fatal_error()
        .map(|(code, _)| {
            matches!(
                code,
                RDKafkaErrorCode::Fenced | RDKafkaErrorCode::ProducerFenced
            )
        })
        .unwrap_or(false)
}

/// Abort the window, up to the number of attempts the lease runway was
/// sized for.
///
/// Derived from the constant rather than written out, so that raising the
/// budget raises the attempts and vice versa. The two drifted apart once
/// already: the loop spent four transaction timeouts while the bound that
/// had to contain them counted one.
fn abort_window<C: ClientContext>(
    producer: &FutureProducer<C>,
    timeout: Duration,
) -> Result<(), KafkaError> {
    let mut last = producer.abort_transaction(timeout);
    let mut spent = 1;
    while last.is_err() && spent < FENCING_ABORT_ATTEMPTS {
        last = producer.abort_transaction(timeout);
        spent += 1;
    }
    last
}

/// Close the window after its admission interval: stop admitting, wait
/// for in-flight sends to settle, then commit (or abort a poisoned
/// window) and resolve every waiter with the shared outcome.
async fn commit_window_after(
    fence: Arc<PartitionFence>,
    window: Duration,
    fill: oneshot::Receiver<()>,
    topic: String,
    partition: u32,
) {
    // The fill branch also covers the sender dropping unfired, which
    // cannot happen while this window is open: the sender lives in the
    // gate of a fence this task holds, and nothing replaces it until
    // the CommittingMark below has been dropped.
    tokio::select! {
        _ = sleep(window) => {
            counter!("personhog_leader_fence_window_closed_total", "reason" => "timer")
                .increment(1);
        }
        _ = fill => {
            counter!("personhog_leader_fence_window_closed_total", "reason" => "filled")
                .increment(1);
        }
    }

    // Stop admitting joiners, then wait for outstanding sends. The mark
    // holds until this function returns — by any path — so no writer can
    // begin the next transaction while this one is still resolving, and
    // none is stranded if it unwinds.
    let _committing = CommittingMark::take(Arc::clone(&fence), partition);
    loop {
        // Register interest before inspecting the gate: a settle that
        // fires between the check and the await must not be lost.
        let settled = fence.sends_settled.notified();
        tokio::pin!(settled);
        settled.as_mut().enable();
        {
            let gate = fence.gate.lock().unwrap();
            if gate.in_flight == 0 {
                break;
            }
        }
        settled.await;
    }

    let (waiters, poisoned) = {
        let mut gate = fence.gate.lock().unwrap();
        (mem::take(&mut gate.waiters), gate.poisoned)
    };
    histogram!("personhog_leader_fence_window_writes", "partition" => partition.to_string())
        .record(waiters.len() as f64);

    // Commit and abort block up to the transaction timeout; keep them
    // off the runtime threads.
    let producer = fence.producer.inner().clone();
    let timeout = fence.commit_timeout;
    let commit_start = Instant::now();
    #[cfg(any(test, feature = "test-support"))]
    let panic_next = fence.panic_next_commit.swap(false, Ordering::SeqCst);
    let result = spawn_blocking(move || {
        #[cfg(any(test, feature = "test-support"))]
        if panic_next {
            panic!("staged commit task failure");
        }
        if poisoned {
            // One attempt. A producer left in its abortable state fails
            // every later `begin_transaction`, so a failed abort costs
            // the producer itself rather than just this window — and the
            // recovery for that is re-acquisition, whose init aborts the
            // pending transaction at the broker anyway.
            match abort_window(&producer, timeout) {
                Ok(()) => Err((KafkaError::Canceled, CommitOutcome::Aborted)),
                // The records are still definitely not visible — an abort
                // that did not land leaves the transaction open, and open
                // is not committed. What is lost is the producer: it stays
                // in its abortable state, where every later
                // `begin_transaction` fails.
                Err(e) => {
                    counter!("personhog_leader_fence_abort_failed_total").increment(1);
                    Err((e, CommitOutcome::AbortedProducerDead))
                }
            }
        } else {
            // A commit that fails is not the same as a commit that did
            // not happen. librdkafka distinguishes three cases and the
            // caller's correct behaviour differs for each: a retriable
            // failure leaves the outcome unknown and must be re-attempted
            // (commit is idempotent within the transaction); an
            // abort-requiring failure is a definite abort once the abort
            // is issued; anything else leaves the fate of the records in
            // doubt, which is a distinct answer from "failed".
            let mut attempt = producer.commit_transaction(timeout);
            for _ in 0..COMMIT_RETRIES {
                match &attempt {
                    Err(KafkaError::Transaction(e)) if e.is_retriable() => {
                        counter!("personhog_leader_fence_commit_retries_total").increment(1);
                        warn!(error = %e, "changelog commit failed; retrying");
                        attempt = producer.commit_transaction(timeout);
                    }
                    _ => break,
                }
            }
            match attempt {
                Ok(()) => Ok(()),
                Err(KafkaError::Transaction(e)) if e.txn_requires_abort() => {
                    match abort_window(&producer, timeout) {
                        Ok(()) => Err((KafkaError::Transaction(e), CommitOutcome::Aborted)),
                        // The abort itself is now in doubt, so the
                        // records are too.
                        Err(abort_err) => Err((abort_err, CommitOutcome::Unknown)),
                    }
                }
                // Neither retriable nor abort-requiring is librdkafka's
                // fatal class, which includes the fence. The transaction
                // is left open with its fate unknown and this producer
                // has no way back to a state where it can begin another;
                // whether it was *also* fenced is answered separately,
                // by the verdict, because the two facts serve different
                // callers.
                //
                // Deliberately not inferring "the first attempt cannot
                // have landed" from this loop never re-issuing:
                // `commit_transaction` re-sends EndTxn internally, so one
                // call here is not one round trip at the broker.
                Err(e) => Err((e, CommitOutcome::Unknown)),
            }
        }
    })
    .await;

    let outcome: Result<(), FencedProduceError> = match result {
        Ok(Ok(())) => {
            histogram!("personhog_leader_fence_commit_ms", "outcome" => "committed")
                .record(commit_start.elapsed().as_secs_f64() * 1000.0);
            Ok(())
        }
        Ok(Err((e, outcome))) => {
            histogram!("personhog_leader_fence_commit_ms", "outcome" => "failed")
                .record(commit_start.elapsed().as_secs_f64() * 1000.0);
            let fenced_now = is_fenced(&e) || producer_fenced(fence.producer.inner());
            if let Some(reason) = condemn_reason(outcome, fenced_now) {
                fence.condemn(partition, reason);
            }
            let verdict = window_verdict(outcome, fenced_now);
            if verdict == WindowVerdict::FencedUncertain {
                counter!(
                    "personhog_leader_produce_fenced_total",
                    "partition" => partition.to_string()
                )
                .increment(1);
                error!(
                    partition,
                    topic,
                    error = %e,
                    "changelog window fenced by a newer owner, with its own outcome unknown"
                );
                Err(FencedProduceError::FencedUncertain(e.to_string()))
            } else if verdict == WindowVerdict::Fenced {
                // A poisoned window's fence was already classified and
                // counted where the send failed; counting again here
                // would report two fences for one event.
                if !poisoned {
                    counter!(
                        "personhog_leader_produce_fenced_total",
                        "partition" => partition.to_string()
                    )
                    .increment(1);
                }
                error!(
                    partition,
                    topic,
                    error = %e,
                    "changelog window fenced by a newer owner — this pod's claim is stale"
                );
                Err(FencedProduceError::Fenced)
            } else if verdict == WindowVerdict::Aborted {
                counter!(
                    "personhog_leader_fence_aborts_total",
                    "partition" => partition.to_string()
                )
                .increment(1);
                error!(partition, topic, error = %e, "changelog window aborted");
                Err(FencedProduceError::Failed(format!("aborted: {e}")))
            } else {
                // Retries are exhausted and the transaction's fate is
                // unknown. Saying "aborted" here would invite a retry
                // that collides with a record that may already be
                // committed, so the doubt is reported as doubt.
                counter!(
                    "personhog_leader_fence_commit_indeterminate_total",
                    "partition" => partition.to_string()
                )
                .increment(1);
                error!(
                    partition,
                    topic,
                    error = %e,
                    "changelog commit outcome unknown; the window may or may not have committed"
                );
                Err(FencedProduceError::Indeterminate(e.to_string()))
            }
        }
        // The commit task itself vanished, so nothing observed the
        // transaction's fate — which leaves the transaction open and this
        // producer unable to begin another. Condemning it is what stops
        // the partition counting as fenced; without it every later write
        // retries a producer that cannot serve one, for the life of the
        // process, with nothing to escalate.
        Err(join) => {
            fence.condemn(partition, "commit_task_lost");
            Err(FencedProduceError::Indeterminate(format!(
                "commit join: {join}"
            )))
        }
    };

    for waiter in waiters {
        // A dropped receiver means the writer's request already ended;
        // nothing to deliver.
        waiter.send(clone_outcome(&outcome)).ok();
    }
}

/// Materialize every fencing series at startup so deploy-window bursts
/// land in an already-scraped series instead of being swallowed by
/// first-increment lazy registration — fence acquisition in particular
/// fires exactly during deploys. A touched histogram renders with zero
/// count until its first sample.
pub fn preregister_fencing_metrics(partitions: u32) {
    for outcome in ["ok", "error"] {
        counter!("personhog_leader_fence_init_total", "outcome" => outcome).increment(0);
    }
    // Settling fires only during handoffs, so every one of its samples
    // lands in a deploy window — the case this preregistration exists
    // for.
    for outcome in ["settled", "timeout", "unusable", "absent"] {
        counter!("personhog_leader_fence_settle_total", "outcome" => outcome).increment(0);
    }
    counter!("personhog_leader_fence_slots_abandoned_total").increment(0);
    for reason in ["timer", "filled"] {
        counter!("personhog_leader_fence_window_closed_total", "reason" => reason).increment(0);
    }
    counter!("personhog_leader_fence_abandoned_total").increment(0);
    counter!("personhog_leader_fence_abort_failed_total").increment(0);
    for outcome in [
        "ok",
        "error",
        "coalesced",
        "discarded",
        "swept",
        "orphaned",
        "init_failed",
    ] {
        counter!("personhog_leader_fence_preconnect_total", "outcome" => outcome).increment(0);
    }
    // The healing counters fire exactly during the incidents an operator
    // would reach for them in, and rarely enough that lazy registration
    // can swallow the first burst between scrapes.
    counter!("personhog_leader_fence_healed_total").increment(0);
    counter!("personhog_leader_fence_heal_abandoned_total").increment(0);
    for reason in CONDEMN_REASONS {
        counter!("personhog_leader_fence_condemned_total", "reason" => reason).increment(0);
    }
    counter!("personhog_leader_fence_commit_retries_total").increment(0);
    // The coordination loop's repair-pass counter fires exclusively
    // mid-incident, exactly when a first-increment series would be
    // swallowed between scrapes.
    for outcome in ["run", "suppressed"] {
        counter!("personhog_coordination_repair_passes_total", "outcome" => outcome).increment(0);
    }
    counter!("personhog_leader_kafka_produce_errors_total").increment(0);
    for partition in 0..partitions {
        let p = partition.to_string();
        counter!("personhog_leader_fence_aborts_total", "partition" => p.clone()).increment(0);
        counter!(
            "personhog_leader_fenced_partition_drops_total",
            "partition" => p.clone()
        )
        .increment(0);
        counter!(
            "personhog_leader_fence_heal_failures_total",
            "partition" => p.clone()
        )
        .increment(0);

        counter!(
            "personhog_leader_fence_commit_indeterminate_total",
            "partition" => p.clone()
        )
        .increment(0);
        counter!("personhog_leader_produce_fenced_total", "partition" => p).increment(0);
    }
    // Histograms are deliberately absent: the Prometheus exporter
    // renders one only once it has a sample, so there is nothing a
    // startup call can materialize.
}

/// `FencedProduceError` holds a String and cannot derive Clone cheaply
/// through the oneshot fan-out; rebuild the outcome per waiter.
fn clone_outcome(outcome: &Result<(), FencedProduceError>) -> Result<(), FencedProduceError> {
    match outcome {
        Ok(()) => Ok(()),
        Err(FencedProduceError::NotAcquired) => Err(FencedProduceError::NotAcquired),
        Err(FencedProduceError::Fenced) => Err(FencedProduceError::Fenced),
        Err(FencedProduceError::FencedUncertain(e)) => {
            Err(FencedProduceError::FencedUncertain(e.clone()))
        }
        Err(FencedProduceError::Failed(e)) => Err(FencedProduceError::Failed(e.clone())),
        Err(FencedProduceError::Indeterminate(e)) => {
            Err(FencedProduceError::Indeterminate(e.clone()))
        }
    }
}

/// Re-take the partition's fence if this pod is serving it without one.
///
/// A fence can go missing under a pod that legitimately owns its
/// partition: a broker rejection evicted it, an abort exhausted its
/// retries and left the producer unusable, or a stale pod took the epoch
/// and stepped back. Nothing in the handoff protocol repairs that —
/// convergence sees the partition warmed and unfenced and does nothing —
/// so without this the partition stays unwritable until a handoff moves
/// it.
///
/// Re-acquisition is safe only because of where this is called from and
/// what it checks. The caller is the convergence to `Serving`, so the
/// durable assignment says this pod owns the partition; the claim must
/// still be valid, because taking a fence moves the broker's epoch away
/// from whoever holds it; and a partition being locally fenced is
/// disqualifying, since that means a handoff is moving it and the
/// incoming owner's fence is the one that should stand.
/// What the healing pass did, for the caller to act on: a healed
/// partition is freshly fenced — the epoch just moved, and the same
/// convergence must not move it again — and a failure is the caller's
/// to surface, because a partition that cannot regain its fence has no
/// other repair path.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealOutcome {
    /// Nothing to do: the fence is present and usable, the partition is
    /// under handoff, or this pod cannot vouch for its claim.
    Intact,
    /// A fence was re-taken and is serving.
    Healed,
    /// A fence was taken but given back — standing lapsed or a handoff
    /// began during the broker round trip.
    Abandoned,
}

pub async fn heal_fence(
    fenced: &Arc<FencedChangelogProducers>,
    inflight: &InflightTracker,
    authority: Option<&AuthorityClock>,
    partition: u32,
) -> Result<HealOutcome, String> {
    let lost_standing = authority.is_some_and(|a| !a.is_valid());
    if lost_standing || fenced.holds(partition) || inflight.is_fenced(partition) {
        return Ok(HealOutcome::Intact);
    }
    let taken = match fenced.acquire_installed(partition).await {
        Ok(taken) => taken,
        Err(e) => {
            // Partition-labeled: a wedged partition must be attributable
            // from the series alone, because this is deliberately not a
            // run failure (see `verify_serving`) and the counter is the
            // alerting surface for it.
            counter!(
                "personhog_leader_fence_heal_failures_total",
                "partition" => partition.to_string()
            )
            .increment(1);
            error!(partition, error = %e, "failed to re-take the changelog fence");
            return Err(e);
        }
    };
    // Answerable for the installed fence from here until a deliberate
    // branch takes over. A drop *during* the acquire needs no guard —
    // the producer is discarded before it is installed, `holds()` stays
    // false, and the next convergence heals again. What the guard covers
    // is the stretch after installation: the checks below await nothing
    // today, so its teeth are a panic between them and any await a
    // future change adds. Same shape as the warm path.
    let guard = FenceGuard::new(Arc::clone(fenced), partition, "heal");
    // The round trip is long enough for the ground to move: the claim can
    // lapse, or a handoff can start draining the partition. Holding a
    // fence taken without standing is not passive — the write path trusts
    // the broker epoch rather than re-checking the claim, so a request
    // landing here would ack a mutation with an epoch taken from the
    // partition's real owner.
    let lost_standing = authority.is_some_and(|a| !a.is_valid());
    if lost_standing || inflight.is_fenced(partition) {
        guard.keep();
        // The fence this call installed, not whatever is installed now:
        // re-reading the map would match by construction and evict a
        // replacement just as readily as its own.
        fenced.forget_fence(partition, &taken);
        counter!("personhog_leader_fence_heal_abandoned_total").increment(1);
        warn!(
            partition,
            "released a fence taken while standing lapsed mid-acquire"
        );
        return Ok(HealOutcome::Abandoned);
    }
    guard.keep();
    counter!("personhog_leader_fence_healed_total").increment(1);
    warn!(
        partition,
        "re-took the changelog fence for a served partition"
    );
    Ok(HealOutcome::Healed)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The verdict the caller acts on, as a truth table over the two
    /// independent facts it combines.
    ///
    /// The cell that matters is (unknown, fenced). A commit that timed
    /// out, was re-issued — by librdkafka itself, not just by this loop —
    /// and only then discovered the fence may already have landed. Its
    /// own verdict keeps both facts: the router still gets the ownership
    /// answer it bounces on, and the version stays spent. Collapsing it
    /// into `Fenced` frees a version whose record may be committed, and
    /// collapsing it into `Indeterminate` throws away the bounce.
    /// The arrow *into* the condemned state. A producer left in a
    /// transaction it cannot leave must be given up, or the partition
    /// keeps counting as fenced and every later write retries a producer
    /// that cannot serve one, for the life of the process.
    #[test]
    fn a_producer_that_cannot_begin_another_window_is_condemned() {
        for fenced in [false, true] {
            assert_eq!(condemn_reason(CommitOutcome::Aborted, fenced), None);
        }
        assert_eq!(
            condemn_reason(CommitOutcome::Unknown, true),
            Some("commit_fenced")
        );
        assert_eq!(
            condemn_reason(CommitOutcome::Unknown, false),
            Some("commit_indeterminate")
        );
        // The same dead producer, split by what killed it: an epoch lost
        // to a newer owner is coordination working, an abort nobody
        // fenced failing is the broker unreachable — the operator's first
        // question, answered from the series alone.
        assert_eq!(
            condemn_reason(CommitOutcome::AbortedProducerDead, true),
            Some("abort_fenced")
        );
        assert_eq!(
            condemn_reason(CommitOutcome::AbortedProducerDead, false),
            Some("abort_failed")
        );
    }

    /// A condemn reason absent from the preregistration list first
    /// appears as a new series mid-incident instead of rising from zero.
    #[test]
    fn every_condemn_reason_is_preregistered() {
        for outcome in [
            CommitOutcome::Aborted,
            CommitOutcome::AbortedProducerDead,
            CommitOutcome::Unknown,
        ] {
            for fenced in [false, true] {
                if let Some(reason) = condemn_reason(outcome, fenced) {
                    assert!(
                        CONDEMN_REASONS.contains(&reason),
                        "condemn_reason produced {reason:?}, missing from CONDEMN_REASONS"
                    );
                }
            }
        }
        for direct in ["commit_task_lost", "committer_unwound"] {
            assert!(
                CONDEMN_REASONS.contains(&direct),
                "direct condemn call site uses {direct:?}, missing from CONDEMN_REASONS"
            );
        }
    }

    #[test]
    fn a_fence_only_settles_the_records_when_the_window_also_aborted() {
        for (outcome, fenced, expected) in [
            (CommitOutcome::Aborted, true, WindowVerdict::Fenced),
            (
                CommitOutcome::AbortedProducerDead,
                true,
                WindowVerdict::Fenced,
            ),
            (CommitOutcome::Aborted, false, WindowVerdict::Aborted),
            (
                CommitOutcome::AbortedProducerDead,
                false,
                WindowVerdict::Aborted,
            ),
            (CommitOutcome::Unknown, true, WindowVerdict::FencedUncertain),
            (CommitOutcome::Unknown, false, WindowVerdict::Indeterminate),
        ] {
            assert_eq!(
                window_verdict(outcome, fenced),
                expected,
                "outcome={outcome:?} fenced={fenced}"
            );
        }
    }
}
