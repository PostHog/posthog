//! Ordered streaming transport: one `WorkerIngest` lane per worker.
//!
//! Each lane owns a bidirectional gRPC stream to its worker and drains an
//! ordered queue: enqueue order is send order is the worker's feed order,
//! which is the per-key ordering guarantee concurrent HTTP requests cannot
//! give. `begin_send` enqueues synchronously — call it where send order is
//! decided (the consumer loop, right after assignment) — and hands back a
//! [`PendingLaneSend`] the caller awaits like an HTTP response.
//!
//! **Failure fences the whole lane.** A nack, stream break, or connect
//! failure resolves every queued and un-acked item, in enqueue order, with a
//! [`SendError`] carrying the messages back — the callers' existing
//! `defer_failed` path then stashes them, and the dispatcher's outstanding
//! counts hold all newer work for those keys until the failed groups are
//! retried (oldest first) and acked. Nothing for a fenced key can leapfrog
//! the failure, because everything for it was either in the ledger or the
//! queue, and both fail together in order.
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
    ingest_stream_request, IngestStreamRequest, KafkaMessage, StreamHello, SubBatch, SubBatchStatus,
};
use metrics::{counter, gauge};
use tokio::sync::{mpsc, oneshot};
use tokio_stream::wrappers::UnboundedReceiverStream;
use tracing::{error, info, warn};

use crate::transport::{SendError, TransportError};
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
    task: tokio::task::JoinHandle<()>,
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
            probe_client: reqwest::Client::new(),
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
            worker_url: worker_url.to_string(),
            grpc_url: grpc_url(worker_url, self.grpc_port),
            consumer_id: self.consumer_id.clone(),
            max_unacked: self.max_unacked,
            ack_timeout: self.ack_timeout,
            assignment_epoch: Arc::clone(&self.assignment_epoch),
        };
        let task = tokio::spawn(async move { runner.run(rx).await });
        Lane { tx, task }
    }

    /// Tear down a departed worker's lane. The reaper only removes workers
    /// with no in-flight work, so the queue and ledger are empty; anything
    /// racing in resolves as failed and re-routes via the deferral path.
    pub fn remove_worker(&self, worker_url: &str) {
        if let Some((_, lane)) = self.lanes.remove(worker_url) {
            lane.task.abort();
        }
    }

    /// Check if a worker is ready by probing its HTTP health endpoint.
    pub async fn check_ready(&self, worker_url: &str) -> bool {
        let url = format!("{worker_url}/_ready");
        match self.probe_client.get(&url).send().await {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        }
    }

    /// Wait until all workers are ready, polling with backoff. Mirrors the
    /// HTTP transport (readiness is an HTTP concern on both transports).
    pub async fn wait_for_workers_ready(
        &self,
        worker_urls: &[String],
        shutdown: &lifecycle::Handle,
    ) -> anyhow::Result<()> {
        let poll_interval = Duration::from_secs(2);
        loop {
            let mut all_ready = true;
            for url in worker_urls {
                if !self.check_ready(url).await {
                    warn!(worker = %url, "Worker not ready");
                    all_ready = false;
                }
            }
            if all_ready {
                info!(workers = worker_urls.len(), "All workers ready");
                return Ok(());
            }
            tokio::select! {
                _ = shutdown.shutdown_recv() => {
                    anyhow::bail!("Shutdown received while waiting for workers");
                }
                _ = tokio::time::sleep(poll_interval) => {}
            }
        }
    }
}

/// One un-acked sub-batch on the stream.
struct LedgerEntry {
    seq: u64,
    item: LaneItem,
}

struct LaneRunner {
    worker_url: String,
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
                StreamEnd::Failed(fenced) => {
                    counter!(
                        "ingestion_consumer_lane_teardowns_total",
                        "worker" => self.worker_url.clone(),
                    )
                    .increment(1);
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

        // The inner connect_timeout bounds TCP only; the outer bound covers
        // everything else in connection setup (e.g. an h2 handshake that
        // never completes because the far side is not actually h2).
        let channel = match tonic::transport::Endpoint::from_shared(self.grpc_url.clone())
            .map(|endpoint| endpoint.connect_timeout(Duration::from_secs(5)))
        {
            Ok(endpoint) => {
                match tokio::time::timeout(self.ack_timeout, endpoint.connect()).await {
                    Ok(Ok(channel)) => channel,
                    Ok(Err(err)) => {
                        warn!(
                            worker = %self.worker_url,
                            grpc_url = %self.grpc_url,
                            error = %err,
                            "Lane connect failed"
                        );
                        return self.fence(
                            pending_first.take(),
                            &mut ledger,
                            queue,
                            "connect failed",
                        );
                    }
                    Err(_) => {
                        warn!(
                            worker = %self.worker_url,
                            grpc_url = %self.grpc_url,
                            timeout_ms = self.ack_timeout.as_millis() as u64,
                            "Lane connect timed out"
                        );
                        return self.fence(
                            pending_first.take(),
                            &mut ledger,
                            queue,
                            "connect timeout",
                        );
                    }
                }
            }
            Err(err) => {
                error!(worker = %self.worker_url, grpc_url = %self.grpc_url, error = %err, "Invalid lane address");
                return self.fence(pending_first.take(), &mut ledger, queue, "invalid address");
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
            return self.fence(pending_first.take(), &mut ledger, queue, "stream closed");
        }

        // Stream-open resolves only when the worker's response headers (its
        // greeting) arrive; bound it so a worker that never greets fences
        // instead of deadlocking the lane — the failure mode that wedged
        // production before the greeting existed.
        let mut acks = match tokio::time::timeout(
            self.ack_timeout,
            client.ingest_stream(UnboundedReceiverStream::new(out_rx)),
        )
        .await
        {
            Ok(Ok(response)) => response.into_inner(),
            Err(_) => {
                warn!(
                    worker = %self.worker_url,
                    grpc_url = %self.grpc_url,
                    timeout_ms = self.ack_timeout.as_millis() as u64,
                    "Lane stream open timed out — no greeting from the worker"
                );
                return self.fence(
                    pending_first.take(),
                    &mut ledger,
                    queue,
                    "stream open timeout",
                );
            }
            Ok(Err(status)) => {
                warn!(worker = %self.worker_url, grpc_url = %self.grpc_url, status = %status, "Lane stream open failed");
                return self.fence(
                    pending_first.take(),
                    &mut ledger,
                    queue,
                    "stream open failed",
                );
            }
        };

        let mut next_seq = 1u64;
        gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
            .set(0.0);
        // Ack-progress deadline: pushed forward on every ack, and re-armed
        // when the ledger goes from empty to non-empty (a quiet lane must not
        // inherit a stale deadline).
        let mut ack_deadline = tokio::time::Instant::now() + self.ack_timeout;

        loop {
            // Send the held first item, then pull more only while the ledger
            // has room — the worker-aligned concurrency cap.
            while ledger.len() < self.max_unacked {
                let item = match pending_first.take() {
                    Some(item) => Some(item),
                    None => match queue.try_recv() {
                        Ok(item) => Some(item),
                        Err(mpsc::error::TryRecvError::Empty) => None,
                        Err(mpsc::error::TryRecvError::Disconnected) => {
                            return if ledger.is_empty() {
                                StreamEnd::QueueClosed
                            } else {
                                // Resolve the tail before exiting.
                                self.fence(None, &mut ledger, queue, "queue closed")
                            };
                        }
                    },
                };
                let Some(item) = item else { break };
                let seq = next_seq;
                next_seq += 1;
                let request = IngestStreamRequest {
                    msg: Some(ingest_stream_request::Msg::SubBatch(SubBatch {
                        seq,
                        batch_id: item.batch_id.clone(),
                        messages: item.messages.iter().map(to_proto_message).collect(),
                        replay: item.replay,
                        assignment_epoch: self.assignment_epoch.load(Ordering::Relaxed),
                    })),
                };
                if out_tx.send(request).is_err() {
                    ledger.push_back(LedgerEntry { seq, item });
                    return self.fence(None, &mut ledger, queue, "stream closed mid-send");
                }
                if ledger.is_empty() {
                    ack_deadline = tokio::time::Instant::now() + self.ack_timeout;
                }
                ledger.push_back(LedgerEntry { seq, item });
                gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
                    .set(ledger.len() as f64);
            }

            // Wait for an ack, or for new work when the ledger has room. The
            // ack-progress watchdog bounds how long un-acked work may sit with
            // no acks at all: a worker that stops acking (saturated by other
            // consumers, wedged, half-dead network) must become a fence — and
            // so a defer-and-reroute — rather than a silent forever-wait, the
            // way an HTTP timeout would have surfaced it.
            let ack = if ledger.is_empty() {
                match queue.recv().await {
                    Some(item) => {
                        pending_first = Some(item);
                        continue;
                    }
                    None => return StreamEnd::QueueClosed,
                }
            } else {
                let watchdog = tokio::time::sleep_until(ack_deadline);
                if ledger.len() < self.max_unacked {
                    tokio::select! {
                        ack = acks.message() => Some(ack),
                        _ = watchdog => {
                            warn!(
                                worker = %self.worker_url,
                                unacked = ledger.len(),
                                timeout_ms = self.ack_timeout.as_millis() as u64,
                                "No ack progress within the watchdog window — fencing lane"
                            );
                            return self.fence(pending_first.take(), &mut ledger, queue, "ack progress timeout");
                        }
                        item = queue.recv() => {
                            match item {
                                Some(item) => {
                                    pending_first = Some(item);
                                    continue;
                                }
                                None => {
                                    return self.fence(None, &mut ledger, queue, "queue closed");
                                }
                            }
                        }
                    }
                } else {
                    tokio::select! {
                        ack = acks.message() => Some(ack),
                        _ = watchdog => {
                            warn!(
                                worker = %self.worker_url,
                                unacked = ledger.len(),
                                timeout_ms = self.ack_timeout.as_millis() as u64,
                                "No ack progress within the watchdog window — fencing lane"
                            );
                            return self.fence(pending_first.take(), &mut ledger, queue, "ack progress timeout");
                        }
                    }
                }
            };

            match ack {
                Some(Ok(Some(response))) => {
                    // Seq 0 is the worker's greeting (and any future
                    // keepalive): it exists to flush response headers, not to
                    // resolve work — ignore it.
                    if response.seq == 0 {
                        continue;
                    }
                    if response.status != SubBatchStatus::Ok as i32 {
                        warn!(
                            worker = %self.worker_url,
                            seq = response.seq,
                            error = %response.error,
                            "Worker nacked sub-batch — fencing lane"
                        );
                        return self.fence(None, &mut ledger, queue, "sub-batch nacked");
                    }
                    let Some(position) = ledger.iter().position(|e| e.seq == response.seq) else {
                        warn!(worker = %self.worker_url, seq = response.seq, "Ack for unknown seq — fencing lane");
                        return self.fence(None, &mut ledger, queue, "unknown ack seq");
                    };
                    let entry = ledger.remove(position).expect("position in bounds");
                    counter!(
                        "ingestion_consumer_transport_requests_total",
                        "worker" => self.worker_url.clone(),
                        "status" => "ok"
                    )
                    .increment(1);
                    gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
                        .set(ledger.len() as f64);
                    let _ = entry.item.reply.send(Ok(response.accepted));
                    ack_deadline = tokio::time::Instant::now() + self.ack_timeout;
                }
                Some(Ok(None)) => {
                    return if ledger.is_empty() && pending_first.is_none() {
                        StreamEnd::Idle
                    } else {
                        self.fence(pending_first.take(), &mut ledger, queue, "stream ended")
                    };
                }
                Some(Err(status)) => {
                    warn!(worker = %self.worker_url, status = %status, "Lane stream failed");
                    return self.fence(pending_first.take(), &mut ledger, queue, "stream error");
                }
                None => unreachable!("ack future always yields a value"),
            }
        }
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
        let mut fenced = 0usize;
        let fail = |item: LaneItem| {
            let _ = item.reply.send(Err(SendError {
                error: TransportError::LaneFailed(reason),
                messages: item.messages,
            }));
        };
        for entry in ledger.drain(..) {
            fail(entry.item);
            fenced += 1;
        }
        if let Some(item) = pending_first {
            fail(item);
            fenced += 1;
        }
        while let Ok(item) = queue.try_recv() {
            fail(item);
            fenced += 1;
        }
        counter!(
            "ingestion_consumer_transport_requests_total",
            "worker" => self.worker_url.clone(),
            "status" => "error"
        )
        .increment(1);
        gauge!("ingestion_consumer_lane_ledger_depth", "worker" => self.worker_url.clone())
            .set(0.0);
        StreamEnd::Failed(fenced)
    }
}

enum StreamEnd {
    /// The transport dropped the queue sender — worker removed or shutdown.
    QueueClosed,
    /// The stream broke; this many outstanding sub-batches were fenced.
    Failed(usize),
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
