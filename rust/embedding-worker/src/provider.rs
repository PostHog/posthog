use std::{future::Future, sync::Arc, time::Duration};

use anyhow::{Context, Result};
use common_types::embedding::{ApiLimits, EmbeddingModel};
use metrics::counter;
use rand::Rng;
use reqwest::{Client, Response, StatusCode};
use tracing::warn;

use crate::{
    construct_request,
    metrics_utils::{RequestLabels, REQUESTS_SENT, RESPONSES_RECEIVED},
    rate_limits::{retry_after, RateLimits},
};

const MAX_ATTEMPTS: usize = 4;
const REQUEST_DEADLINE: Duration = Duration::from_secs(120);

pub struct EmbeddingClient {
    client: Client,
    api_key: String,
    limits: RateLimits,
}

impl EmbeddingClient {
    pub fn new(client: Client, api_key: String, limits: ApiLimits) -> Result<Self> {
        Ok(Self {
            client,
            api_key,
            limits: RateLimits::new(limits)?,
        })
    }

    pub async fn generate(
        &self,
        text: &str,
        model: EmbeddingModel,
        tokens: usize,
        labels: &RequestLabels,
    ) -> Result<Vec<f64>> {
        self.execute_with_retry(model, tokens, labels, || {
            self.client.execute(construct_request(
                text,
                model,
                &self.api_key,
                self.client.clone(),
            ))
        })
        .await
    }

    async fn execute_with_retry<F, Fut>(
        &self,
        model: EmbeddingModel,
        tokens: usize,
        labels: &RequestLabels,
        mut send: F,
    ) -> Result<Vec<f64>>
    where
        F: FnMut() -> Fut,
        Fut: Future<Output = reqwest::Result<Response>>,
    {
        let request_labels: Vec<_> = labels
            .render()
            .iter()
            .map(|(key, value)| {
                (
                    Arc::<str>::from(key.as_str()),
                    Arc::<str>::from(value.as_str()),
                )
            })
            .collect();
        tokio::time::timeout(REQUEST_DEADLINE, async {
            for attempt in 0..MAX_ATTEMPTS {
                self.limits.acquire(model, tokens).await;
                counter!(REQUESTS_SENT, &request_labels).increment(1);

                let fallback = Duration::from_secs(2_u64.pow(attempt as u32 + 1));
                let jitter = Duration::from_millis(rand::thread_rng().gen_range(0..=250));
                let (failure, delay, throttled) = match send().await {
                    Ok(response) => {
                        let status = response.status();
                        let mut response_labels = request_labels.clone();
                        response_labels
                            .push((Arc::from("status_code"), Arc::from(status.as_str())));
                        counter!(RESPONSES_RECEIVED, &response_labels).increment(1);

                        let throttled = status == StatusCode::TOO_MANY_REQUESTS;
                        let delay = retry_after(response.headers()).unwrap_or(fallback) + jitter;
                        self.limits
                            .observe(model, response.headers(), throttled.then_some(delay))
                            .await;

                        if status.is_success() {
                            return model
                                .extract_embedding_from_response_body(&response.json().await?)
                                .context("Failed to extract embedding");
                        }
                        let request_id = response
                            .headers()
                            .get("x-request-id")
                            .and_then(|value| value.to_str().ok())
                            .unwrap_or("unavailable");
                        let failure = anyhow::anyhow!(
                            "Embedding provider returned HTTP {status} (request_id: {request_id})"
                        );
                        if !throttled && !status.is_server_error() {
                            return Err(failure);
                        }
                        (failure, delay, throttled)
                    }
                    Err(error) => (anyhow::Error::from(error), fallback + jitter, false),
                };

                if attempt + 1 == MAX_ATTEMPTS {
                    return Err(failure);
                }
                warn!(
                    error = %failure,
                    retry_delay_ms = delay.as_millis() as u64,
                    attempt = attempt + 1,
                    "Retrying embedding request"
                );
                if !throttled {
                    tokio::time::sleep(delay).await;
                }
            }
            unreachable!("The last attempt returns its result")
        })
        .await
        .context("Embedding request exceeded its retry deadline")?
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::Cell, future::ready};

    use tokio::time::Instant;

    use super::*;

    fn client(requests_per_minute: usize) -> EmbeddingClient {
        EmbeddingClient::new(
            Client::new(),
            "test-key".into(),
            ApiLimits {
                requests_per_minute,
                tokens_per_minute: 60_000,
            },
        )
        .unwrap()
    }

    fn response(status: u16, retry_after: Option<&str>) -> Response {
        let mut builder = http::Response::builder().status(status);
        if let Some(delay) = retry_after {
            builder = builder.header("retry-after", delay);
        }
        builder
            .body(r#"{"data":[{"embedding":[0.25]}]}"#)
            .unwrap()
            .into()
    }

    #[tokio::test(start_paused = true)]
    async fn retries_transient_statuses_with_server_delay_and_stops_on_terminal_errors() {
        for (statuses, success) in [
            (vec![429, 200], true),
            (vec![503, 200], true),
            (vec![429, 503, 200], true),
            (vec![429, 429, 429, 429], false),
            (vec![404], false),
        ] {
            let client = client(600);
            let calls = Cell::new(0);
            let start = Instant::now();
            let result = client
                .execute_with_retry(
                    EmbeddingModel::default(),
                    1,
                    &RequestLabels::default(),
                    || {
                        let call = calls.get();
                        calls.set(call + 1);
                        if call > 0 {
                            assert!(start.elapsed() >= Duration::from_secs(3 * call as u64));
                        }
                        ready(Ok(response(statuses[call], Some("3"))))
                    },
                )
                .await;
            assert_eq!(result.is_ok(), success, "{statuses:?}");
            if success {
                assert_eq!(result.unwrap(), vec![0.25]);
            }
            assert_eq!(calls.get(), statuses.len(), "{statuses:?}");
        }
    }

    #[tokio::test(start_paused = true)]
    async fn retry_attempts_consume_local_capacity() {
        for transport_error in [false, true] {
            let client = client(6);
            let calls = Cell::new(0);
            let start = Instant::now();
            client
                .execute_with_retry(
                    EmbeddingModel::default(),
                    1,
                    &RequestLabels::default(),
                    || {
                        let call = calls.get() + 1;
                        calls.set(call);
                        assert!(start.elapsed() >= Duration::from_secs(10 * call));
                        if call == 1 && transport_error {
                            return ready(Err(Client::new()
                                .get("invalid-url")
                                .build()
                                .unwrap_err()));
                        }
                        ready(Ok(response(
                            if call == 1 { 503 } else { 200 },
                            Some("0.01"),
                        )))
                    },
                )
                .await
                .unwrap();
            assert_eq!(calls.get(), 2);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn successful_requests_are_not_repeated_while_a_peer_retries() {
        let client = client(600);
        let successful_calls = Cell::new(0);
        let throttled_calls = Cell::new(0);
        let labels = RequestLabels::default();
        let successful = client.execute_with_retry(EmbeddingModel::default(), 1, &labels, || {
            successful_calls.set(successful_calls.get() + 1);
            ready(Ok(response(200, None)))
        });
        let throttled = client.execute_with_retry(EmbeddingModel::default(), 1, &labels, || {
            let call = throttled_calls.get();
            throttled_calls.set(call + 1);
            ready(Ok(response(if call == 0 { 429 } else { 200 }, Some("2"))))
        });
        let (first, second) = tokio::join!(successful, throttled);
        assert!(first.is_ok());
        assert!(second.is_ok());
        assert_eq!(successful_calls.get(), 1);
        assert_eq!(throttled_calls.get(), 2);
    }

    #[tokio::test(start_paused = true)]
    async fn long_retry_after_is_bounded_without_sending_early() {
        let client = client(600);
        let calls = Cell::new(0);
        let start = Instant::now();
        let error = client
            .execute_with_retry(
                EmbeddingModel::default(),
                1,
                &RequestLabels::default(),
                || {
                    calls.set(calls.get() + 1);
                    ready(Ok(response(429, Some("300"))))
                },
            )
            .await
            .unwrap_err();
        assert_eq!(calls.get(), 1);
        assert!(start.elapsed() >= REQUEST_DEADLINE);
        assert!(error.to_string().contains("retry deadline"));
    }
}
