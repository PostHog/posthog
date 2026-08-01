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
//! first write, admits concurrent writes for a short interval (their
//! records ride librdkafka's normal batching), then commits once and
//! resolves every waiter. Under light load a window holds one write and
//! costs one commit; under load the commit amortizes across the window.
//!
//! The price of sharing a transaction is shared failure: an aborted
//! window fails all of its writes together. Readers never observe
//! aborted records (consumers run `read_committed`), so the coupling is
//! visible only as grouped retryable errors.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::{fmt, mem};

use common_kafka::config::KafkaConfig;
use common_kafka::transaction::TransactionalProducer;
use dashmap::DashMap;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::client::ClientContext;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use tokio::sync::{oneshot, Notify};
use tokio::task::spawn_blocking;
use tokio::time::sleep;
use tracing::{error, warn};

use personhog_proto::personhog::types::v1::Person;

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
    /// the partition's transactional id. This pod's claim is stale.
    Fenced,
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
}

struct PartitionFence {
    producer: TransactionalProducer,
    /// A std mutex, deliberately: every critical section is a handful of
    /// field updates with no await inside, and `WindowSlot`'s `Drop` must
    /// be able to release its seat synchronously.
    gate: Mutex<Gate>,
    /// Signalled when `in_flight` reaches zero.
    sends_settled: Notify,
    /// Signalled when a committing window finishes, letting blocked
    /// writers open the next one.
    window_closed: Notify,
    commit_timeout: Duration,
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
    armed: bool,
}

impl FenceGuard {
    pub fn new(fenced: Arc<FencedChangelogProducers>, partition: u32) -> Self {
        Self {
            fenced,
            partition,
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
                "releasing a fence taken for a warm that did not finish"
            );
            self.fenced.release(self.partition);
        }
    }
}

/// Per-partition fenced producers for the changelog. Constructed once
/// and shared; partitions are acquired at warm completion and released
/// with ownership.
pub struct FencedChangelogProducers {
    kafka: KafkaConfig,
    topic: String,
    init_timeout: Duration,
    commit_timeout: Duration,
    /// How long an open window admits joiners before committing.
    window: Duration,
    partitions: DashMap<u32, Arc<PartitionFence>>,
}

impl FencedChangelogProducers {
    pub fn new(
        kafka: KafkaConfig,
        topic: String,
        init_timeout: Duration,
        commit_timeout: Duration,
        window: Duration,
    ) -> Self {
        Self {
            kafka,
            topic,
            init_timeout,
            commit_timeout,
            window,
            partitions: DashMap::new(),
        }
    }

    /// Take the partition's fence: create the transactional producer and
    /// initialize transactions, which fences every previous owner of the
    /// partition's transactional id. Runs on the blocking pool — init is
    /// a synchronous broker round trip.
    pub async fn acquire(&self, partition: u32) -> Result<(), String> {
        let kafka = self.kafka.clone();
        let tid = transactional_id(&self.topic, partition);
        let timeout = self.init_timeout;
        let start = Instant::now();
        let producer =
            spawn_blocking(move || TransactionalProducer::from_config(&kafka, &tid, timeout))
                .await
                .map_err(|e| format!("fence init join: {e}"))?
                .map_err(|e| {
                    counter!("personhog_leader_fence_init_total", "outcome" => "error")
                        .increment(1);
                    format!("fence init: {e}")
                })?;
        counter!("personhog_leader_fence_init_total", "outcome" => "ok").increment(1);
        histogram!("personhog_leader_fence_init_ms").record(start.elapsed().as_secs_f64() * 1000.0);
        self.partitions.insert(
            partition,
            Arc::new(PartitionFence {
                producer,
                gate: Mutex::new(Gate {
                    open: false,
                    in_flight: 0,
                    poisoned: false,
                    committing: false,
                    waiters: Vec::new(),
                }),
                sends_settled: Notify::new(),
                window_closed: Notify::new(),
                commit_timeout: self.commit_timeout,
            }),
        );
        Ok(())
    }

    /// Drop the partition's fence with ownership. The broker-side epoch
    /// survives; only a future owner's init advances it.
    pub fn release(&self, partition: u32) {
        self.partitions.remove(&partition);
    }

    /// Produce one changelog record inside the partition's current
    /// transaction window, returning its offset once the window commits.
    pub async fn produce(
        &self,
        partition: u32,
        person: &Person,
    ) -> Result<i64, FencedProduceError> {
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
            // Register interest before inspecting the gate: a close that
            // fires between the check and the await must not be lost.
            let closed = fence.window_closed.notified();
            tokio::pin!(closed);
            closed.as_mut().enable();
            {
                let mut gate = fence.gate.lock().unwrap();
                if gate.open {
                    gate.in_flight += 1;
                    break false;
                }
                if !gate.committing && gate.in_flight == 0 && gate.waiters.is_empty() {
                    // Idle: open a new window. BeginTxn is a local
                    // librdkafka state transition, safe inline.
                    fence.producer.inner().begin_transaction().map_err(|e| {
                        counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                        self.classify(&fence, partition, e)
                    })?;
                    gate.open = true;
                    gate.in_flight = 1;
                    gate.poisoned = false;
                    break true;
                }
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

        if opened {
            let fence_for_commit = Arc::clone(&fence);
            let window = self.window;
            let topic = self.topic.clone();
            let part = partition;
            tokio::spawn(async move {
                commit_window_after(fence_for_commit, window, topic, part).await;
            });
        }

        // Send within the open window; the record rides librdkafka's
        // ordinary batching alongside its window-mates.
        let key = changelog_message_key(person.team_id, person.id);
        let payload = person.encode_to_vec();
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
                Ok(Err((e, _))) => {
                    error!(partition, error = %e, "fenced send delivery failed");
                    Err(Some(e))
                }
                Err(_cancelled) => {
                    error!(partition, "fenced send cancelled");
                    Err(None)
                }
            },
            Err((e, _)) => {
                error!(partition, error = %e, "fenced send enqueue failed");
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
                if matches!(e, FencedProduceError::Fenced) {
                    self.forget_fence(partition, &fence);
                }
                Err(e)
            }
            Err(_) => {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                Err(FencedProduceError::Failed(
                    "commit task dropped".to_string(),
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
        self.partitions
            .remove_if(&partition, |_, installed| Arc::ptr_eq(installed, fence));
    }
}

/// How many times a retriable abort is re-attempted before the producer
/// is declared unusable.
const ABORT_RETRIES: usize = 3;

/// How many times a retriable commit is re-attempted before its outcome
/// is declared unknown.
const COMMIT_RETRIES: usize = 3;

/// What is known about a window's records after a failed commit.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CommitOutcome {
    /// The transaction is definitely aborted; nothing became visible.
    Aborted,
    /// Whether the records committed is not known.
    Unknown,
}

/// Transaction errors librdkafka documents as safe to re-attempt.
fn retriable_txn_error(code: RDKafkaErrorCode) -> bool {
    matches!(
        code,
        RDKafkaErrorCode::OperationTimedOut
            | RDKafkaErrorCode::RequestTimedOut
            | RDKafkaErrorCode::NotCoordinator
            | RDKafkaErrorCode::CoordinatorNotAvailable
            | RDKafkaErrorCode::CoordinatorLoadInProgress
    )
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

/// Close the window after its admission interval: stop admitting, wait
/// for in-flight sends to settle, then commit (or abort a poisoned
/// window) and resolve every waiter with the shared outcome.
async fn commit_window_after(
    fence: Arc<PartitionFence>,
    window: Duration,
    topic: String,
    partition: u32,
) {
    sleep(window).await;

    // Stop admitting joiners, then wait for outstanding sends. The
    // committing flag holds until the commit finishes so no writer can
    // begin the next transaction while this one is still resolving.
    {
        let mut gate = fence.gate.lock().unwrap();
        gate.open = false;
        gate.committing = true;
    }
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
    let result = spawn_blocking(move || {
        if poisoned {
            // Retry a retriable abort: leaving the producer in its
            // abortable state would fail every later `begin_transaction`
            // with an error no path re-acquires from, stranding the
            // partition until the next handoff.
            let mut abort = producer.abort_transaction(timeout);
            for _ in 0..ABORT_RETRIES {
                match &abort {
                    Err(e) if e.rdkafka_error_code().is_some_and(retriable_txn_error) => {
                        warn!(error = %e, "abort of a poisoned window failed; retrying");
                        abort = producer.abort_transaction(timeout);
                    }
                    _ => break,
                }
            }
            if let Err(e) = &abort {
                counter!("personhog_leader_fence_abort_exhausted_total").increment(1);
                error!(error = %e, "abort of a poisoned window failed; producer left unusable");
            }
            Err((KafkaError::Canceled, CommitOutcome::Aborted))
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
                    if let Err(abort_err) = producer.abort_transaction(timeout) {
                        // The abort itself is now in doubt, so the
                        // records are too.
                        return Err((abort_err, CommitOutcome::Unknown));
                    }
                    Err((KafkaError::Transaction(e), CommitOutcome::Aborted))
                }
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
            if is_fenced(&e) || producer_fenced(fence.producer.inner()) {
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
            } else if outcome == CommitOutcome::Aborted {
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
        // transaction's fate.
        Err(join) => Err(FencedProduceError::Indeterminate(format!(
            "commit join: {join}"
        ))),
    };

    for waiter in waiters {
        // A dropped receiver means the writer's request already ended;
        // nothing to deliver.
        waiter.send(clone_outcome(&outcome)).ok();
    }
    fence.gate.lock().unwrap().committing = false;
    fence.window_closed.notify_waiters();
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
    counter!("personhog_leader_fence_slots_abandoned_total").increment(0);
    counter!("personhog_leader_fence_abandoned_total").increment(0);
    counter!("personhog_leader_fence_abort_exhausted_total").increment(0);
    counter!("personhog_leader_fence_commit_retries_total").increment(0);
    counter!("personhog_leader_fenced_partition_drops_total").increment(0);
    counter!("personhog_leader_kafka_produce_errors_total").increment(0);
    for partition in 0..partitions {
        let p = partition.to_string();
        counter!("personhog_leader_fence_aborts_total", "partition" => p.clone()).increment(0);
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
        Err(FencedProduceError::Failed(e)) => Err(FencedProduceError::Failed(e.clone())),
        Err(FencedProduceError::Indeterminate(e)) => {
            Err(FencedProduceError::Indeterminate(e.clone()))
        }
    }
}
