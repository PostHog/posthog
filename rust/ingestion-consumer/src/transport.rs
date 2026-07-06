use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use metrics::{counter, gauge, histogram};
use rand::Rng;
use tokio::sync::Semaphore;
use tracing::{error, info, warn};

use crate::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};

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
}

impl HttpTransport {
    pub fn new(
        timeout: Duration,
        max_retries: u32,
        api_secret: Option<String>,
        worker_urls: &[String],
        worker_concurrent_batches: usize,
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
        }
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
        let url = format!("{worker_url}/_ready");
        match self.client.get(&url).send().await {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        }
    }

    /// Wait until all workers are ready, polling with backoff.
    /// Returns an error if shutdown is signalled before all workers are ready.
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

    /// Send a sub-batch to a worker. Returns the number of accepted messages.
    ///
    /// Acquires a permit from the worker's `Semaphore` before sending. If
    /// `worker_concurrent_batches` permits are already held, the call waits
    /// here — that's the natural backpressure. The permit is released on
    /// drop, covering all return paths (success, retriable error, retries
    /// exhausted, non-retriable error).
    pub async fn send_batch(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
    ) -> Result<u32, SendError> {
        let message_count = messages.len();
        let request = IngestBatchRequest {
            batch_id: batch_id.to_string(),
            messages,
        };

        let url = format!("{worker_url}/ingest");

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

        let mut last_err = None;
        // Whether the previous attempt failed with a 503. A busy worker gets a
        // longer, jittered backoff so callers don't retry it in lockstep.
        let mut last_was_busy = false;
        for attempt in 0..=self.max_retries {
            if attempt > 0 {
                tokio::time::sleep(retry_backoff(attempt, last_was_busy)).await;
                counter!(
                    "ingestion_consumer_transport_retries_total",
                    "worker" => worker_url.to_string(),
                    "reason" => if last_was_busy { "busy" } else { "error" },
                )
                .increment(1);
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
                        return Ok(response.accepted);
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
                    if !err.is_retriable() {
                        return Err(SendError {
                            error: err,
                            messages: request.messages,
                        });
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
        Err(SendError {
            error: err,
            messages: request.messages,
        })
    }

    async fn do_send(
        &self,
        url: &str,
        request: &IngestBatchRequest,
    ) -> Result<IngestBatchResponse, TransportError> {
        let mut req_builder = self.client.post(url).json(request);
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

        if status.is_client_error() || status.is_server_error() {
            let body = response.text().await.unwrap_or_default();
            return Err(TransportError::HttpStatus(status.as_u16(), body));
        }

        let parsed: IngestBatchResponse = response.json().await?;
        Ok(parsed)
    }
}

/// Failure from [`HttpTransport::send_batch`], carrying back the batch's
/// messages so the caller can defer/replay them (the worker may have died
/// mid-send and the messages were never accepted).
#[derive(Debug)]
pub struct SendError {
    pub error: TransportError,
    pub messages: Vec<SerializedKafkaMessage>,
}

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),

    #[error("Worker busy (HTTP 503): {0}")]
    WorkerBusy(String),

    #[error("Worker returned HTTP {0}: {1}")]
    HttpStatus(u16, String),

    #[error("Worker returned error: {0}")]
    WorkerError(String),

    #[error("All retries exhausted")]
    RetriesExhausted,
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
            TransportError::WorkerBusy(_) => true,
            TransportError::WorkerError(_) => true,
            TransportError::RetriesExhausted => false,
        }
    }
}

/// Backoff before a retry. A busy worker (503) gets a longer base plus jitter so
/// that callers backing off the same worker don't retry in lockstep; other
/// retriable errors use a short exponential backoff. `attempt` is 1-based (the
/// first retry passes 1).
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
    fn test_client_errors_are_not_retriable() {
        assert!(!TransportError::HttpStatus(400, "bad".into()).is_retriable());
        assert!(!TransportError::RetriesExhausted.is_retriable());
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
