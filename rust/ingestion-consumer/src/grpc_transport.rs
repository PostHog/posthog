//! Ordered streaming transport: one `WorkerIngest` stream per worker.
//!
//! Each worker stream owns a bidirectional gRPC stream to its worker and drains an
//! ordered queue: enqueue order is send order is the worker's feed order,
//! which is the per-key ordering guarantee concurrent HTTP requests cannot
//! give. `begin_send` enqueues synchronously — call it where send order is
//! decided (the consumer loop, right after assignment) — and hands back a
//! [`PendingWorkerStreamSend`] the caller awaits like an HTTP response.
//!
//! **Acks resolve in send order.** The worker acks sub-batches as they
//! complete, out of order. The worker stream records each ack in its ledger and
//! resolves only the consecutive acked prefix, so a send never succeeds
//! while an earlier one is still open: if that earlier one then fails, the
//! later one is still in the ledger and fences with it, instead of having
//! already released its keys and left the older messages to replay after
//! the newer ones.
//!
//! **A partial ack is not a failure.** It resolves in the same order as OK
//! and hands back the messages the worker's time budget cut off. An ack that
//! does not match its sub-batch fences the stream as a fault.
//!
//! **Failure fences the whole worker stream.** A nack, stream break, or connect
//! failure resolves every queued and un-acked item, in enqueue order, with a
//! [`SendError`] carrying the messages back. The batcher then requeues them
//! at the front of their keys' queues, and holds all newer work for those
//! keys until the failed messages are retried (oldest first) and acked. Each
//! fenced send also carries a [`FenceGuard`]; the worker stream keeps fencing
//! every new arrival until all guards are dropped, which closes the gap
//! between a send resolving and its caller requeuing, where a newer send for
//! a fenced key could otherwise be enqueued and ride the next stream first.
//! Nothing for a fenced key can leapfrog the failure, because everything for
//! it was either in the ledger, the queue, or fenced on arrival.
//!
//! The queue is unbounded, so enqueue stays synchronous and ordered. The
//! batcher bounds its depth: it keeps at most `INGESTION_WORKER_CONCURRENT_BATCHES`
//! requests in flight per worker and sends nothing more until one settles,
//! so every queued sub-batch goes on the wire at once.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::AssignmentEpoch;
use dashmap::DashMap;
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_client::WorkerIngestClient;
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    KafkaMessage, MessageRef, StreamHello, SubBatch, SubBatchAck, SubBatchStatus,
};
use metrics::{counter, gauge, histogram};
use prost::Message;
use tokio::sync::{mpsc, oneshot};
use tokio_stream::wrappers::UnboundedReceiverStream;
use tracing::{error, info, warn};

use crate::readiness;
use crate::transport::{
    split_by_size, FenceGuard, SendError, SendOutcome, TransportError, DEFAULT_MAX_BODY_BYTES,
};
use crate::types::SerializedKafkaMessage;

/// An acked chunk: the worker's answer, with the messages handed back so a
/// split send can reassemble the whole sub-batch on failure.
struct Accepted {
    accepted: u32,
    unfinished: Vec<MessageRef>,
    messages: Vec<SerializedKafkaMessage>,
}

type StreamReply = Result<Accepted, SendError>;

/// An enqueued sub-batch awaiting its acks; resolves like an HTTP send. A
/// sub-batch over the size cap rides the stream as several consecutive
/// chunks, one receiver each.
pub struct PendingWorkerStreamSend {
    chunks: Vec<oneshot::Receiver<StreamReply>>,
}

impl PendingWorkerStreamSend {
    /// All-or-nothing: `Ok` only when every
    /// chunk was acked, fully or partially; on any failure the `SendError`
    /// carries back the full original message set, in order, so the caller
    /// defers all of it. Already-accepted chunks then replay, which is
    /// ordinary at-least-once.
    pub async fn wait(self) -> Result<SendOutcome, SendError> {
        let mut accepted_total = 0u32;
        let mut messages: Vec<SerializedKafkaMessage> = Vec::new();
        // A partition revoked and regained inside one poll delivers an offset
        // twice, so unfinished references are counted, not deduplicated.
        let mut unfinished: HashMap<(i32, i64), usize> = HashMap::new();
        let mut failure: Option<SendError> = None;
        for rx in self.chunks {
            let reply = match rx.await {
                Ok(reply) => reply,
                // The worker stream task died without resolving its items — a
                // bug, not an operational failure. The messages are gone, so
                // the batch cannot reach its accepted total and the consumer
                // exits and replays.
                Err(_) => Err(SendError {
                    error: TransportError::WorkerStreamClosed,
                    messages: Vec::new(),
                    fence_guard: None,
                }),
            };
            match reply {
                Ok(accepted) => {
                    accepted_total += accepted.accepted;
                    for message in &accepted.unfinished {
                        *unfinished
                            .entry((message.partition, message.offset))
                            .or_default() += 1;
                    }
                    messages.extend(accepted.messages);
                }
                Err(mut err) => {
                    messages.extend(std::mem::take(&mut err.messages));
                    match &mut failure {
                        // Keep the first failure's error; fold later guards
                        // into it so the stream fences until all are requeued.
                        Some(first) => match (&mut first.fence_guard, err.fence_guard.take()) {
                            (Some(guard), Some(other)) => guard.merge(other),
                            (slot @ None, other) => *slot = other,
                            (Some(_), None) => {}
                        },
                        None => failure = Some(err),
                    }
                }
            }
        }
        match failure {
            None if unfinished.is_empty() => Ok(SendOutcome::Accepted(accepted_total)),
            // Callers match unfinished messages to what they sent in send
            // order, so walk the sent messages, not the worker's list.
            None => Ok(SendOutcome::Partial {
                accepted: accepted_total,
                unfinished: messages
                    .into_iter()
                    .filter(|message| {
                        match unfinished.get_mut(&(message.partition, message.offset)) {
                            Some(left) if *left > 0 => {
                                *left -= 1;
                                true
                            }
                            _ => false,
                        }
                    })
                    .collect(),
            }),
            Some(mut err) => {
                err.messages = messages;
                Err(err)
            }
        }
    }
}

/// How one send rides the stream.
#[derive(Clone, Copy, Debug, Default)]
pub struct SendOptions {
    pub replay: bool,
    /// The worker's soft time budget. `None` sends no budget.
    pub soft_budget: Option<Duration>,
}

struct WorkerStreamItem {
    batch_id: String,
    messages: Vec<SerializedKafkaMessage>,
    replay: bool,
    /// `0` means no budget.
    soft_budget_ms: u64,
    reply: oneshot::Sender<StreamReply>,
}

struct WorkerStream {
    tx: mpsc::UnboundedSender<WorkerStreamItem>,
}

/// How a worker's gRPC address is derived from its HTTP URL.
#[derive(Clone, Copy, Debug)]
pub enum GrpcPort {
    /// Every worker serves gRPC on this port — the production shape, where
    /// workers are distinct pod IPs sharing one containerPort.
    Fixed(u16),
    /// gRPC port = the worker URL's HTTP port plus this offset — for
    /// single-host setups (local dev, tests) where workers share an IP and
    /// differ only by port.
    OffsetFromHttp(u16),
}

/// Sends sub-batches over one ordered `WorkerIngest` stream per worker.
pub struct GrpcTransport {
    worker_streams: DashMap<String, Arc<WorkerStream>>,
    consumer_id: String,
    /// How each worker's stream address is derived from its HTTP URL.
    grpc_port: GrpcPort,
    /// Fence the worker stream when un-acked work sees no ack for this long.
    ack_timeout: Duration,
    /// Bumped on Kafka partition assignment; stamped on every sub-batch so
    /// the worker sentinel rebaselines across rebalances.
    assignment_epoch: AssignmentEpoch,
    /// Readiness probing stays HTTP: workers always serve `/_ready`.
    probe_client: reqwest::Client,
    /// Cap on one frame's estimated size. A sub-batch over it is sent as
    /// consecutive chunks (see `begin_send`), so no frame crosses the worker's
    /// message limit.
    max_body_bytes: usize,
}

impl GrpcTransport {
    pub fn new(grpc_port: GrpcPort, ack_timeout: Duration) -> Self {
        Self {
            worker_streams: DashMap::new(),
            consumer_id: make_consumer_id(),
            grpc_port,
            ack_timeout,
            max_body_bytes: DEFAULT_MAX_BODY_BYTES,
            // A fresh epoch for standalone construction; production wiring
            // injects the shared one via `set_assignment_epoch`.
            assignment_epoch: AssignmentEpoch::new(),
            probe_client: reqwest::Client::builder()
                .timeout(readiness::PROBE_TIMEOUT)
                .build()
                .expect("failed to create probe client"),
        }
    }

    /// Share the process-wide assignment epoch. Call before the transport is
    /// shared, so every stamped sub-batch carries the same generation the
    /// rebalance context bumps.
    pub fn set_assignment_epoch(&mut self, epoch: AssignmentEpoch) {
        self.assignment_epoch = epoch;
    }

    /// The assignment epoch this transport stamps on sub-batches.
    pub fn assignment_epoch(&self) -> AssignmentEpoch {
        self.assignment_epoch.clone()
    }

    /// Override the per-frame size cap. Call before the transport is shared.
    pub fn set_max_body_bytes(&mut self, bytes: usize) {
        assert!(bytes > 0, "max_body_bytes must be > 0");
        self.max_body_bytes = bytes;
    }

    /// Enqueue a sub-batch on the worker's stream. Synchronous on purpose: call
    /// in send order (the consumer loop / serialized flush paths) — the worker stream
    /// preserves enqueue order onto the stream.
    ///
    /// A sub-batch whose estimated size exceeds `max_body_bytes` goes on the
    /// stream as consecutive chunks, so one frame never crosses the worker's
    /// message limit. Consecutive chunks on one ordered stream keep the
    /// sub-batch's order, and the caller still sees one send.
    pub fn begin_send(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> PendingWorkerStreamSend {
        let options = SendOptions {
            replay,
            soft_budget: None,
        };
        self.begin_send_with(worker_url, batch_id, messages, options)
    }

    pub fn begin_send_with(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        options: SendOptions,
    ) -> PendingWorkerStreamSend {
        let chunks = split_by_size(messages, self.max_body_bytes);
        if chunks.len() > 1 {
            counter!(
                "ingestion_consumer_transport_batch_splits_total",
                "reason" => "size_estimate"
            )
            .increment((chunks.len() - 1) as u64);
        }
        // The worker runs each frame as its own batch, so in a split send a
        // key's later message could finish while an earlier one is left
        // unfinished.
        let soft_budget_ms = match options.soft_budget {
            Some(budget) if chunks.len() == 1 && !budget.is_zero() => {
                u64::try_from(budget.as_millis()).unwrap_or(u64::MAX).max(1)
            }
            _ => 0,
        };
        let replay = options.replay;
        let stream = self.worker_stream_for(worker_url);
        let receivers = chunks
            .into_iter()
            .map(|messages| {
                let (reply, rx) = oneshot::channel();
                let item = WorkerStreamItem {
                    batch_id: batch_id.to_string(),
                    messages,
                    replay,
                    soft_budget_ms,
                    reply,
                };
                if let Err(send_err) = stream.tx.send(item) {
                    // Worker stream task gone (removed worker): fail the send
                    // immediately with its messages so the caller defers and
                    // re-routes.
                    let item = send_err.0;
                    let _ = item.reply.send(Err(SendError {
                        error: TransportError::WorkerStreamClosed,
                        messages: item.messages,
                        fence_guard: None,
                    }));
                }
                rx
            })
            .collect();
        PendingWorkerStreamSend { chunks: receivers }
    }

    fn worker_stream_for(&self, worker_url: &str) -> Arc<WorkerStream> {
        if let Some(stream) = self.worker_streams.get(worker_url) {
            return stream.clone();
        }
        self.worker_streams
            .entry(worker_url.to_string())
            .or_insert_with(|| Arc::new(self.spawn_worker_stream(worker_url)))
            .clone()
    }

    fn spawn_worker_stream(&self, worker_url: &str) -> WorkerStream {
        let (tx, rx) = mpsc::unbounded_channel();
        let runner = WorkerStreamRunner {
            worker_url: Arc::from(worker_url),
            grpc_url: grpc_url(worker_url, self.grpc_port),
            consumer_id: self.consumer_id.clone(),
            ack_timeout: self.ack_timeout,
            assignment_epoch: self.assignment_epoch.clone(),
        };
        tokio::spawn(async move { runner.run(rx).await });
        WorkerStream { tx }
    }

    /// Tear down a departed worker's stream. Dropping it closes its queue
    /// sender: the runner takes no more work, lets the sub-batches already on
    /// the wire settle by ack or by the ack watchdog, and exits on its own.
    /// A reaped worker that is slow rather than dead so finishes its request
    /// instead of a survivor repeating it while it still runs. Aborting the
    /// task would instead drop the un-acked sends unresolved, which the caller
    /// can only recover by crashing and replaying.
    pub fn remove_worker(&self, worker_url: &str) {
        self.worker_streams.remove(worker_url);
    }

    /// Check if a worker is ready by probing its HTTP health endpoint.
    pub async fn check_ready(&self, worker_url: &str) -> bool {
        readiness::check_ready(&self.probe_client, worker_url).await
    }

    /// Wait until all workers are ready, polling with backoff.
    pub async fn wait_for_workers_ready(
        &self,
        worker_urls: &[String],
        shutdown: &lifecycle::Handle,
    ) -> anyhow::Result<()> {
        readiness::wait_for_workers_ready(&self.probe_client, worker_urls, shutdown).await
    }
}

/// One un-acked sub-batch on the stream.
struct LedgerEntry {
    seq: u64,
    item: WorkerStreamItem,
    /// Per-send ack deadline, armed when the sub-batch went on the wire. The
    /// watchdog fences on the oldest entry's deadline, so a stuck sub-batch
    /// times out even while its siblings keep acking.
    deadline: tokio::time::Instant,
    /// When the sub-batch went on the wire, for the send-to-ack latency histogram.
    sent_at: std::time::Instant,
    /// The worker's answer once acked. The entry stays in the ledger until
    /// every earlier entry is acked too, so a fence still reaches it.
    acked: Option<Ack>,
}

struct Ack {
    accepted: u32,
    unfinished: Vec<MessageRef>,
}

/// An open stream: the request sender and the worker's ack stream.
type OpenStream = (
    mpsc::UnboundedSender<IngestStreamRequest>,
    tonic::Streaming<IngestStreamResponse>,
);

/// One event off the ack stream: a frame, a clean end (`None`), or an error.
type AckEvent = Result<Option<IngestStreamResponse>, tonic::Status>;

struct WorkerStreamRunner {
    worker_url: Arc<str>,
    grpc_url: String,
    consumer_id: String,
    ack_timeout: Duration,
    assignment_epoch: AssignmentEpoch,
}

impl WorkerStreamRunner {
    /// Worker stream lifecycle: connect, stream until something breaks, fence
    /// everything outstanding, reconnect. Ends when the transport drops the
    /// queue sender (worker removed or shutdown).
    async fn run(self, mut queue: mpsc::UnboundedReceiver<WorkerStreamItem>) {
        let mut stream_epoch = 0u64;
        let mut backoff = Duration::from_millis(100);
        loop {
            stream_epoch += 1;
            match self.run_stream(&mut queue, stream_epoch).await {
                StreamEnd::QueueClosed => {
                    info!(worker = %self.worker_url, "Worker stream queue closed, exiting");
                    return;
                }
                StreamEnd::Failed(fence) => {
                    counter!(
                        "ingestion_consumer_worker_stream_teardowns_total",
                        "worker" => self.worker_url.clone(),
                    )
                    .increment(1);
                    let fenced = fence.settle(&mut queue).await;
                    if fenced > 0 {
                        counter!(
                            "ingestion_consumer_worker_stream_fenced_sub_batches_total",
                            "worker" => self.worker_url.clone(),
                        )
                        .increment(fenced as u64);
                    }
                    tokio::time::sleep(jittered(backoff)).await;
                    backoff = (backoff * 2).min(Duration::from_secs(5));
                }
                StreamEnd::Idle => {
                    // Stream ended cleanly with nothing outstanding (e.g. the
                    // worker restarted gracefully) — reconnect without delay
                    // escalation.
                    backoff = Duration::from_millis(100);
                }
            }
        }
    }

    /// Run one stream incarnation. Returns how it ended; on `Failed`, every
    /// queued and un-acked item has been resolved as failed, in order.
    async fn run_stream(
        &self,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        stream_epoch: u64,
    ) -> StreamEnd {
        // Hold sends until there is work: connecting eagerly on an idle worker stream
        // would spin reconnects against a worker that never gets traffic.
        let first = match queue.recv().await {
            Some(item) => item,
            None => return StreamEnd::QueueClosed,
        };

        let mut ledger: VecDeque<LedgerEntry> = VecDeque::new();
        let mut pending_first = Some(first);

        let (out_tx, mut acks) = match self.open_stream(stream_epoch).await {
            Ok(stream) => stream,
            Err(reason) => return self.fence(pending_first.take(), &mut ledger, queue, reason),
        };

        let mut next_seq = 1u64;
        self.record_ledger_depth(0);

        loop {
            if let Err(end) = self.fill_ledger(
                &out_tx,
                queue,
                &mut pending_first,
                &mut ledger,
                &mut next_seq,
            ) {
                return end;
            }
            let ack = match self
                .await_next_ack(&mut acks, queue, &mut pending_first, &mut ledger)
                .await
            {
                Ok(Some(ack)) => ack,
                Ok(None) => continue,
                Err(end) => return end,
            };
            if let Err(end) = self.handle_ack(ack, queue, &mut pending_first, &mut ledger) {
                return end;
            }
        }
    }

    /// Connect, greet, and open the ack stream. On failure the caller fences
    /// with the returned reason.
    async fn open_stream(&self, stream_epoch: u64) -> Result<OpenStream, &'static str> {
        // The inner connect_timeout bounds TCP only; the outer bound covers
        // everything else in connection setup (e.g. an h2 handshake that
        // never completes because the far side is not actually h2).
        let endpoint = match tonic::transport::Endpoint::from_shared(self.grpc_url.clone()) {
            Ok(endpoint) => endpoint.connect_timeout(Duration::from_secs(5)),
            Err(err) => {
                error!(worker = %self.worker_url, grpc_url = %self.grpc_url, error = %err, "Invalid worker stream address");
                return Err("invalid address");
            }
        };
        let channel = match tokio::time::timeout(self.ack_timeout, endpoint.connect()).await {
            Ok(Ok(channel)) => channel,
            Ok(Err(err)) => {
                warn!(
                    worker = %self.worker_url,
                    grpc_url = %self.grpc_url,
                    error = %err,
                    "Worker stream connect failed"
                );
                return Err("connect failed");
            }
            Err(_) => {
                warn!(
                    worker = %self.worker_url,
                    grpc_url = %self.grpc_url,
                    timeout_ms = self.ack_timeout.as_millis() as u64,
                    "Worker stream connect timed out"
                );
                return Err("connect timeout");
            }
        };

        let mut client = WorkerIngestClient::new(channel)
            .send_compressed(tonic::codec::CompressionEncoding::Gzip)
            .accept_compressed(tonic::codec::CompressionEncoding::Gzip);

        let (out_tx, out_rx) = mpsc::unbounded_channel::<IngestStreamRequest>();
        let hello = IngestStreamRequest {
            msg: Some(ingest_stream_request::Msg::Hello(StreamHello {
                consumer_id: self.consumer_id.clone(),
                stream_epoch,
            })),
        };
        if out_tx.send(hello).is_err() {
            return Err("stream closed");
        }

        // Stream-open resolves only when the worker's response headers (its
        // greeting) arrive; bound it so a worker that never greets fences
        // instead of deadlocking the worker stream — the failure mode that wedged
        // production before the greeting existed.
        match tokio::time::timeout(
            self.ack_timeout,
            client.ingest_stream(UnboundedReceiverStream::new(out_rx)),
        )
        .await
        {
            Ok(Ok(response)) => Ok((out_tx, response.into_inner())),
            Err(_) => {
                warn!(
                    worker = %self.worker_url,
                    grpc_url = %self.grpc_url,
                    timeout_ms = self.ack_timeout.as_millis() as u64,
                    "Worker stream stream open timed out — no greeting from the worker"
                );
                Err("stream open timeout")
            }
            Ok(Err(status)) => {
                warn!(worker = %self.worker_url, grpc_url = %self.grpc_url, status = %status, "Worker stream stream open failed");
                Err("stream open failed")
            }
        }
    }

    /// The batcher caps the requests in flight per worker, so nothing is held
    /// back here. A closed queue stops the filling; the ledger still drains by
    /// ack. `Err` ends the stream.
    fn fill_ledger(
        &self,
        out_tx: &mpsc::UnboundedSender<IngestStreamRequest>,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        pending_first: &mut Option<WorkerStreamItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        next_seq: &mut u64,
    ) -> Result<(), StreamEnd> {
        loop {
            let item = match pending_first.take() {
                Some(item) => Some(item),
                None => match queue.try_recv() {
                    Ok(item) => Some(item),
                    Err(mpsc::error::TryRecvError::Empty) => None,
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        if ledger.is_empty() {
                            return Err(StreamEnd::QueueClosed);
                        }
                        None
                    }
                },
            };
            let Some(item) = item else { break };
            let seq = *next_seq;
            *next_seq += 1;
            let request = IngestStreamRequest {
                msg: Some(ingest_stream_request::Msg::SubBatch(SubBatch {
                    seq,
                    batch_id: item.batch_id.clone(),
                    messages: item.messages.iter().map(to_proto_message).collect(),
                    replay: item.replay,
                    assignment_epoch: self.assignment_epoch.current(),
                    soft_budget_ms: item.soft_budget_ms,
                })),
            };
            // tonic gzips the frame after this point, so only the raw size is observable here.
            counter!("ingestion_consumer_transport_body_bytes_total", "encoding" => "protobuf")
                .increment(request.encoded_len() as u64);
            let deadline = tokio::time::Instant::now() + self.ack_timeout;
            let sent = out_tx.send(request).is_ok();
            ledger.push_back(LedgerEntry {
                seq,
                item,
                deadline,
                sent_at: std::time::Instant::now(),
                acked: None,
            });
            if !sent {
                return Err(self.fence(None, ledger, queue, "stream closed mid-send"));
            }
            self.record_ledger_depth(ledger.len());
        }
        Ok(())
    }

    /// Un-acked sub-batches on the stream, also published as the per-worker in-flight gauge.
    fn record_ledger_depth(&self, depth: usize) {
        gauge!("ingestion_consumer_worker_stream_ledger_depth", "worker" => self.worker_url.clone())
            .set(depth as f64);
        gauge!("ingestion_consumer_transport_concurrent_batches", "worker" => self.worker_url.clone())
            .set(depth as f64);
    }

    fn record_send_duration(&self, entry: &LedgerEntry) {
        histogram!("ingestion_consumer_transport_duration_seconds", "worker" => self.worker_url.clone())
            .record(entry.sent_at.elapsed().as_secs_f64());
    }

    /// Wait for an ack, or for new work while the queue is open. `Ok(None)`
    /// means new work was held in `pending_first`, or the queue closed under
    /// the wait and the ledger still drains; `Err` ends the stream.
    ///
    /// The ack-progress watchdog bounds how long the oldest un-acked
    /// sub-batch may sit unacked. Each entry carries its own deadline, armed
    /// when it was sent, so the watchdog keys on the oldest (front) entry,
    /// which is never acked (acked prefixes pop at once): a stuck sub-batch
    /// fences even while its siblings keep acking. A worker that stops acking (saturated
    /// by other consumers, wedged, half-dead network) becomes a fence — and
    /// so a defer-and-reroute — rather than a silent forever-wait.
    async fn await_next_ack(
        &self,
        acks: &mut tonic::Streaming<IngestStreamResponse>,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        pending_first: &mut Option<WorkerStreamItem>,
        ledger: &mut VecDeque<LedgerEntry>,
    ) -> Result<Option<AckEvent>, StreamEnd> {
        let Some(front) = ledger.front() else {
            return match queue.recv().await {
                Some(item) => {
                    *pending_first = Some(item);
                    Ok(None)
                }
                None => Err(StreamEnd::QueueClosed),
            };
        };
        let watchdog = tokio::time::sleep_until(front.deadline);
        tokio::select! {
            ack = acks.message() => Ok(Some(ack)),
            _ = watchdog => {
                warn!(
                    worker = %self.worker_url,
                    unacked = ledger.len(),
                    timeout_ms = self.ack_timeout.as_millis() as u64,
                    "No ack progress within the watchdog window — fencing worker stream"
                );
                Err(self.fence(pending_first.take(), ledger, queue, "ack progress timeout"))
            }
            item = queue.recv(), if !queue.is_closed() => {
                *pending_first = item;
                Ok(None)
            }
        }
    }

    /// Apply one ack-stream event to the ledger. `Err` ends the stream.
    fn handle_ack(
        &self,
        ack: AckEvent,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        pending_first: &mut Option<WorkerStreamItem>,
        ledger: &mut VecDeque<LedgerEntry>,
    ) -> Result<(), StreamEnd> {
        let frame = match ack {
            Ok(Some(frame)) => frame,
            Ok(None) => {
                return Err(if ledger.is_empty() && pending_first.is_none() {
                    StreamEnd::Idle
                } else {
                    self.fence(pending_first.take(), ledger, queue, "stream ended")
                });
            }
            Err(status) => {
                warn!(worker = %self.worker_url, status = %status, "Worker stream stream failed");
                return Err(self.fence(pending_first.take(), ledger, queue, "stream error"));
            }
        };
        // `ready` is the worker's greeting (and any future keepalive): it
        // exists to flush response headers, not to resolve work. A frame this
        // consumer predates is ignored the same way.
        let response = match frame.msg {
            Some(ingest_stream_response::Msg::Ack(ack)) => ack,
            Some(ingest_stream_response::Msg::Ready(_)) | None => return Ok(()),
        };
        if response.status == SubBatchStatus::Failed as i32 {
            warn!(
                worker = %self.worker_url,
                seq = response.seq,
                error = %response.error,
                "Worker nacked sub-batch — fencing worker stream"
            );
            return Err(self.fence(None, ledger, queue, "sub-batch nacked"));
        }
        let partial = response.status == SubBatchStatus::Partial as i32;
        if response.status != SubBatchStatus::Ok as i32 && !partial {
            // BUSY, or any status this consumer predates: transient
            // backpressure, not a fault. Fence in order (the ordered stream
            // cannot retry one sub-batch in place) but as retriable, so the
            // work re-routes without marking the worker unhealthy.
            warn!(
                worker = %self.worker_url,
                seq = response.seq,
                status = response.status,
                "Worker signalled busy — fencing worker stream as retriable"
            );
            return Err(self.fence_with(true, None, ledger, queue, "worker busy"));
        }
        let Some(index) = ledger
            .iter()
            .position(|e| e.seq == response.seq && e.acked.is_none())
        else {
            warn!(worker = %self.worker_url, seq = response.seq, "Ack for unknown seq — fencing worker stream");
            return Err(self.fence(None, ledger, queue, "unknown ack seq"));
        };
        if let Some(reason) = ack_shape_error(&ledger[index].item, &response) {
            warn!(
                worker = %self.worker_url,
                seq = response.seq,
                reason,
                "Malformed ack — fencing worker stream"
            );
            return Err(self.fence(None, ledger, queue, reason));
        }
        let entry = &mut ledger[index];
        entry.acked = Some(Ack {
            accepted: response.accepted,
            unfinished: response.unfinished,
        });
        self.record_send_duration(entry);
        counter!(
            "ingestion_consumer_transport_requests_total",
            "worker" => self.worker_url.clone(),
            "status" => if partial { "partial" } else { "ok" }
        )
        .increment(1);
        // Resolve only the acked prefix: a later ack waits for every earlier
        // seq, so a failure ahead of it still fences it instead of letting it
        // release its keys first.
        while ledger.front().is_some_and(|e| e.acked.is_some()) {
            let entry = ledger.pop_front().expect("front is present");
            let Ack {
                accepted,
                unfinished,
            } = entry.acked.expect("front is acked");
            let WorkerStreamItem {
                reply, messages, ..
            } = entry.item;
            let _ = reply.send(Ok(Accepted {
                accepted,
                unfinished,
                messages,
            }));
        }
        self.record_ledger_depth(ledger.len());
        Ok(())
    }

    /// Resolve everything outstanding as failed, **in enqueue order**: the
    /// un-acked ledger first, then anything still queued (which was enqueued
    /// after everything in the ledger). Order matters because the batcher
    /// requeues each failed send at the front of its keys' queues, so
    /// resolving in order keeps every fenced key's messages queued
    /// oldest-first and the retry (oldest first) is the same request that
    /// failed.
    fn fence(
        &self,
        pending_first: Option<WorkerStreamItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        reason: &'static str,
    ) -> StreamEnd {
        self.fence_with(false, pending_first, ledger, queue, reason)
    }

    /// `retriable` distinguishes transient backpressure (a busy worker) from a
    /// real fault: the fenced sends carry a retriable error so the caller
    /// re-routes them without counting the worker as unhealthy, and the metric
    /// records `busy` rather than `error`.
    fn fence_with(
        &self,
        retriable: bool,
        pending_first: Option<WorkerStreamItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>,
        reason: &'static str,
    ) -> StreamEnd {
        let mut fence = Fence::new(retriable, reason);
        for entry in ledger.drain(..) {
            if entry.acked.is_none() {
                self.record_send_duration(&entry);
            }
            fence.fail(entry.item);
        }
        if let Some(item) = pending_first {
            fence.fail(item);
        }
        while let Ok(item) = queue.try_recv() {
            fence.fail(item);
        }
        counter!(
            "ingestion_consumer_transport_requests_total",
            "worker" => self.worker_url.clone(),
            "status" => if retriable { "busy" } else { "error" }
        )
        .increment(1);
        self.record_ledger_depth(0);
        StreamEnd::Failed(fence)
    }
}

/// A fence in progress. Every fenced send carries a [`FenceGuard`]; until all
/// of them are dropped the worker stream fails each new arrival too, so a send
/// enqueued before the fenced messages are requeued cannot ride the next
/// stream ahead of them.
struct Fence {
    retriable: bool,
    reason: &'static str,
    released_tx: mpsc::UnboundedSender<()>,
    released_rx: mpsc::UnboundedReceiver<()>,
    /// Guards handed out and not yet dropped.
    outstanding: usize,
    fenced: usize,
}

impl Fence {
    fn new(retriable: bool, reason: &'static str) -> Self {
        let (released_tx, released_rx) = mpsc::unbounded_channel();
        Self {
            retriable,
            reason,
            released_tx,
            released_rx,
            outstanding: 0,
            fenced: 0,
        }
    }

    fn fail(&mut self, item: WorkerStreamItem) {
        let error = if self.retriable {
            TransportError::WorkerStreamBusy(self.reason)
        } else {
            TransportError::WorkerStreamFailed(self.reason)
        };
        self.outstanding += 1;
        self.fenced += 1;
        // A caller that already dropped its receiver drops the guard here,
        // which releases it at once.
        let _ = item.reply.send(Err(SendError {
            error,
            messages: item.messages,
            fence_guard: Some(FenceGuard::new(self.released_tx.clone())),
        }));
    }

    /// Fail arrivals until every fenced caller has dropped its guard. Returns
    /// how many sends the fence failed in total.
    async fn settle(mut self, queue: &mut mpsc::UnboundedReceiver<WorkerStreamItem>) -> usize {
        while self.outstanding > 0 {
            // Releases first: a caller drops its guard before it can enqueue
            // again, so a release already waiting must not lose to the send
            // that followed it and fence that send for nothing.
            tokio::select! {
                biased;
                released = self.released_rx.recv() => {
                    if released.is_some() {
                        self.outstanding -= 1;
                    }
                }
                item = queue.recv() => match item {
                    Some(item) => self.fail(item),
                    // Queue closed: nothing more can arrive, and the runner
                    // exits on its next receive.
                    None => break,
                },
            }
        }
        self.fenced
    }
}

enum StreamEnd {
    /// The transport dropped the queue sender — worker removed or shutdown.
    QueueClosed,
    /// The stream broke; the fence holds what was resolved as failed and
    /// keeps fencing until those callers have requeued their messages.
    Failed(Fence),
    /// The stream ended cleanly with nothing outstanding.
    Idle,
}

/// A worker bug that misreports what it processed would lose or double
/// complete messages, so an ack that does not match its sub-batch fences the
/// stream as a fault.
fn ack_shape_error(item: &WorkerStreamItem, ack: &SubBatchAck) -> Option<&'static str> {
    if ack.status != SubBatchStatus::Partial as i32 {
        return (!ack.unfinished.is_empty()).then_some("unfinished on a non-partial ack");
    }
    if item.soft_budget_ms == 0 {
        return Some("partial ack for an unbudgeted sub-batch");
    }
    if ack.unfinished.is_empty() {
        return Some("partial ack with no unfinished entries");
    }
    if ack.accepted as usize + ack.unfinished.len() != item.messages.len() {
        return Some("partial ack does not account for every message");
    }
    // A partition revoked and regained inside one poll delivers an offset
    // twice, so a sub-batch may carry one coordinate more than once.
    let mut carried: HashMap<(i32, i64), usize> = HashMap::with_capacity(item.messages.len());
    for message in &item.messages {
        *carried
            .entry((message.partition, message.offset))
            .or_default() += 1;
    }
    for message in &ack.unfinished {
        match carried.get_mut(&(message.partition, message.offset)) {
            Some(left) if *left > 0 => *left -= 1,
            Some(_) => {
                return Some("partial ack lists a message more often than the sub-batch carried it")
            }
            None => return Some("partial ack lists a message the sub-batch did not carry"),
        }
    }
    None
}

fn to_proto_message(message: &SerializedKafkaMessage) -> KafkaMessage {
    KafkaMessage {
        topic: message.topic.to_string(),
        partition: message.partition,
        offset: message.offset,
        timestamp: message.timestamp,
        key: message.key.clone(),
        value: message.value.clone(),
        headers: message.headers.clone(),
    }
}

/// Derive the worker's gRPC address from its HTTP URL: same host, gRPC port.
/// Worker URLs are `http://<host-or-ip>:<port>` (see `discovery::addr_to_worker`).
fn grpc_url(worker_url: &str, grpc_port: GrpcPort) -> String {
    let without_scheme = worker_url
        .strip_prefix("http://")
        .or_else(|| worker_url.strip_prefix("https://"))
        .unwrap_or(worker_url);
    let (host, http_port) = match without_scheme.rfind(':') {
        // Don't split inside an unbracketed IPv6 literal.
        Some(idx) if !without_scheme[idx + 1..].contains(']') => (
            &without_scheme[..idx],
            without_scheme[idx + 1..].parse::<u16>().unwrap_or(0),
        ),
        _ => (without_scheme, 0),
    };
    let port = match grpc_port {
        GrpcPort::Fixed(port) => port,
        GrpcPort::OffsetFromHttp(offset) => http_port.saturating_add(offset),
    };
    format!("http://{host}:{port}")
}

fn jittered(base: Duration) -> Duration {
    let jitter = rand::random::<f64>() * 0.5 + 0.75;
    base.mul_f64(jitter)
}

/// Process-unique sender id: workers scope feed-order baselines to one
/// consumer incarnation.
fn make_consumer_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}
