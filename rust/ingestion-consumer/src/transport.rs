use std::collections::VecDeque;
use std::io::Write;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use flate2::write::GzEncoder;
use flate2::Compression;
use metrics::{counter, gauge, histogram};
use rand::Rng;
use tokio::sync::Semaphore;
use tracing::{error, warn};

use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder};
use crate::readiness;
use crate::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};

/// Default cap on the serialized JSON size of one /ingest request body. The
/// worker's HTTP body limit is 20 MB; half that leaves headroom for the
/// per-message size estimate (which ignores JSON string escaping).
pub const DEFAULT_MAX_BODY_BYTES: usize = 10 * 1024 * 1024;

/// RAII guard that tracks the number of batches currently in flight to a
/// worker. Increments the gauge on creation and decrements on drop, so every
/// `send_batch` return path (success, error, retries exhausted, panic unwind)
/// is covered — mirroring the lifetime of the worker's `Semaphore` permit.
struct InFlightGuard {
    worker_url: String,
}

impl InFlightGuard {
    fn new(worker_url: &str) -> Self {
        gauge!("ingestion_consumer_transport_concurrent_batches", "worker" => worker_url.to_string())
            .increment(1.0);
        Self {
            worker_url: worker_url.to_string(),
        }
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        gauge!("ingestion_consumer_transport_concurrent_batches", "worker" => self.worker_url.clone())
            .decrement(1.0);
    }
}

/// Sends batches to Node.js worker processes over HTTP.
///
/// Uses reqwest with connection pooling (one pool per worker URL).
/// Retries on 5xx/timeout/503 with exponential backoff.
///
/// Per-worker `Semaphore`s are a soft cap on how many concurrent batches we
/// keep in flight to each worker URL — ideally aligned with the worker's
/// `BatchingPipeline.concurrentBatches` (`INGESTION_WORKER_CONCURRENT_BATCHES`)
/// so the happy path proactively backpressures (waits for a permit) before the
/// worker fills up. The cap need not match the worker exactly: if the worker
/// rejects a batch with 503, the transport treats it as transient backpressure
/// and retries with a longer, jittered backoff. This keeps the consumer correct
/// when a worker is shared by other callers and its true capacity isn't a
/// number this consumer can reserve in advance.
///
/// Semaphores are created lazily on first send to a worker and pruned via
/// [`remove_worker`](HttpTransport::remove_worker), so the worker pool can
/// change at runtime (workers joining/leaving via discovery).
pub struct HttpTransport {
    client: reqwest::Client,
    max_retries: u32,
    api_secret: Option<String>,
    worker_semaphores: DashMap<String, Arc<Semaphore>>,
    worker_concurrent_batches: usize,
    /// Gzip request bodies (`Content-Encoding: gzip`). Batch bodies are JSON
    /// wrapping JSON-text Kafka messages, so they compress several-fold; the
    /// worker's Express body parser inflates transparently.
    compression_enabled: bool,
    /// Process-unique sender id stamped on every request, so the worker-side
    /// feed-order sentinel can rebaseline when the consumer restarts.
    consumer_id: String,
    /// Cap on the serialized JSON size of one request body. Sub-batches whose
    /// estimated size exceeds it are split into multiple sequential requests;
    /// a request the worker still rejects with 413 is halved and resent.
    max_body_bytes: usize,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
}

impl HttpTransport {
    pub fn new(
        timeout: Duration,
        max_retries: u32,
        api_secret: Option<String>,
        worker_urls: &[String],
        worker_concurrent_batches: usize,
        compression_enabled: bool,
    ) -> Self {
        assert!(
            worker_concurrent_batches > 0,
            "worker_concurrent_batches must be > 0"
        );

        let client = reqwest::Client::builder()
            .timeout(timeout)
            .pool_max_idle_per_host(4)
            .build()
            .expect("failed to create HTTP client");

        // Pre-seed semaphores for the initial worker set; new workers get one
        // lazily on first send (see `semaphore_for`).
        let worker_semaphores = DashMap::new();
        for url in worker_urls {
            worker_semaphores.insert(
                url.clone(),
                Arc::new(Semaphore::new(worker_concurrent_batches)),
            );
        }

        Self {
            client,
            max_retries,
            api_secret,
            worker_semaphores,
            worker_concurrent_batches,
            compression_enabled,
            consumer_id: make_consumer_id(),
            max_body_bytes: DEFAULT_MAX_BODY_BYTES,
            debug_recorder: None,
        }
    }

    /// Inject the debug UI recorder. Call before the transport is shared.
    pub fn set_debug_recorder(&mut self, recorder: Arc<DebugRecorder>) {
        self.debug_recorder = Some(recorder);
    }

    /// Override the request body size cap. Call before the transport is shared.
    pub fn set_max_body_bytes(&mut self, bytes: usize) {
        assert!(bytes > 0, "max_body_bytes must be > 0");
        self.max_body_bytes = bytes;
    }

    /// Get the worker's concurrency semaphore, creating it on first use so the
    /// transport serves workers added at runtime without explicit registration.
    fn semaphore_for(&self, worker_url: &str) -> Arc<Semaphore> {
        if let Some(sem) = self.worker_semaphores.get(worker_url) {
            return sem.clone();
        }
        self.worker_semaphores
            .entry(worker_url.to_string())
            .or_insert_with(|| Arc::new(Semaphore::new(self.worker_concurrent_batches)))
            .clone()
    }

    /// Drop a worker's semaphore after it leaves the pool, so departed workers
    /// don't accumulate. In-flight sends already hold a cloned `Arc`, so their
    /// permits remain valid until they complete.
    pub fn remove_worker(&self, worker_url: &str) {
        self.worker_semaphores.remove(worker_url);
    }

    /// Check if a worker is ready by probing its health endpoint.
    pub async fn check_ready(&self, worker_url: &str) -> bool {
        readiness::check_ready(&self.client, worker_url).await
    }

    /// Wait until all workers are ready, polling with backoff.
    /// Returns an error if shutdown is signalled before all workers are ready.
    pub async fn wait_for_workers_ready(
        &self,
        worker_urls: &[String],
        shutdown: &lifecycle::Handle,
    ) -> anyhow::Result<()> {
        readiness::wait_for_workers_ready(&self.client, worker_urls, shutdown).await
    }

    /// Send a sub-batch to a worker. Returns the number of accepted messages.
    ///
    /// Acquires a permit from the worker's `Semaphore` before sending. If
    /// `worker_concurrent_batches` permits are already held, the call waits
    /// here — that's the natural backpressure. The permit is released on
    /// drop, covering all return paths (success, retriable error, retries
    /// exhausted, non-retriable error).
    ///
    /// A sub-batch whose estimated body size exceeds `max_body_bytes` is split
    /// into multiple sequential requests (order-preserving, under the same
    /// permit). A request the worker still rejects with 413 is halved and
    /// resent; a single message the worker rejects with 413 is a non-retriable
    /// failure. The result stays all-or-nothing: `Ok` only when every chunk was
    /// accepted, and on any failure the `SendError` carries back the full
    /// original message set — already-accepted chunks may then be re-sent
    /// later, which is ordinary at-least-once replay.
    ///
    /// `replay` marks a request that may repeat previously sent messages (a
    /// deferred-flush re-route); HTTP retries within this call are marked as
    /// replays automatically.
    pub async fn send_batch(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> Result<u32, SendError> {
        let semaphore = self.semaphore_for(worker_url);

        // Atomic "did we actually have to wait?" check. `available_permits`
        // followed by `acquire_owned` would race — a permit could be released
        // between the two (false positive) or stolen (false negative). Using
        // `try_acquire_owned` first gives an accurate backpressure counter.
        let _permit = match semaphore.clone().try_acquire_owned() {
            Ok(permit) => permit,
            Err(_) => {
                counter!(
                    "ingestion_consumer_transport_backpressure_waits_total",
                    "worker" => worker_url.to_string()
                )
                .increment(1);
                semaphore
                    .acquire_owned()
                    .await
                    .expect("worker semaphore must not be closed")
            }
        };

        // Now that the permit is held, this batch is genuinely in flight to the
        // worker. The guard decrements the gauge on every return path.
        let _in_flight = InFlightGuard::new(worker_url);

        let message_total = messages.len();
        let mut queue: VecDeque<Vec<SerializedKafkaMessage>> =
            split_by_size(messages, self.max_body_bytes).into();
        if queue.len() > 1 {
            counter!(
                "ingestion_consumer_transport_batch_splits_total",
                "reason" => "size_estimate"
            )
            .increment((queue.len() - 1) as u64);
            record_if(&self.debug_recorder, || DebugEventKind::SendSplit {
                worker: worker_url.to_string(),
                batch_id: batch_id.to_string(),
                reason: "size_estimate",
                chunks: queue.len(),
                messages: message_total,
            });
        }

        let mut sent: Vec<SerializedKafkaMessage> = Vec::new();
        let mut accepted_total = 0u32;
        while let Some(chunk) = queue.pop_front() {
            match self.send_chunk(worker_url, batch_id, chunk, replay).await {
                ChunkOutcome::Accepted { accepted, messages } => {
                    accepted_total += accepted;
                    sent.extend(messages);
                }
                ChunkOutcome::TooLarge { messages } if messages.len() > 1 => {
                    // The estimate undershot the worker's body limit — halve
                    // the chunk and resend both parts, front of the queue so
                    // message order is preserved.
                    counter!(
                        "ingestion_consumer_transport_batch_splits_total",
                        "reason" => "http_413"
                    )
                    .increment(1);
                    record_if(&self.debug_recorder, || DebugEventKind::SendSplit {
                        worker: worker_url.to_string(),
                        batch_id: batch_id.to_string(),
                        reason: "http_413",
                        chunks: 2,
                        messages: messages.len(),
                    });
                    let mut left = messages;
                    let right = left.split_off(left.len() / 2);
                    queue.push_front(right);
                    queue.push_front(left);
                }
                ChunkOutcome::TooLarge { messages } => {
                    // A single message the worker refuses can never succeed by
                    // splitting or retrying.
                    error!(
                        worker = %worker_url,
                        batch_id = %batch_id,
                        "Worker rejected a single message as too large"
                    );
                    return Err(SendError {
                        error: TransportError::PayloadTooLarge(String::new()),
                        messages: reassemble(sent, messages, queue),
                        fence_guard: None,
                    });
                }
                ChunkOutcome::Failed { error, messages } => {
                    return Err(SendError {
                        error,
                        messages: reassemble(sent, messages, queue),
                        fence_guard: None,
                    });
                }
            }
        }

        Ok(accepted_total)
    }

    /// Send one already-size-bounded chunk with the retry loop. Ownership of
    /// the messages travels through the outcome so the caller can split or
    /// re-defer them.
    async fn send_chunk(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> ChunkOutcome {
        let message_count = messages.len();
        let mut request = IngestBatchRequest {
            batch_id: batch_id.to_string(),
            messages,
            consumer_id: self.consumer_id.clone(),
            replay,
        };

        let url = format!("{worker_url}/ingest");

        let mut last_err = None;
        // Whether the previous attempt failed with a 503. A busy worker gets a
        // longer, jittered backoff so callers don't retry it in lockstep.
        let mut last_was_busy = false;
        for attempt in 0..=self.max_retries {
            if attempt > 0 {
                // A retried request may repeat messages the worker already
                // processed (e.g. a timeout after the worker finished) — mark it
                // so the worker-side sentinel counts repeats as replays.
                request.replay = true;
                tokio::time::sleep(retry_backoff(attempt, last_was_busy)).await;
                counter!(
                    "ingestion_consumer_transport_retries_total",
                    "worker" => worker_url.to_string(),
                    "reason" => if last_was_busy { "busy" } else { "error" },
                )
                .increment(1);
                record_if(&self.debug_recorder, || DebugEventKind::SendRetry {
                    worker: worker_url.to_string(),
                    batch_id: batch_id.to_string(),
                    attempt,
                    reason: if last_was_busy { "busy" } else { "error" },
                });
            }

            let start = std::time::Instant::now();
            match self.do_send(&url, &request).await {
                Ok(response) => {
                    let elapsed = start.elapsed();
                    histogram!("ingestion_consumer_transport_duration_seconds", "worker" => worker_url.to_string())
                        .record(elapsed.as_secs_f64());
                    counter!("ingestion_consumer_transport_requests_total", "worker" => worker_url.to_string(), "status" => "ok")
                        .increment(1);

                    if response.status == "ok" {
                        return ChunkOutcome::Accepted {
                            accepted: response.accepted,
                            messages: request.messages,
                        };
                    }

                    last_was_busy = false;
                    let err_msg = response.error.unwrap_or_default();
                    warn!(
                        worker = %worker_url,
                        batch_id = %batch_id,
                        attempt = attempt + 1,
                        error = %err_msg,
                        "Worker returned error status"
                    );
                    last_err = Some(TransportError::WorkerError(err_msg));
                }
                Err(err) => {
                    let elapsed = start.elapsed();
                    histogram!("ingestion_consumer_transport_duration_seconds", "worker" => worker_url.to_string())
                        .record(elapsed.as_secs_f64());
                    last_was_busy = matches!(err, TransportError::WorkerBusy(_));
                    let status_label = if last_was_busy { "busy" } else { "error" };
                    counter!("ingestion_consumer_transport_requests_total", "worker" => worker_url.to_string(), "status" => status_label)
                        .increment(1);

                    warn!(
                        worker = %worker_url,
                        batch_id = %batch_id,
                        attempt = attempt + 1,
                        messages = message_count,
                        error = %err,
                        "Failed to send batch to worker"
                    );
                    // 413 is deterministic for this chunk on every worker —
                    // hand it back for splitting instead of retrying verbatim.
                    if matches!(err, TransportError::PayloadTooLarge(_)) {
                        return ChunkOutcome::TooLarge {
                            messages: request.messages,
                        };
                    }
                    if !err.is_retriable() {
                        return ChunkOutcome::Failed {
                            error: err,
                            messages: request.messages,
                        };
                    }
                    last_err = Some(err);
                }
            }
        }

        let err = last_err.unwrap_or(TransportError::RetriesExhausted);
        error!(
            worker = %worker_url,
            batch_id = %batch_id,
            messages = message_count,
            max_retries = self.max_retries,
            "All retries exhausted"
        );
        counter!("ingestion_consumer_transport_exhausted_total", "worker" => worker_url.to_string())
            .increment(1);
        record_if(&self.debug_recorder, || DebugEventKind::SendExhausted {
            worker: worker_url.to_string(),
            batch_id: batch_id.to_string(),
            messages: message_count,
            error: err.to_string(),
        });
        ChunkOutcome::Failed {
            error: err,
            messages: request.messages,
        }
    }

    async fn do_send(
        &self,
        url: &str,
        request: &IngestBatchRequest,
    ) -> Result<IngestBatchResponse, TransportError> {
        // Serialized per attempt: the retry loop flips `request.replay`
        // between attempts, so the body can't be built once up front.
        let json = serde_json::to_vec(request)?;
        counter!("ingestion_consumer_transport_body_bytes_total", "encoding" => "raw")
            .increment(json.len() as u64);

        let mut req_builder = self
            .client
            .post(url)
            .header(reqwest::header::CONTENT_TYPE, "application/json");
        if self.compression_enabled {
            let body = gzip(&json);
            counter!("ingestion_consumer_transport_body_bytes_total", "encoding" => "gzip")
                .increment(body.len() as u64);
            req_builder = req_builder
                .header(reqwest::header::CONTENT_ENCODING, "gzip")
                .body(body);
        } else {
            req_builder = req_builder.body(json);
        }
        if let Some(secret) = &self.api_secret {
            req_builder = req_builder.header("X-Internal-Api-Secret", secret);
        }
        let response = req_builder.send().await?;
        let status = response.status();

        // 503 means the worker is at concurrent batch capacity. Surface it as a
        // distinct error so the retry loop applies the longer, jittered busy
        // backoff (rather than hammering with the short 5xx backoff).
        if status == reqwest::StatusCode::SERVICE_UNAVAILABLE {
            let body = response.text().await.unwrap_or_default();
            return Err(TransportError::WorkerBusy(body));
        }

        // 413 means the body exceeded the worker's HTTP body limit. Every
        // worker enforces the same limit, so retrying elsewhere can't succeed;
        // the caller splits the chunk instead.
        if status == reqwest::StatusCode::PAYLOAD_TOO_LARGE {
            let body = response.text().await.unwrap_or_default();
            return Err(TransportError::PayloadTooLarge(body));
        }

        if status.is_client_error() || status.is_server_error() {
            let body = response.text().await.unwrap_or_default();
            return Err(TransportError::HttpStatus(status.as_u16(), body));
        }

        let parsed: IngestBatchResponse = response.json().await?;
        Ok(parsed)
    }
}

/// Outcome of sending one size-bounded chunk of a sub-batch.
enum ChunkOutcome {
    Accepted {
        accepted: u32,
        messages: Vec<SerializedKafkaMessage>,
    },
    /// The worker rejected the body with 413 — split and resend, don't retry.
    TooLarge {
        messages: Vec<SerializedKafkaMessage>,
    },
    Failed {
        error: TransportError,
        messages: Vec<SerializedKafkaMessage>,
    },
}

/// Rebuild the sub-batch's full message list, in original order, from the
/// already-sent chunks, the failing chunk, and the not-yet-sent remainder —
/// `send_batch`'s failure contract hands the whole sub-batch back to the
/// caller for deferral.
fn reassemble(
    mut sent: Vec<SerializedKafkaMessage>,
    failed: Vec<SerializedKafkaMessage>,
    queue: VecDeque<Vec<SerializedKafkaMessage>>,
) -> Vec<SerializedKafkaMessage> {
    sent.extend(failed);
    for chunk in queue {
        sent.extend(chunk);
    }
    sent
}

/// Approximate serialized JSON size of one message within the batch body.
/// Field names and punctuation are a small constant; escaping of the embedded
/// JSON text is absorbed by the headroom between the split cap and the
/// worker's hard body limit (and by the 413 halving fallback).
fn approx_message_size(msg: &SerializedKafkaMessage) -> usize {
    const PER_MESSAGE_OVERHEAD: usize = 96;
    msg.topic.len()
        + msg.key.as_deref().map_or(0, str::len)
        + msg.value.as_deref().map_or(0, str::len)
        + msg
            .headers
            .iter()
            .map(|(k, v)| k.len() + v.len() + 8)
            .sum::<usize>()
        + PER_MESSAGE_OVERHEAD
}

/// Split a sub-batch into chunks whose estimated serialized size stays under
/// `max_body_bytes`, preserving message order. A single message estimated
/// above the cap gets its own chunk — it can't be split further.
pub(crate) fn split_by_size(
    messages: Vec<SerializedKafkaMessage>,
    max_body_bytes: usize,
) -> Vec<Vec<SerializedKafkaMessage>> {
    let mut chunks = Vec::new();
    let mut current = Vec::new();
    let mut current_size = 0usize;
    for msg in messages {
        let size = approx_message_size(&msg);
        if !current.is_empty() && current_size + size > max_body_bytes {
            chunks.push(std::mem::take(&mut current));
            current_size = 0;
        }
        current_size += size;
        current.push(msg);
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    chunks
}

/// Failure from [`HttpTransport::send_batch`], carrying back the batch's
/// messages so the caller can defer/replay them (the worker may have died
/// mid-send and the messages were never accepted).
#[derive(Debug)]
pub struct SendError {
    pub error: TransportError,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Set on a fenced worker stream send. Hold it until `messages` are stashed: the
    /// worker stream keeps fencing new arrivals until every guard from that fence is
    /// dropped, so nothing enqueued before the stash lands can reach the
    /// worker ahead of the fenced groups on the next stream.
    pub fence_guard: Option<FenceGuard>,
}

/// Tells a fencing worker stream that one fenced send's messages are stashed.
pub struct FenceGuard {
    /// One release per fenced send this guard stands for: a split sub-batch
    /// fenced across several chunks merges their guards into one.
    released: Vec<tokio::sync::mpsc::UnboundedSender<()>>,
}

impl FenceGuard {
    pub(crate) fn new(released: tokio::sync::mpsc::UnboundedSender<()>) -> Self {
        Self {
            released: vec![released],
        }
    }

    /// Fold `other` into this guard, so both release only when this one drops.
    pub(crate) fn merge(&mut self, mut other: FenceGuard) {
        self.released.append(&mut other.released);
    }
}

impl Drop for FenceGuard {
    fn drop(&mut self) {
        for released in &self.released {
            let _ = released.send(());
        }
    }
}

impl std::fmt::Debug for FenceGuard {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("FenceGuard")
    }
}

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),

    #[error("Failed to serialize request: {0}")]
    Serialize(#[from] serde_json::Error),

    #[error("Worker busy (HTTP 503): {0}")]
    WorkerBusy(String),

    #[error("Request body too large (HTTP 413): {0}")]
    PayloadTooLarge(String),

    #[error("Worker returned HTTP {0}: {1}")]
    HttpStatus(u16, String),

    #[error("Worker returned error: {0}")]
    WorkerError(String),

    #[error("All retries exhausted")]
    RetriesExhausted,

    #[error("Worker stream failed: {0}")]
    WorkerStreamFailed(&'static str),

    #[error("Worker stream busy: {0}")]
    WorkerStreamBusy(&'static str),

    #[error("Worker stream closed without resolving the send")]
    WorkerStreamClosed,
}

impl TransportError {
    /// 4xx errors are non-transient and should not be retried.
    /// `WorkerBusy` (HTTP 503) is retriable backpressure: a worker shared by
    /// other callers can be momentarily at capacity even when this consumer's
    /// soft semaphore cap would allow more, so we retry with a longer, jittered
    /// backoff instead of failing.
    pub fn is_retriable(&self) -> bool {
        match self {
            TransportError::HttpStatus(status, _) => *status >= 500,
            TransportError::Http(_) => true,
            TransportError::Serialize(_) => false,
            TransportError::WorkerBusy(_) => true,
            TransportError::PayloadTooLarge(_) => false,
            TransportError::WorkerError(_) => true,
            TransportError::RetriesExhausted => false,
            // Worker stream failures resolve through the deferral path, not the HTTP
            // retry loop — never retried in place.
            TransportError::WorkerStreamFailed(_) => false,
            // A busy worker stream is transient backpressure (like WorkerBusy), so the
            // fenced work re-routes as retriable rather than a worker fault.
            TransportError::WorkerStreamBusy(_) => true,
            TransportError::WorkerStreamClosed => false,
        }
    }

    /// Backpressure the worker signalled deliberately (503 or a busy worker stream).
    /// Distinct from `is_retriable`: connection errors and 5xx are retriable
    /// too, but they are worker faults and must count against passive health.
    pub fn is_backpressure(&self) -> bool {
        matches!(
            self,
            TransportError::WorkerBusy(_) | TransportError::WorkerStreamBusy(_)
        )
    }
}

/// Backoff before a retry. A busy worker (503) gets a longer base plus jitter so
/// that callers backing off the same worker don't retry in lockstep; other
/// retriable errors use a short exponential backoff. `attempt` is 1-based (the
/// first retry passes 1).
/// Process-unique sender id: workers use it to scope feed-order baselines to
/// one consumer incarnation.
fn make_consumer_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}

/// Gzip a serialized body. Level `fast` (1): the payload is JSON text that
/// already compresses several-fold at the lowest level, and this sits on the
/// per-batch send path where CPU spent compressing delays the batch.
fn gzip(bytes: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::with_capacity(bytes.len() / 4), Compression::fast());
    encoder
        .write_all(bytes)
        .expect("writing to a Vec cannot fail");
    encoder
        .finish()
        .expect("finishing a Vec-backed gzip stream cannot fail")
}

fn retry_backoff(attempt: u32, busy: bool) -> Duration {
    let exp = 2u64.saturating_pow(attempt.saturating_sub(1));
    if busy {
        let base = (250 * exp).min(5_000);
        let jitter = rand::thread_rng().gen_range(0..=base / 2);
        Duration::from_millis(base + jitter)
    } else {
        Duration::from_millis(100 * exp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_busy_is_retriable() {
        assert!(TransportError::WorkerBusy("at capacity".into()).is_retriable());
    }

    #[test]
    fn test_only_busy_errors_are_backpressure() {
        assert!(TransportError::WorkerBusy("at capacity".into()).is_backpressure());
        assert!(TransportError::WorkerStreamBusy("busy").is_backpressure());
        assert!(!TransportError::HttpStatus(500, "boom".into()).is_backpressure());
        assert!(!TransportError::WorkerError("boom".into()).is_backpressure());
        assert!(!TransportError::WorkerStreamFailed("nack").is_backpressure());
        assert!(!TransportError::RetriesExhausted.is_backpressure());
    }

    #[test]
    fn test_client_errors_are_not_retriable() {
        assert!(!TransportError::HttpStatus(400, "bad".into()).is_retriable());
        assert!(!TransportError::PayloadTooLarge("too big".into()).is_retriable());
        assert!(!TransportError::RetriesExhausted.is_retriable());
    }

    fn message_with_value(offset: i64, value_len: usize) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "t".to_string(),
            partition: 0,
            offset,
            timestamp: 0,
            key: None,
            value: Some("x".repeat(value_len)),
            headers: std::collections::HashMap::new(),
        }
    }

    #[test]
    fn test_split_by_size_respects_cap_and_preserves_order() {
        let messages: Vec<_> = (0..10).map(|i| message_with_value(i, 1000)).collect();
        // Each message estimates to ~1100 bytes, so a 2500-byte cap fits two.
        let chunks = split_by_size(messages, 2500);

        assert!(
            chunks.len() >= 5,
            "expected >= 5 chunks, got {}",
            chunks.len()
        );
        for chunk in &chunks {
            let size: usize = chunk.iter().map(approx_message_size).sum();
            assert!(size <= 2500, "chunk exceeds cap: {size}");
        }
        let offsets: Vec<i64> = chunks.iter().flatten().map(|m| m.offset).collect();
        assert_eq!(offsets, (0..10).collect::<Vec<_>>());
    }

    #[test]
    fn test_split_by_size_isolates_oversize_message() {
        let messages = vec![
            message_with_value(0, 10),
            message_with_value(1, 5000),
            message_with_value(2, 10),
        ];
        let chunks = split_by_size(messages, 1000);

        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[1].len(), 1);
        assert_eq!(chunks[1][0].offset, 1);
    }

    #[test]
    fn test_split_by_size_single_chunk_when_under_cap() {
        let messages: Vec<_> = (0..3).map(|i| message_with_value(i, 10)).collect();
        let chunks = split_by_size(messages, DEFAULT_MAX_BODY_BYTES);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].len(), 3);
    }

    #[test]
    fn test_server_errors_are_retriable() {
        assert!(TransportError::HttpStatus(500, "boom".into()).is_retriable());
    }

    #[test]
    fn test_busy_backoff_is_longer_than_error_backoff() {
        // Across attempts the busy backoff floor (base, no jitter) must exceed
        // the error backoff for the same attempt.
        for attempt in 1..=4 {
            let busy_min = 250 * 2u64.saturating_pow(attempt - 1);
            let err = retry_backoff(attempt, false);
            assert!(
                retry_backoff(attempt, true) >= Duration::from_millis(busy_min.min(5_000)),
                "busy backoff below floor at attempt {attempt}"
            );
            assert!(
                err < Duration::from_millis(busy_min.min(5_000)),
                "error backoff not shorter than busy at attempt {attempt}"
            );
        }
    }

    #[test]
    fn test_busy_backoff_is_capped() {
        // Even at a high attempt the busy base is capped at 5s; jitter adds up to
        // half the base, so the total stays at most 7.5s.
        assert!(retry_backoff(20, true) <= Duration::from_millis(7_500));
    }
}
