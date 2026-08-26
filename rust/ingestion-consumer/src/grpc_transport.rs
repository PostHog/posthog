//! Ordered streaming transport: one `WorkerIngest` lane per worker.
//!
//! Each lane owns a bidirectional gRPC stream to its worker and drains an
//! ordered queue: enqueue order is send order is the worker's feed order,
//! which is the per-key ordering guarantee concurrent HTTP requests cannot
//! give. `begin_send` enqueues synchronously — call it where send order is
//! decided (the consumer loop, right after assignment) — and hands back a
//! [`PendingLaneSend`] the caller awaits like an HTTP response.
//!
//! **Acks resolve in send order.** The worker acks sub-batches as they
//! complete, out of order. The lane records each ack in its ledger and
//! resolves only the consecutive acked prefix, so a send never succeeds
//! while an earlier one is still open: if that earlier one then fails, the
//! later one is still in the ledger and fences with it, instead of having
//! already released its keys and left the older messages to replay after
//! the newer ones.
//!
//! **Failure fences the whole lane.** A nack, stream break, or connect
//! failure resolves every queued and un-acked item, in enqueue order, with a
//! [`SendError`] carrying the messages back — the callers' existing
//! `defer_failed` path then stashes them, and the dispatcher's outstanding
//! counts hold all newer work for those keys until the failed groups are
//! retried (oldest first) and acked. Each fenced send also carries a
//! [`FenceGuard`]; the lane keeps fencing every new arrival until all guards
//! are dropped, which closes the gap between a send resolving and its
//! caller stashing, where the consumer loop could otherwise enqueue a fenced
//! key's next group and the next stream would send it first. Nothing for a
//! fenced key can leapfrog the failure, because everything for it was either
//! in the ledger, the queue, or fenced on arrival.
//!
//! Backpressure: the queue is unbounded (so enqueue stays synchronous and
//! ordered) but the lane keeps at most `max_unacked` sub-batches un-acked on
//! the stream; queue depth is bounded in practice by the consumer's
//! `max_in_flight_batches`, whose batches cannot complete until their sends
//! resolve.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_client::WorkerIngestClient;
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    KafkaMessage, StreamHello, SubBatch, SubBatchStatus,
};
use metrics::{counter, gauge};
use tokio::sync::{mpsc, oneshot};
use tokio_stream::wrappers::UnboundedReceiverStream;
use tracing::{error, info, warn};

use crate::readiness;
use crate::transport::{FenceGuard, SendError, TransportError};
use crate::types::SerializedKafkaMessage;

/// An enqueued sub-batch awaiting its ack; resolves like an HTTP send.
pub struct PendingLaneSend {
    rx: oneshot::Receiver<Result<u32, SendError>>,
}

impl PendingLaneSend {
    pub async fn wait(self) -> Result<u32, SendError> {
        match self.rx.await {
            Ok(result) => result,
            // The lane task died without resolving its items — a bug, not an
            // operational failure. The messages are gone, so the batch cannot
            // reach its accepted total and the consumer exits and replays.
            Err(_) => Err(SendError {
                error: TransportError::LaneClosed,
                messages: Vec::new(),
                fence_guard: None,
            }),
        }
    }
}

struct LaneItem {
    batch_id: String,
    messages: Vec<SerializedKafkaMessage>,
    replay: bool,
    reply: oneshot::Sender<Result<u32, SendError>>,
}

struct Lane {
    tx: mpsc::UnboundedSender<LaneItem>,
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
    lanes: DashMap<String, Arc<Lane>>,
    consumer_id: String,
    /// How each worker's stream address is derived from its HTTP URL.
    grpc_port: GrpcPort,
    /// Max un-acked sub-batches per lane (aligned with the worker's
    /// `concurrentBatches`, like the HTTP semaphore it replaces).
    max_unacked: usize,
    /// Fence the lane when un-acked work sees no ack for this long.
    ack_timeout: Duration,
    /// Bumped on Kafka partition assignment; stamped on every sub-batch so
    /// the worker sentinel rebaselines across rebalances.
    assignment_epoch: Arc<AtomicU64>,
    /// Readiness probing stays HTTP: workers always serve `/_ready`.
    probe_client: reqwest::Client,
}

impl GrpcTransport {
    pub fn new(grpc_port: GrpcPort, max_unacked: usize, ack_timeout: Duration) -> Self {
        assert!(max_unacked > 0, "max_unacked must be > 0");
        Self {
            lanes: DashMap::new(),
            consumer_id: make_consumer_id(),
            grpc_port,
            max_unacked,
            ack_timeout,
            assignment_epoch: Arc::new(AtomicU64::new(1)),
            probe_client: reqwest::Client::builder()
                .timeout(readiness::PROBE_TIMEOUT)
                .build()
                .expect("failed to create probe client"),
        }
    }

    /// Shared epoch counter; the consumer's rebalance context bumps it.
    pub fn assignment_epoch(&self) -> Arc<AtomicU64> {
        Arc::clone(&self.assignment_epoch)
    }

    /// Enqueue a sub-batch on the worker's lane. Synchronous on purpose: call
    /// in send order (the consumer loop / serialized flush paths) — the lane
    /// preserves enqueue order onto the stream.
    pub fn begin_send(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> PendingLaneSend {
        let (reply, rx) = oneshot::channel();
        let item = LaneItem {
            batch_id: batch_id.to_string(),
            messages,
            replay,
            reply,
        };
        let lane = self.lane_for(worker_url);
        if let Err(send_err) = lane.tx.send(item) {
            // Lane task gone (removed worker): fail the send immediately with
            // its messages so the caller defers and re-routes.
            let item = send_err.0;
            let _ = item.reply.send(Err(SendError {
                error: TransportError::LaneClosed,
                messages: item.messages,
                fence_guard: None,
            }));
        }
        PendingLaneSend { rx }
    }

    fn lane_for(&self, worker_url: &str) -> Arc<Lane> {
        if let Some(lane) = self.lanes.get(worker_url) {
            return lane.clone();
        }
        self.lanes
            .entry(worker_url.to_string())
            .or_insert_with(|| Arc::new(self.spawn_lane(worker_url)))
            .clone()
    }

    fn spawn_lane(&self, worker_url: &str) -> Lane {
        let (tx, rx) = mpsc::unbounded_channel();
        let runner = LaneRunner {
            worker_url: Arc::from(worker_url),
            grpc_url: grpc_url(worker_url, self.grpc_port),
            consumer_id: self.consumer_id.clone(),
            max_unacked: self.max_unacked,
            ack_timeout: self.ack_timeout,
            assignment_epoch: Arc::clone(&self.assignment_epoch),
        };
        tokio::spawn(async move { runner.run(rx).await });
        Lane { tx }
    }

    /// Tear down a departed worker's lane. Dropping the lane closes its queue
    /// sender, so the runner fences whatever is still in flight **in order**,
    /// with the messages intact, and exits on its own. Aborting the task would
    /// instead drop the un-acked sends unresolved, which the caller can only
    /// recover by crashing and replaying — so let the graceful path run.
    pub fn remove_worker(&self, worker_url: &str) {
        self.lanes.remove(worker_url);
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
    item: LaneItem,
    /// Per-send ack deadline, armed when the sub-batch went on the wire. The
    /// watchdog fences on the oldest entry's deadline, so a stuck sub-batch
    /// times out even while its siblings keep acking.
    deadline: tokio::time::Instant,
    /// The worker's accepted count once acked. The entry stays in the ledger
    /// until every earlier entry is acked too, so a fence still reaches it.
    acked: Option<u32>,
}

/// An open stream: the request sender and the worker's ack stream.
type OpenStream = (
    mpsc::UnboundedSender<IngestStreamRequest>,
    tonic::Streaming<IngestStreamResponse>,
);

/// One event off the ack stream: a frame, a clean end (`None`), or an error.
type AckEvent = Result<Option<IngestStreamResponse>, tonic::Status>;

struct LaneRunner {
    worker_url: Arc<str>,
    grpc_url: String,
    consumer_id: String,
    max_unacked: usize,
    ack_timeout: Duration,
    assignment_epoch: Arc<AtomicU64>,
}

impl LaneRunner {
    /// Lane lifecycle: connect, stream until something breaks, fence
    /// everything outstanding, reconnect. Ends when the transport drops the
    /// queue sender (worker removed or shutdown).
    async fn run(self, mut queue: mpsc::UnboundedReceiver<LaneItem>) {
        let mut stream_epoch = 0u64;
        let mut backoff = Duration::from_millis(100);
        loop {
            stream_epoch += 1;
            match self.run_stream(&mut queue, stream_epoch).await {
                StreamEnd::QueueClosed => {
                    info!(worker = %self.worker_url, "Lane queue closed, exiting");
                    return;
                }
                StreamEnd::Failed(fence) => {
                    counter!(
                        "ingestion_consumer_lane_teardowns_total",
                        "worker" => self.worker_url.clone(),
                    )
                    .increment(1);
                    let fenced = fence.settle(&mut queue).await;
                    if fenced > 0 {
                        counter!(
                            "ingestion_consumer_lane_fenced_sub_batches_total",
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
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
        stream_epoch: u64,
    ) -> StreamEnd {
        // Hold sends until there is work: connecting eagerly on an idle lane
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
        gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
            .set(0.0);

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
                error!(worker = %self.worker_url, grpc_url = %self.grpc_url, error = %err, "Invalid lane address");
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
                    "Lane connect failed"
                );
                return Err("connect failed");
            }
            Err(_) => {
                warn!(
                    worker = %self.worker_url,
                    grpc_url = %self.grpc_url,
                    timeout_ms = self.ack_timeout.as_millis() as u64,
                    "Lane connect timed out"
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
        // instead of deadlocking the lane — the failure mode that wedged
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
                    "Lane stream open timed out — no greeting from the worker"
                );
                Err("stream open timeout")
            }
            Ok(Err(status)) => {
                warn!(worker = %self.worker_url, grpc_url = %self.grpc_url, status = %status, "Lane stream open failed");
                Err("stream open failed")
            }
        }
    }

    /// Send the held first item, then pull more only while the ledger has
    /// room — the worker-aligned concurrency cap. `Err` ends the stream.
    fn fill_ledger(
        &self,
        out_tx: &mpsc::UnboundedSender<IngestStreamRequest>,
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
        pending_first: &mut Option<LaneItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        next_seq: &mut u64,
    ) -> Result<(), StreamEnd> {
        while ledger.len() < self.max_unacked {
            let item = match pending_first.take() {
                Some(item) => Some(item),
                None => match queue.try_recv() {
                    Ok(item) => Some(item),
                    Err(mpsc::error::TryRecvError::Empty) => None,
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        return Err(if ledger.is_empty() {
                            StreamEnd::QueueClosed
                        } else {
                            // Resolve the tail before exiting.
                            self.fence(None, ledger, queue, "queue closed")
                        });
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
                    assignment_epoch: self.assignment_epoch.load(Ordering::Relaxed),
                })),
            };
            let deadline = tokio::time::Instant::now() + self.ack_timeout;
            let sent = out_tx.send(request).is_ok();
            ledger.push_back(LedgerEntry {
                seq,
                item,
                deadline,
                acked: None,
            });
            if !sent {
                return Err(self.fence(None, ledger, queue, "stream closed mid-send"));
            }
            gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
                .set(ledger.len() as f64);
        }
        Ok(())
    }

    /// Wait for an ack, or for new work when the ledger has room. `Ok(None)`
    /// means new work was held in `pending_first`; `Err` ends the stream.
    ///
    /// The ack-progress watchdog bounds how long the oldest un-acked
    /// sub-batch may sit unacked. Each entry carries its own deadline, armed
    /// when it was sent, so the watchdog keys on the oldest (front) entry,
    /// which is never acked (acked prefixes pop at once): a stuck sub-batch
    /// fences even while its siblings keep acking — the per-send bound the
    /// HTTP timeout it replaces gave. A worker that stops acking (saturated
    /// by other consumers, wedged, half-dead network) becomes a fence — and
    /// so a defer-and-reroute — rather than a silent forever-wait.
    async fn await_next_ack(
        &self,
        acks: &mut tonic::Streaming<IngestStreamResponse>,
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
        pending_first: &mut Option<LaneItem>,
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
                    "No ack progress within the watchdog window — fencing lane"
                );
                Err(self.fence(pending_first.take(), ledger, queue, "ack progress timeout"))
            }
            item = queue.recv(), if ledger.len() < self.max_unacked => match item {
                Some(item) => {
                    *pending_first = Some(item);
                    Ok(None)
                }
                None => Err(self.fence(None, ledger, queue, "queue closed")),
            }
        }
    }

    /// Apply one ack-stream event to the ledger. `Err` ends the stream.
    fn handle_ack(
        &self,
        ack: AckEvent,
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
        pending_first: &mut Option<LaneItem>,
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
                warn!(worker = %self.worker_url, status = %status, "Lane stream failed");
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
                "Worker nacked sub-batch — fencing lane"
            );
            return Err(self.fence(None, ledger, queue, "sub-batch nacked"));
        }
        if response.status != SubBatchStatus::Ok as i32 {
            // BUSY, or any status this consumer predates: transient
            // backpressure, not a fault. Fence in order (the ordered stream
            // cannot retry one sub-batch in place) but as retriable, so the
            // work re-routes without marking the worker unhealthy.
            warn!(
                worker = %self.worker_url,
                seq = response.seq,
                status = response.status,
                "Worker signalled busy — fencing lane as retriable"
            );
            return Err(self.fence_with(true, None, ledger, queue, "worker busy"));
        }
        let Some(entry) = ledger
            .iter_mut()
            .find(|e| e.seq == response.seq && e.acked.is_none())
        else {
            warn!(worker = %self.worker_url, seq = response.seq, "Ack for unknown seq — fencing lane");
            return Err(self.fence(None, ledger, queue, "unknown ack seq"));
        };
        entry.acked = Some(response.accepted);
        counter!(
            "ingestion_consumer_transport_requests_total",
            "worker" => self.worker_url.clone(),
            "status" => "ok"
        )
        .increment(1);
        // Resolve only the acked prefix: a later ack waits for every earlier
        // seq, so a failure ahead of it still fences it instead of letting it
        // release its keys first.
        while ledger.front().is_some_and(|e| e.acked.is_some()) {
            let entry = ledger.pop_front().expect("front is present");
            let accepted = entry.acked.expect("front is acked");
            let _ = entry.item.reply.send(Ok(accepted));
        }
        gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
            .set(ledger.len() as f64);
        Ok(())
    }

    /// Resolve everything outstanding as failed, **in enqueue order**: the
    /// un-acked ledger first, then anything still queued (which was enqueued
    /// after everything in the ledger). Order matters because the callers'
    /// `defer_failed` stashes groups by batch sequence — resolving in order
    /// keeps every fenced key's groups stashed oldest-first, so the retry
    /// (oldest first) is the same request that failed.
    fn fence(
        &self,
        pending_first: Option<LaneItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
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
        pending_first: Option<LaneItem>,
        ledger: &mut VecDeque<LedgerEntry>,
        queue: &mut mpsc::UnboundedReceiver<LaneItem>,
        reason: &'static str,
    ) -> StreamEnd {
        let mut fence = Fence::new(retriable, reason);
        for entry in ledger.drain(..) {
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
        gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
            .set(0.0);
        StreamEnd::Failed(fence)
    }
}

/// A fence in progress. Every fenced send carries a [`FenceGuard`]; until all
/// of them are dropped the lane fails each new arrival too, so a send
/// enqueued before the fenced messages are stashed cannot ride the next
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

    fn fail(&mut self, item: LaneItem) {
        let error = if self.retriable {
            TransportError::LaneBusy(self.reason)
        } else {
            TransportError::LaneFailed(self.reason)
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
    async fn settle(mut self, queue: &mut mpsc::UnboundedReceiver<LaneItem>) -> usize {
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
    /// keeps fencing until those callers have stashed their messages.
    Failed(Fence),
    /// The stream ended cleanly with nothing outstanding.
    Idle,
}

fn to_proto_message(message: &SerializedKafkaMessage) -> KafkaMessage {
    KafkaMessage {
        topic: message.topic.clone(),
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

/// Process-unique sender id, matching the HTTP transport's semantics.
fn make_consumer_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}
