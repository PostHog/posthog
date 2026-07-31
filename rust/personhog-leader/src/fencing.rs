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

use std::sync::Arc;
use std::time::{Duration, Instant};
use std::{fmt, mem};

use common_kafka::config::KafkaConfig;
use common_kafka::transaction::TransactionalProducer;
use dashmap::DashMap;
use metrics::{counter, histogram};
use prost::Message as ProtoMessage;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{FutureRecord, Producer};
use tokio::sync::{oneshot, Mutex, Notify};
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
}

impl fmt::Display for FencedProduceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FencedProduceError::NotAcquired => write!(f, "partition fence not acquired"),
            FencedProduceError::Fenced => {
                write!(f, "producer fenced by a newer owner of the partition")
            }
            FencedProduceError::Failed(e) => write!(f, "fenced produce failed: {e}"),
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
    gate: Mutex<Gate>,
    /// Signalled when `in_flight` reaches zero.
    sends_settled: Notify,
    /// Signalled when a committing window finishes, letting blocked
    /// writers open the next one.
    window_closed: Notify,
    commit_timeout: Duration,
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
        let fence = self
            .partitions
            .get(&partition)
            .map(|f| Arc::clone(&f))
            .ok_or(FencedProduceError::NotAcquired)?;

        // Join the open window, or open one. A window mid-commit admits
        // no joiners; wait for it to close and retry.
        let opened = loop {
            // Register interest before inspecting the gate: a close that
            // fires between the check and the await must not be lost.
            let closed = fence.window_closed.notified();
            tokio::pin!(closed);
            closed.as_mut().enable();
            {
                let mut gate = fence.gate.lock().await;
                if gate.open {
                    gate.in_flight += 1;
                    break false;
                }
                if !gate.committing && gate.in_flight == 0 && gate.waiters.is_empty() {
                    // Idle: open a new window. BeginTxn is a local
                    // librdkafka state transition, safe inline.
                    fence
                        .producer
                        .inner()
                        .begin_transaction()
                        .map_err(|e| self.classify(&fence, partition, e))?;
                    gate.open = true;
                    gate.in_flight = 1;
                    gate.poisoned = false;
                    break true;
                }
            }
            closed.await;
        };

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
                    histogram!("personhog_leader_kafka_produce_duration_ms")
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
            {
                let mut gate = fence.gate.lock().await;
                gate.in_flight -= 1;
                gate.poisoned = true;
                if gate.in_flight == 0 {
                    fence.sends_settled.notify_waiters();
                }
            }
            return Err(match send_err {
                Some(e) => self.classify(&fence, partition, e),
                None => FencedProduceError::Failed("send cancelled (timeout)".to_string()),
            });
        }
        let offset = offset.expect("checked above");

        let (tx, rx) = oneshot::channel();
        {
            let mut gate = fence.gate.lock().await;
            gate.in_flight -= 1;
            gate.waiters.push(tx);
            if gate.in_flight == 0 {
                fence.sends_settled.notify_waiters();
            }
        }

        // The record exists but is invisible until the window commits;
        // the ack must wait for the commit outcome.
        match rx.await {
            Ok(Ok(())) => {
                counter!("personhog_leader_kafka_produces_total").increment(1);
                Ok(offset)
            }
            Ok(Err(e)) => Err(e),
            Err(_) => Err(FencedProduceError::Failed(
                "commit task dropped".to_string(),
            )),
        }
    }

    /// Classify a transaction error, removing the fence on a broker
    /// fence rejection so subsequent writes fail fast as stale. The
    /// fenced signal often hides behind a local symptom — librdkafka
    /// purges queued messages once the producer turns fatal — so the
    /// producer's fatal error is consulted alongside the surface error.
    fn classify(
        &self,
        fence: &PartitionFence,
        partition: u32,
        e: KafkaError,
    ) -> FencedProduceError {
        if is_fenced(&e) || producer_fenced(fence.producer.inner()) {
            counter!("personhog_leader_produce_fenced_total").increment(1);
            error!(
                partition,
                error = %e,
                "changelog producer fenced by a newer owner — this pod's claim is stale"
            );
            self.partitions.remove(&partition);
            FencedProduceError::Fenced
        } else {
            FencedProduceError::Failed(e.to_string())
        }
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
fn producer_fenced<C: rdkafka::client::ClientContext>(
    producer: &rdkafka::producer::FutureProducer<C>,
) -> bool {
    use rdkafka::producer::Producer;
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
        let mut gate = fence.gate.lock().await;
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
            let gate = fence.gate.lock().await;
            if gate.in_flight == 0 {
                break;
            }
        }
        settled.await;
    }

    let (waiters, poisoned) = {
        let mut gate = fence.gate.lock().await;
        (mem::take(&mut gate.waiters), gate.poisoned)
    };
    histogram!("personhog_leader_fence_window_writes").record(waiters.len() as f64);

    // Commit and abort block up to the transaction timeout; keep them
    // off the runtime threads.
    let producer = fence.producer.inner().clone();
    let timeout = fence.commit_timeout;
    let commit_start = Instant::now();
    let result = spawn_blocking(move || {
        if poisoned {
            // The abort's own failure is secondary — the window already
            // failed; a producer that cannot abort surfaces on the next
            // begin.
            if let Err(e) = producer.abort_transaction(timeout) {
                warn!(error = %e, "abort of a poisoned window failed");
            }
            Err((
                KafkaError::Canceled,
                "aborted: a send in this window failed",
            ))
        } else {
            producer
                .commit_transaction(timeout)
                .map_err(|e| (e, "commit failed"))
        }
    })
    .await;

    let outcome: Result<(), FencedProduceError> = match result {
        Ok(Ok(())) => {
            histogram!("personhog_leader_fence_commit_ms")
                .record(commit_start.elapsed().as_secs_f64() * 1000.0);
            Ok(())
        }
        Ok(Err((e, context))) => {
            counter!("personhog_leader_fence_aborts_total").increment(1);
            if is_fenced(&e) || producer_fenced(fence.producer.inner()) {
                counter!("personhog_leader_produce_fenced_total").increment(1);
                error!(
                    partition,
                    topic,
                    error = %e,
                    "changelog window fenced by a newer owner — this pod's claim is stale"
                );
                Err(FencedProduceError::Fenced)
            } else {
                error!(partition, topic, error = %e, context, "changelog window failed");
                Err(FencedProduceError::Failed(format!("{context}: {e}")))
            }
        }
        Err(join) => Err(FencedProduceError::Failed(format!("commit join: {join}"))),
    };

    for waiter in waiters {
        // A dropped receiver means the writer's request already ended;
        // nothing to deliver.
        waiter.send(clone_outcome(&outcome)).ok();
    }
    fence.gate.lock().await.committing = false;
    fence.window_closed.notify_waiters();
}

/// `FencedProduceError` holds a String and cannot derive Clone cheaply
/// through the oneshot fan-out; rebuild the outcome per waiter.
fn clone_outcome(outcome: &Result<(), FencedProduceError>) -> Result<(), FencedProduceError> {
    match outcome {
        Ok(()) => Ok(()),
        Err(FencedProduceError::NotAcquired) => Err(FencedProduceError::NotAcquired),
        Err(FencedProduceError::Fenced) => Err(FencedProduceError::Fenced),
        Err(FencedProduceError::Failed(e)) => Err(FencedProduceError::Failed(e.clone())),
    }
}
