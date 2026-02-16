use std::time::Duration;

use async_trait::async_trait;
use tracing::{info, warn};

use crate::error::IngestionError;
use crate::types::{BatchRequest, BatchResponse, SerializedMessage};

#[async_trait]
pub trait IngestionTransport: Send + Sync {
    async fn send_batch(
        &self,
        target: &str,
        messages: Vec<SerializedMessage>,
    ) -> Result<(), IngestionError>;
}

pub struct HttpJsonTransport {
    client: reqwest::Client,
    max_retries: u32,
}

impl HttpJsonTransport {
    pub fn new(timeout: Duration, max_retries: u32) -> Self {
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .pool_max_idle_per_host(4)
            .build()
            .expect("failed to build HTTP client");

        Self {
            client,
            max_retries,
        }
    }
}

#[async_trait]
impl IngestionTransport for HttpJsonTransport {
    async fn send_batch(
        &self,
        target: &str,
        messages: Vec<SerializedMessage>,
    ) -> Result<(), IngestionError> {
        let url = format!("{target}/api/ingestion/batch");
        let request = BatchRequest { messages };
        let mut backoff = Duration::from_millis(100);
        let max_backoff = Duration::from_secs(30);

        for attempt in 0..=self.max_retries {
            let result = self.client.post(&url).json(&request).send().await;

            match result {
                Ok(response) => {
                    let status = response.status();

                    if status.is_success() {
                        let body: BatchResponse = response
                            .json()
                            .await
                            .map_err(|e| IngestionError::Transport {
                                target: target.to_string(),
                                source: e.into(),
                            })?;

                        if body.status == "ok" {
                            return Ok(());
                        }

                        return Err(IngestionError::Transport {
                            target: target.to_string(),
                            source: anyhow::anyhow!(
                                "server returned error: {}",
                                body.error.unwrap_or_default()
                            ),
                        });
                    }

                    // Retry on server errors and rate limiting
                    if should_retry(status.as_u16()) && attempt < self.max_retries {
                        warn!(
                            attempt,
                            status = status.as_u16(),
                            target,
                            "retryable HTTP error, backing off"
                        );
                        tokio::time::sleep(backoff).await;
                        backoff = (backoff * 2).min(max_backoff);
                        continue;
                    }

                    return Err(IngestionError::Transport {
                        target: target.to_string(),
                        source: anyhow::anyhow!("HTTP {status}"),
                    });
                }
                Err(e) => {
                    if attempt < self.max_retries {
                        warn!(
                            attempt,
                            error = %e,
                            target,
                            "connection error, retrying"
                        );
                        tokio::time::sleep(backoff).await;
                        backoff = (backoff * 2).min(max_backoff);
                        continue;
                    }

                    return Err(IngestionError::Transport {
                        target: target.to_string(),
                        source: e.into(),
                    });
                }
            }
        }

        info!(target, "all retries exhausted");
        Err(IngestionError::RetriesExhausted {
            target: target.to_string(),
        })
    }
}

fn should_retry(status: u16) -> bool {
    matches!(status, 429 | 502 | 503 | 504)
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;

    fn make_test_messages(count: usize) -> Vec<SerializedMessage> {
        (0..count)
            .map(|i| {
                SerializedMessage::from_kafka_message(
                    "test",
                    0,
                    i as i64,
                    None,
                    None,
                    Some(b"{}"),
                    vec![],
                )
            })
            .collect()
    }

    #[tokio::test]
    async fn test_successful_batch_send() {
        let server = MockServer::start();

        server.mock(|when, then| {
            when.method(POST).path("/api/ingestion/batch");
            then.status(200)
                .json_body(serde_json::json!({"status": "ok", "accepted": 2}));
        });

        let transport = HttpJsonTransport::new(Duration::from_secs(5), 3);
        let result = transport
            .send_batch(&server.base_url(), make_test_messages(2))
            .await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_retry_on_503() {
        let server = MockServer::start();

        let fail_mock = server.mock(|when, then| {
            when.method(POST).path("/api/ingestion/batch");
            then.status(503);
        });

        let transport = HttpJsonTransport::new(Duration::from_secs(5), 1);
        let result = transport
            .send_batch(&server.base_url(), make_test_messages(1))
            .await;

        // Should have retried once then failed
        assert!(result.is_err());
        fail_mock.assert_hits(2); // initial + 1 retry
    }

    #[tokio::test]
    async fn test_no_retry_on_400() {
        let server = MockServer::start();

        let mock = server.mock(|when, then| {
            when.method(POST).path("/api/ingestion/batch");
            then.status(400);
        });

        let transport = HttpJsonTransport::new(Duration::from_secs(5), 3);
        let result = transport
            .send_batch(&server.base_url(), make_test_messages(1))
            .await;

        assert!(result.is_err());
        mock.assert_hits(1); // no retries
    }

    #[tokio::test]
    async fn test_timeout_handling() {
        let server = MockServer::start();

        server.mock(|when, then| {
            when.method(POST).path("/api/ingestion/batch");
            then.status(200)
                .delay(Duration::from_secs(10))
                .json_body(serde_json::json!({"status": "ok"}));
        });

        let transport = HttpJsonTransport::new(Duration::from_millis(100), 0);
        let result = transport
            .send_batch(&server.base_url(), make_test_messages(1))
            .await;

        assert!(result.is_err());
    }
}
