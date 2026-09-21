//! The worker batcher: the dispatch orchestration behind one boundary.
//!
//! The consumer loop submits one [`Accumulator`] per poll, in poll order, and
//! receives one [`GroupCompletion`] per group back. Everything in between is
//! an implementation detail of this module: assignment, the scatter over the
//! worker streams with its send resolution, and the parked-retry pump. No
//! batch identity crosses the boundary: the batcher creates an internal batch
//! id per accumulator for the dispatcher and the wire request, and the
//! consumer correlates completions by partition and offset.
//!
//! Fatal orchestration failures (a stalled key table, a batch with no usable
//! workers) are reported on an error channel; the consumer turns them into a
//! process failure, so the failure decision stays in the consumer loop.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{AssignmentEpoch, GroupCompletion, Offset, Partition};
use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{error, info};

use crate::dispatcher::{Dispatcher, KeyOffset, SubBatch, Submission};
use crate::grpc_transport::{GrpcTransport, PendingWorkerStreamSend};
use crate::order_sentinel::KeyOrderSentinel;
use crate::transport::SendError;
use crate::types::Accumulator;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

/// The batcher's output channels, held by the consumer loop.
pub struct BatcherOutputs {
    /// One event per group: its partition, assignment epoch, offsets, and
    /// accepted count.
    pub completions: mpsc::UnboundedReceiver<GroupCompletion>,
    /// Fatal orchestration failures. The consumer fails the process on the
    /// first message.
    pub errors: mpsc::UnboundedReceiver<String>,
}

/// A slice of a batch whose send order is already established on its worker's
/// stream (`GrpcTransport::begin_send`), plus the metadata the resolve
/// protocol and the completion events need.
struct PendingSubBatch {
    worker: WorkerId,
    routing_keys: Vec<String>,
    key_offsets: Vec<KeyOffset>,
    message_count: usize,
    /// The accumulator groups this sub-batch carries, kept aside so the
    /// resolved send can be broken back into per-group completions.
    groups: Vec<CompletionGroup>,
    /// The runs' epoch, stamped on their completions.
    assignment_epoch: u64,
    pending: PendingWorkerStreamSend,
}

/// One accumulator group's share of a sub-batch: its partition and offsets.
struct CompletionGroup {
    partition: Partition,
    offsets: Vec<Offset>,
}

struct BatcherInner {
    dispatcher: Arc<Dispatcher>,
    transport: Arc<GrpcTransport>,
    /// Stamped on each submitted batch's completions; bumped on partition
    /// assignment by the consumer's rebalance context.
    assignment_epoch: AssignmentEpoch,
    accepted_messages: AtomicU64,
    completions: mpsc::UnboundedSender<GroupCompletion>,
    errors: mpsc::UnboundedSender<String>,
}

impl BatcherInner {
    fn report_error(&self, message: String) {
        error!(error = %message, "Batcher failure");
        if self.errors.send(message).is_err() {
            error!("Batcher error channel closed; consumer is gone");
        }
    }
}

/// Emit one completion per group of a successfully resolved send. A send is
/// all-or-nothing, so `accepted` normally equals the sub-batch size and each
/// group completes with its own length; a worker that under-reports shorts
/// the tail groups, so the poll fails its accepted check and the process
/// exits and replays.
fn send_group_completions(
    completions: &mpsc::UnboundedSender<GroupCompletion>,
    groups: Vec<CompletionGroup>,
    assignment_epoch: u64,
    accepted: u32,
) {
    let mut remaining = accepted;
    for group in groups {
        let group_accepted = remaining.min(group.offsets.len() as u32);
        remaining -= group_accepted;
        counter!("ingestion_consumer_group_completions_total").increment(1);
        counter!("ingestion_consumer_group_completion_accepted_messages_total")
            .increment(group_accepted as u64);
        let _ = completions.send(GroupCompletion {
            partition: group.partition,
            assignment_epoch,
            offsets: group.offsets,
            accepted: group_accepted,
        });
    }
}

/// Owns the dispatch orchestration: the dispatcher, the scatter tasks, and
/// the parked-retry pump. Holds shared handles to the transport; the
/// transport, router, and registry keep their construction and ownership in
/// `main.rs`.
pub struct Batcher {
    inner: Arc<BatcherInner>,
    parked_retry_pump: JoinHandle<()>,
}

impl Batcher {
    pub fn new(
        dispatcher: Arc<Dispatcher>,
        transport: Arc<GrpcTransport>,
        stall_timeout: Duration,
        parked_retry_interval: Duration,
    ) -> (Self, BatcherOutputs) {
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let assignment_epoch = transport.assignment_epoch();
        let inner = Arc::new(BatcherInner {
            dispatcher,
            transport,
            assignment_epoch,
            accepted_messages: AtomicU64::new(0),
            completions: completions_tx,
            errors: errors_tx,
        });
        let parked_retry_pump = tokio::spawn(run_parked_retry_pump(
            Arc::clone(&inner),
            parked_retry_interval,
            stall_timeout,
        ));
        (
            Self {
                inner,
                parked_retry_pump,
            },
            BatcherOutputs {
                completions: completions_rx,
                errors: errors_rx,
            },
        )
    }

    /// The dispatcher's per-key order sentinel, shared with the consumer's
    /// rdkafka context so rebalances can reset its baselines.
    pub fn key_order_sentinel(&self) -> Arc<KeyOrderSentinel> {
        self.inner.dispatcher.key_order_sentinel()
    }

    /// The dispatcher, for the consumer's revocation hook.
    pub fn dispatcher(&self) -> Arc<Dispatcher> {
        Arc::clone(&self.inner.dispatcher)
    }

    /// Submit one poll's demuxed groups. Call on the consumer loop, in poll
    /// order. Returns the assignment epoch stamped on the poll's completions,
    /// so the consumer can correlate them without a second epoch read.
    ///
    /// Assignment happens here, synchronously, so it happens in true batch
    /// order: on a spawned task, batch N+1's assign could beat batch N's to
    /// the key table and send a key's newer messages first — per-key send
    /// order must be fixed exactly once, in Kafka order, at assignment. Send
    /// order is also established here, under the dispatcher's lock:
    /// `begin_send` is synchronous, so a key's sub-batches enter its worker's
    /// stream in assignment order.
    pub fn submit(&self, accumulator: Accumulator) -> u64 {
        let assignment_epoch = self.inner.assignment_epoch.current();
        let batch_id = make_batch_id();
        let assign_start = Instant::now();
        let groups = accumulator.into_groups();
        let Submission { pending, retained } = self.inner.dispatcher.assign_and_send(
            &batch_id,
            assignment_epoch,
            groups,
            |sub_batch| begin_send(&self.inner.transport, &batch_id, sub_batch, false),
        );
        // Assignment serializes on the consumer loop (it does not overlap
        // batch collection) — watch this stays a small fraction of the batch
        // collection interval.
        histogram!("ingestion_consumer_assign_duration_seconds")
            .record(assign_start.elapsed().as_secs_f64());

        drop(tokio::spawn(run_scatter(
            Arc::clone(&self.inner),
            batch_id,
            pending,
            retained,
        )));
        assignment_epoch
    }
}

impl Drop for Batcher {
    fn drop(&mut self) {
        self.parked_retry_pump.abort();
    }
}

/// Await a batch's pre-ordered sub-batch sends and feed passive health
/// signals. Reports a batch that had no usable workers, and records the
/// scatter duration on success.
async fn run_scatter(
    inner: Arc<BatcherInner>,
    batch_id: String,
    pending: Vec<PendingSubBatch>,
    retained: bool,
) {
    // Use the submission's synchronous assignment outcome. Mutable scheduler
    // state may have changed by the time this spawned task runs.
    if pending.is_empty() && !retained {
        counter!("ingestion_consumer_no_healthy_workers_total").increment(1);
        inner.report_error("No healthy workers available to route batch".to_string());
        return;
    }
    let start = Instant::now();
    match scatter(&inner, &batch_id, pending).await {
        Ok(_) => {
            histogram!("ingestion_consumer_batch_processing_duration_seconds")
                .record(start.elapsed().as_secs_f64());
            info!(batch_id = %batch_id, "Kafka batch processing completed");
        }
        Err(err) => inner.report_error(format!("awaiting sub-batches failed: {err:#}")),
    }
}

/// Await sub-batch sends in parallel and settle each in the dispatcher. A
/// successful send emits one completion per group it carried; a failed send
/// (the worker died mid-send, or its worker stream was fenced) requeues its
/// messages for the parked retry. Returns the number of messages accepted.
async fn scatter(
    inner: &Arc<BatcherInner>,
    batch_id: &str,
    pending: Vec<PendingSubBatch>,
) -> anyhow::Result<u32> {
    let mut handles = Vec::with_capacity(pending.len());
    for sub_batch in pending {
        handles.push(tokio::spawn(await_settled(
            Arc::clone(inner),
            batch_id.to_string(),
            sub_batch,
        )));
    }

    let mut accepted = 0u32;
    for handle in handles {
        accepted += handle.await?;
    }
    Ok(accepted)
}

/// Await one in-flight send, settle it in one seam call, and spawn an
/// awaiter for every follow-up send the settlement dispatched (a delivered
/// settlement releases the key's next run). Every begin_send gets exactly
/// one awaiter, so every dispatch settles exactly once.
async fn await_settled(
    inner: Arc<BatcherInner>,
    batch_id: String,
    sub_batch: PendingSubBatch,
) -> u32 {
    let PendingSubBatch {
        worker,
        routing_keys,
        key_offsets,
        message_count,
        groups,
        assignment_epoch,
        pending,
    } = sub_batch;

    match pending.wait().await {
        Ok(accepted) => {
            if accepted > 0 {
                inner
                    .accepted_messages
                    .fetch_add(accepted as u64, Ordering::Relaxed);
            }
            // Advance ACK high-water marks before the settle, which
            // may evict the keys' sentinel state.
            inner.dispatcher.on_sub_batch_acked(&key_offsets);
            let followups = settle_and_send(&inner, &worker, message_count, &routing_keys, None);
            inner.dispatcher.record_send_outcome(&worker, false);
            send_group_completions(&inner.completions, groups, assignment_epoch, accepted);
            spawn_followups(&inner, followups);
            accepted
        }
        Err(send_err) => {
            // One settlement call requeues the failed messages and
            // releases the keys together, so a newer send cannot
            // overtake them.
            // Backpressure (a busy worker) is transient, not a fault:
            // re-route the work but do not count it against the
            // worker's health, so passive health tracks real faults.
            let SendError {
                error,
                messages,
                fence_guard,
            } = send_err;
            let is_fault = !error.is_backpressure();
            let followups = settle_and_send(
                &inner,
                &worker,
                message_count,
                &routing_keys,
                Some((batch_id, messages)),
            );
            // Requeued: let the worker stream stop fencing new arrivals.
            drop(fence_guard);
            inner.dispatcher.record_send_outcome(&worker, is_fault);
            spawn_followups(&inner, followups);
            0
        }
    }
}

/// Settle one send and begin the settlement's follow-up sends under the
/// dispatcher lock. Follow-up sends belong to no poll, so they go on the
/// wire under a fresh batch id, minted for correlation and logs.
fn settle_and_send(
    inner: &Arc<BatcherInner>,
    worker: &WorkerId,
    message_count: usize,
    routing_keys: &[String],
    failed: Option<(String, Vec<SerializedKafkaMessage>)>,
) -> (String, Vec<PendingSubBatch>) {
    let settle_id = make_batch_id();
    let followups = inner.dispatcher.settle_and_send(
        worker,
        message_count,
        routing_keys,
        failed,
        |sub_batch| begin_send(&inner.transport, &settle_id, sub_batch, false),
    );
    (settle_id, followups)
}

/// Spawn one detached awaiter per follow-up send.
fn spawn_followups(
    inner: &Arc<BatcherInner>,
    (settle_id, followups): (String, Vec<PendingSubBatch>),
) {
    for sub_batch in followups {
        drop(tokio::spawn(await_settled(
            Arc::clone(inner),
            settle_id.clone(),
            sub_batch,
        )));
    }
}

/// The key table's retry driver: fire the parked-retry deadline on an
/// interval. Parked keys are the ones no settlement can release, so the
/// pump is their only retry path. Its stall watchdog: acceptance resets the
/// deadline, and pending work with zero acceptance for a full window fails
/// the process, so a wedged key table restarts loudly instead of growing lag
/// silently.
async fn run_parked_retry_pump(
    inner: Arc<BatcherInner>,
    interval: Duration,
    stall_timeout: Duration,
) {
    let mut ticker = tokio::time::interval(interval);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut seen_accepted = 0u64;
    let mut stall_deadline = Instant::now() + stall_timeout;
    loop {
        ticker.tick().await;

        // Check the stall before this tick's retries. Acceptance or full
        // idleness resets the clock. Once the deadline expires, stop starting
        // parked retries so overlapping failures must converge to zero
        // outstanding; then report the stall. An already in-flight send may
        // still be healthy but slow, so let it settle: acceptance resets the
        // deadline, while failure leaves queued work with nothing outstanding
        // and trips the watchdog on the next tick.
        let accepted = inner.accepted_messages.load(Ordering::Relaxed);
        let (queued, outstanding) = inner.dispatcher.key_work();
        let now = Instant::now();
        if accepted != seen_accepted || (queued == 0 && outstanding == 0) {
            seen_accepted = accepted;
            stall_deadline = now + stall_timeout;
        } else if now >= stall_deadline {
            if queued > 0 && outstanding == 0 {
                inner.report_error(
                    "key-table work made no progress within the stall timeout".to_string(),
                );
                return;
            }
            continue;
        }

        // A retried send may replay a failed run, so it goes on the wire
        // with the replay flag.
        let settle_id = make_batch_id();
        let pending = inner.dispatcher.parked_retry_and_send(|sub_batch| {
            begin_send(&inner.transport, &settle_id, sub_batch, true)
        });
        for sub_batch in pending {
            drop(tokio::spawn(await_settled(
                Arc::clone(&inner),
                settle_id.clone(),
                sub_batch,
            )));
        }
    }
}

/// Establish a sub-batch's send order. Synchronous and non-blocking on
/// purpose: called under the dispatcher's lock, where send order is decided,
/// so a key's sub-batches enter its worker's stream in exactly that order.
fn begin_send(
    transport: &GrpcTransport,
    batch_id: &str,
    sub_batch: SubBatch,
    replay: bool,
) -> PendingSubBatch {
    let SubBatch {
        worker,
        messages,
        routing_keys,
        key_offsets,
        assignment_epoch,
    } = sub_batch;
    let groups = completion_groups(&messages);
    let message_count = messages.len();
    let pending = transport.begin_send(&worker, batch_id, messages, replay);
    PendingSubBatch {
        worker,
        routing_keys,
        key_offsets,
        message_count,
        groups,
        assignment_epoch,
        pending,
    }
}

/// Reconstruct the accumulator's groups from a sub-batch's messages: one
/// group per partition and key, a keyless message on its own. The dispatcher
/// may merge one key's groups from two partitions into one sub-batch (the key
/// table is partition-blind); a completion names one partition, so the merge
/// splits back here.
fn completion_groups(messages: &[SerializedKafkaMessage]) -> Vec<CompletionGroup> {
    let mut groups: Vec<CompletionGroup> = Vec::new();
    let mut index_by_key: HashMap<(Partition, &str), usize> = HashMap::new();
    for message in messages {
        let partition = Partition(message.partition);
        let offset = Offset(message.offset);
        match message.key.as_deref() {
            None => groups.push(CompletionGroup {
                partition,
                offsets: vec![offset],
            }),
            Some(key) => match index_by_key.get(&(partition, key)) {
                Some(&index) => groups[index].offsets.push(offset),
                None => {
                    index_by_key.insert((partition, key), groups.len());
                    groups.push(CompletionGroup {
                        partition,
                        offsets: vec![offset],
                    });
                }
            },
        }
    }
    groups
}

pub(crate) fn make_batch_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn message(partition: i32, offset: i64, key: Option<&str>) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition,
            offset,
            timestamp: 0,
            key: key.map(|k| k.to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn shapes(groups: &[CompletionGroup]) -> Vec<(i32, Vec<i64>)> {
        groups
            .iter()
            .map(|g| (g.partition.0, g.offsets.iter().map(|o| o.0).collect()))
            .collect()
    }

    #[test]
    fn completion_groups_split_per_partition_and_key() {
        // The dispatcher merges one key across partitions into one sub-batch;
        // the completion groups must split it back per partition.
        let groups = completion_groups(&[
            message(0, 1, Some("a")),
            message(0, 2, Some("b")),
            message(3, 9, Some("a")),
            message(0, 4, Some("a")),
        ]);
        assert_eq!(
            shapes(&groups),
            vec![(0, vec![1, 4]), (0, vec![2]), (3, vec![9])]
        );
    }

    #[test]
    fn completion_groups_keep_keyless_messages_alone() {
        let groups = completion_groups(&[
            message(7, 42, None),
            message(7, 43, None),
            message(7, 44, Some("a")),
        ]);
        assert_eq!(
            shapes(&groups),
            vec![(7, vec![42]), (7, vec![43]), (7, vec![44])]
        );
    }

    #[tokio::test]
    async fn send_group_completions_apportions_an_under_reported_accepted_count() {
        let (completions_tx, mut completions_rx) = mpsc::unbounded_channel();

        let groups = vec![
            CompletionGroup {
                partition: Partition(0),
                offsets: vec![Offset(1), Offset(2)],
            },
            CompletionGroup {
                partition: Partition(0),
                offsets: vec![Offset(3), Offset(4)],
            },
        ];
        send_group_completions(&completions_tx, groups, 5, 3);

        let first = completions_rx.recv().await.expect("first completion");
        assert_eq!(first.assignment_epoch, 5);
        assert_eq!(first.offsets, vec![Offset(1), Offset(2)]);
        assert_eq!(first.accepted, 2);
        // The worker under-reported by one, so the tail group is shorted and
        // the consumer's accepted check fails the poll.
        let second = completions_rx.recv().await.expect("second completion");
        assert_eq!(second.offsets, vec![Offset(3), Offset(4)]);
        assert_eq!(second.accepted, 1);
    }
}
