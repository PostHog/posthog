use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use metrics::{counter, gauge, histogram};
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
/// Retries on 5xx/timeout with exponential backoff.
///
/// Per-worker `Semaphore`s cap how many concurrent batches we can have in
/// flight to each worker URL. The capacity must match the worker's own
/// `BatchingPipeline.concurrentBatches` setting (controlled by
/// `INGESTION_WORKER_CONCURRENT_BATCHES` on both sides). When all permits
/// are held, `send_batch` waits — this is the natural backpressure that
/// replaces retry-on-503. A 503 escaping to the transport indicates a
/// contract violation (mis-configured limits or a Rust-side timeout
/// leaving a worker still processing) and is treated as non-retriable.
pub struct HttpTransport {
    client: reqwest::Client,
    max_retries: u32,
    api_secret: Option<String>,
    worker_semaphores: HashMap<String, Arc<Semaphore>>,
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

        let worker_semaphores = worker_urls
            .iter()
            .map(|url| {
                (
                    url.clone(),
                    Arc::new(Semaphore::new(worker_concurrent_batches)),
                )
            })
            .collect();

        Self {
            client,
            max_retries,
            api_secret,
            worker_semaphores,
        }
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
    ) -> Result<u32, TransportError> {
        let message_count = messages.len();
        let request = IngestBatchRequest {
            batch_id: batch_id.to_string(),
            messages,
        };

        let url = format!("{worker_url}/ingest");

        let semaphore = self
            .worker_semaphores
            .get(worker_url)
            .ok_or_else(|| TransportError::UnknownWorker(worker_url.to_string()))?
            .clone();

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
        for attempt in 0..=self.max_retries {
            if attempt > 0 {
                let backoff = Duration::from_millis(100 * 2u64.pow(attempt - 1));
                tokio::time::sleep(backoff).await;
                counter!("ingestion_consumer_transport_retries_total", "worker" => worker_url.to_string())
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
                    let status_label = if matches!(err, TransportError::WorkerBusy(_)) {
                        "busy"
                    } else {
                        "error"
                    };
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
                        return Err(err);
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
        Err(err)
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

        // 503 means the worker is at concurrent batch capacity. The previous
        // batch is still being processed — surface as a distinct error so the
        // caller can apply a longer backoff instead of hammering with 100ms
        // retries (which all bounce off the same in-flight batch).
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

    #[error("Unknown worker URL: {0}")]
    UnknownWorker(String),

    #[error("All retries exhausted")]
    RetriesExhausted,
}

impl TransportError {
    /// 4xx errors are non-transient and should not be retried.
    /// `WorkerBusy` (HTTP 503) is also non-retriable: the consumer's per-worker
    /// semaphore is supposed to prevent it from ever firing, so it indicates a
    /// contract violation rather than a transient condition — retrying just
    /// hammers an already-overloaded worker.
    pub fn is_retriable(&self) -> bool {
        match self {
            TransportError::HttpStatus(status, _) => *status >= 500,
            TransportError::Http(_) => true,
            TransportError::WorkerBusy(_) => false,
            TransportError::WorkerError(_) => true,
            TransportError::UnknownWorker(_) => false,
            TransportError::RetriesExhausted => false,
        }
    }
}
