use std::time::Duration;

use metrics::{counter, histogram};
use tracing::{error, info, warn};

use crate::types::{IngestBatchRequest, IngestBatchResponse, SerializedKafkaMessage};

/// Sends batches to Node.js worker processes over HTTP.
///
/// Uses reqwest with connection pooling (one pool per worker URL).
/// Retries on 5xx/timeout with exponential backoff.
pub struct HttpTransport {
    client: reqwest::Client,
    max_retries: u32,
    api_secret: Option<String>,
}

impl HttpTransport {
    pub fn new(timeout: Duration, max_retries: u32, api_secret: Option<String>) -> Self {
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .pool_max_idle_per_host(4)
            .build()
            .expect("failed to create HTTP client");

        Self {
            client,
            max_retries,
            api_secret,
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
                    counter!("ingestion_consumer_transport_requests_total", "worker" => worker_url.to_string(), "status" => "error")
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

    #[error("Worker returned HTTP {0}: {1}")]
    HttpStatus(u16, String),

    #[error("Worker returned error: {0}")]
    WorkerError(String),

    #[error("All retries exhausted")]
    RetriesExhausted,
}

impl TransportError {
    /// 4xx errors are non-transient and should not be retried.
    pub fn is_retriable(&self) -> bool {
        match self {
            TransportError::HttpStatus(status, _) => *status >= 500,
            TransportError::Http(_) => true,
            TransportError::WorkerError(_) => true,
            TransportError::RetriesExhausted => false,
        }
    }
}
