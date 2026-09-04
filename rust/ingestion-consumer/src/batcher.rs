//! The worker batcher: the dispatch orchestration behind one boundary.
//!
//! The consumer loop submits one [`Accumulator`] per poll, in poll order, and
//! receives one [`GroupCompletion`] per group back. Everything in between is
//! an implementation detail of this module: assignment, the scatter over the
//! worker streams with its send resolution, and the serialized oldest-first
//! deferred flush. No batch identity crosses the boundary: the batcher
//! creates an internal batch id per accumulator for the dispatcher and the
//! wire request, and the consumer correlates completions by partition and
//! offset.
//!
//! Fatal orchestration failures (a wedged deferred flush, shutdown while
//! deferred work is unroutable, a batch with no usable workers) are reported
//! on an error channel; the consumer turns them into a process failure, so
//! the failure decision stays in the consumer loop.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{AssignmentEpoch, GroupCompletion, Offset, Partition};
use lifecycle::Handle;
use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{error, info};

use crate::dispatcher::{Dispatcher, KeyOffset, SubBatch};
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
    pending: PendingWorkerStreamSend,
}

/// One accumulator group's share of a sub-batch: its partition and offsets.
struct CompletionGroup {
    partition: Partition,
    offsets: Vec<Offset>,
}

/// One submitted batch in the flush driver's queue: the driver awaits the
/// batch's scatter, then flushes its deferred groups, oldest batch first.
struct FlushTicket {
    batch_id: String,
    assignment_epoch: u64,
    scatter: JoinHandle<()>,
}

struct BatcherInner {
    dispatcher: Arc<Dispatcher>,
    transport: Arc<GrpcTransport>,
    /// Stamped on each submitted batch's completions; bumped on partition
    /// assignment by the consumer's rebalance context.
    assignment_epoch: AssignmentEpoch,
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
/// the deferred-flush driver. Holds shared handles to the transport; the
/// transport, router, and registry keep their construction and ownership in
/// `main.rs`.
pub struct Batcher {
    inner: Arc<BatcherInner>,
    flush_queue: mpsc::UnboundedSender<FlushTicket>,
}

impl Batcher {
    pub fn new(
        dispatcher: Arc<Dispatcher>,
        transport: Arc<GrpcTransport>,
        handle: Handle,
        deferred_flush_timeout: Duration,
    ) -> (Self, BatcherOutputs) {
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let assignment_epoch = transport.assignment_epoch();
        let inner = Arc::new(BatcherInner {
            dispatcher,
            transport,
            assignment_epoch,
            completions: completions_tx,
            errors: errors_tx,
        });
        let (flush_queue, flush_rx) = mpsc::unbounded_channel();
        tokio::spawn(run_flush_driver(
            Arc::clone(&inner),
            flush_rx,
            handle,
            deferred_flush_timeout,
        ));
        (
            Self { inner, flush_queue },
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

    /// Submit one poll's demuxed groups. Call on the consumer loop, in poll
    /// order. Returns the assignment epoch stamped on the poll's completions,
    /// so the consumer can correlate them without a second epoch read.
    ///
    /// Registration and assignment both happen here, synchronously, so both
    /// happen in true batch order. Registration first, so the stash learns
    /// batch order before failed-send deferrals (which land in gather order)
    /// can reach it. Assignment too: on spawned tasks, batch N+1's assign
    /// could beat batch N's to the pin table and send a key's newer messages
    /// first — per-key send order must be fixed exactly once, in Kafka order,
    /// at assignment. Send order is also established here, under the
    /// dispatcher's lock: `begin_send` is synchronous, so a key's sub-batches
    /// enter its worker's stream in assignment order.
    pub fn submit(&self, accumulator: Accumulator) -> u64 {
        let assignment_epoch = self.inner.assignment_epoch.current();
        let batch_id = make_batch_id();
        self.inner.dispatcher.register_batch(&batch_id);
        let assign_start = Instant::now();
        let groups = accumulator.into_groups();
        let pending = self
            .inner
            .dispatcher
            .assign_and_send(&batch_id, groups, |sub_batch| {
                begin_send(&self.inner.transport, &batch_id, sub_batch, false)
            });
        // Assignment serializes on the consumer loop (it does not overlap
        // batch collection) — watch this stays a small fraction of the batch
        // collection interval.
        histogram!("ingestion_consumer_assign_duration_seconds")
            .record(assign_start.elapsed().as_secs_f64());

        let scatter = tokio::spawn(run_scatter(
            Arc::clone(&self.inner),
            batch_id.clone(),
            pending,
            assignment_epoch,
        ));
        let _ = self.flush_queue.send(FlushTicket {
            batch_id,
            assignment_epoch,
            scatter,
        });
        assignment_epoch
    }
}

/// Await a batch's pre-ordered sub-batch sends and feed passive health
/// signals. Reports a batch that had no usable workers, and records the
/// scatter duration on success.
async fn run_scatter(
    inner: Arc<BatcherInner>,
    batch_id: String,
    pending: Vec<PendingSubBatch>,
    assignment_epoch: u64,
) {
    // Nothing to send and no deferred groups means no usable workers.
    if pending.is_empty() && !inner.dispatcher.batch_has_flush_activity(&batch_id) {
        counter!("ingestion_consumer_no_healthy_workers_total").increment(1);
        inner.report_error("No healthy workers available to route batch".to_string());
        return;
    }
    let start = Instant::now();
    match scatter(&inner, &batch_id, pending, false, assignment_epoch).await {
        Ok(_) => {
            histogram!("ingestion_consumer_batch_processing_duration_seconds")
                .record(start.elapsed().as_secs_f64());
            info!(batch_id = %batch_id, "Kafka batch processing completed");
        }
        Err(err) => inner.report_error(format!("awaiting sub-batches failed: {err:#}")),
    }
}

/// Await sub-batch sends in parallel and resolve each in the dispatcher.
/// On a send failure (the worker died mid-send, or its worker stream was fenced),
/// the failed messages are deferred — before the resolve, so the pin
/// isn't evicted — to be replayed in order. A successful send emits one
/// completion per group it carried. Returns the number of messages accepted.
///
/// `from_flush` is true when awaiting sub-batches produced by the flush driver:
/// the resolve then clears one deferral per key, so a key stays deferring from
/// when it was first held until its flushed messages actually land (preventing
/// a newer batch from racing them).
async fn scatter(
    inner: &Arc<BatcherInner>,
    batch_id: &str,
    pending: Vec<PendingSubBatch>,
    from_flush: bool,
    assignment_epoch: u64,
) -> anyhow::Result<u32> {
    let mut handles = Vec::with_capacity(pending.len());
    for sub_batch in pending {
        let inner = Arc::clone(inner);
        let PendingSubBatch {
            worker,
            routing_keys,
            key_offsets,
            message_count,
            groups,
            pending,
        } = sub_batch;
        let bid = batch_id.to_string();

        handles.push(tokio::spawn(async move {
            match pending.wait().await {
                Ok(accepted) => {
                    // Advance ACK high-water marks before the resolve, which
                    // may evict the keys' sentinel state.
                    inner.dispatcher.on_sub_batch_acked(&key_offsets);
                    inner.dispatcher.on_sub_batch_resolved(
                        &worker,
                        message_count,
                        &routing_keys,
                        from_flush,
                        false,
                    );
                    inner.dispatcher.record_send_outcome(&worker, false);
                    send_group_completions(&inner.completions, groups, assignment_epoch, accepted);
                    accepted
                }
                Err(send_err) => {
                    // Re-defer the failed messages first, so the ref-count drop
                    // in `on_sub_batch_resolved` doesn't evict the pin while the
                    // key still has work to replay. On the flush path this pairs
                    // with the `clears_deferral` decrement in the resolve, so the
                    // outstanding count nets to unchanged (never dipping to zero)
                    // and the key keeps deferring across the retry.
                    // Backpressure (a busy worker) is transient, not a fault:
                    // re-route the work but do not count it against the
                    // worker's health, so passive health tracks real faults.
                    let SendError {
                        error,
                        messages,
                        fence_guard,
                    } = send_err;
                    let is_fault = !error.is_backpressure();
                    inner.dispatcher.defer_failed(&bid, messages);
                    // Stashed: let the worker stream stop fencing new arrivals.
                    drop(fence_guard);
                    inner.dispatcher.on_sub_batch_resolved(
                        &worker,
                        message_count,
                        &routing_keys,
                        from_flush,
                        true,
                    );
                    inner.dispatcher.record_send_outcome(&worker, is_fault);
                    0
                }
            }
        }));
    }

    let mut accepted = 0u32;
    for handle in handles {
        accepted += handle.await?;
    }
    Ok(accepted)
}

/// Flush each batch's deferred groups (keys whose worker was draining/dead)
/// in submit order, re-routing them to healthy workers. Serialized, oldest
/// batch first, after that batch's own scatter has resolved, which preserves
/// per-key order across batches. Retries with backoff while a flush can't
/// route (no healthy worker yet).
///
/// The stall deadline bounds **stalls, not total time**: it resets whenever
/// any of the batch's messages are accepted, so a large backlog draining
/// slowly under saturation keeps going, and the batcher only reports failure
/// — exiting the process and replaying — when flushing is truly wedged:
/// nothing landed for a full timeout (nothing routable, or a flapping worker
/// re-deferring every send). Failing the whole process for a mere slow drain
/// amplified today's saturation: each restart replayed all its partitions
/// into an already overloaded pool.
async fn run_flush_driver(
    inner: Arc<BatcherInner>,
    mut tickets: mpsc::UnboundedReceiver<FlushTicket>,
    handle: Handle,
    deferred_flush_timeout: Duration,
) {
    while let Some(ticket) = tickets.recv().await {
        if let Err(err) = ticket.scatter.await {
            inner.report_error(format!("batch processing task failed: {err:#}"));
            return;
        }
        if inner.dispatcher.has_unfinished_flush(&ticket.batch_id) {
            let mut stall_deadline = Instant::now() + deferred_flush_timeout;
            while inner.dispatcher.has_unfinished_flush(&ticket.batch_id) {
                if Instant::now() >= stall_deadline {
                    inner.report_error(
                        "deferred messages made no progress within the flush timeout".to_string(),
                    );
                    return;
                }
                // Serialized on this driver, oldest batch first, so
                // begin_send order preserves the flush's key order.
                let pending = inner
                    .dispatcher
                    .flush_deferred_and_send(&ticket.batch_id, |sub_batch| {
                        begin_send(&inner.transport, &ticket.batch_id, sub_batch, true)
                    });
                if pending.is_empty() {
                    // Nothing is routable right now (no healthy worker), so wait.
                    tokio::select! {
                        _ = handle.shutdown_recv() => {
                            inner.report_error(
                                "shutdown while flushing deferred messages".to_string(),
                            );
                            return;
                        }
                        _ = tokio::time::sleep(Duration::from_millis(200)) => {
                            handle.report_healthy();
                        }
                    }
                } else {
                    match scatter(
                        &inner,
                        &ticket.batch_id,
                        pending,
                        true,
                        ticket.assignment_epoch,
                    )
                    .await
                    {
                        Ok(accepted) if accepted > 0 => {
                            stall_deadline = Instant::now() + deferred_flush_timeout;
                        }
                        Ok(_) => {}
                        Err(err) => {
                            inner.report_error(format!(
                                "awaiting flushed sub-batches failed: {err:#}"
                            ));
                            return;
                        }
                    }
                }
            }
        }
        inner.dispatcher.release_batch(&ticket.batch_id);
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
        pending,
    }
}

/// Reconstruct the accumulator's groups from a sub-batch's messages: one
/// group per partition and key, a keyless message on its own. The dispatcher
/// may merge one key's groups from two partitions into one sub-batch (the pin
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
