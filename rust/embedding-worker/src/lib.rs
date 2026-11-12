use std::time::Duration;
use std::{borrow::Cow, sync::Arc};

use anyhow::Result;
use chrono::{DateTime, Utc};
use common_kafka::kafka_consumer::Offset;
use common_types::embedding::{
    EmbeddingModel, EmbeddingRequest, EmbeddingResponse, EmbeddingResult, ModelResult,
};
use metrics::counter;
use rand::Rng;
use reqwest::{header::RETRY_AFTER, Client, Response, StatusCode};
use tracing::{error, warn};

use crate::{
    app_context::AppContext,
    metrics_utils::{
        RequestLabels, DROPPED_REQUESTS, EMBEDDINGS_GENERATED, EMBEDDING_FAILED,
        EMBEDDING_REQUEST_TIME, EMBEDDING_TOTAL_TIME, EMBEDDING_TOTAL_TOKENS, MESSAGES_RECEIVED,
        MESSAGE_TRUNCATED, RATE_LIMITED_RETRIES, REQUESTS_SENT, RESPONSES_RECEIVED,
    },
    organization::apply_ai_opt_in,
    route::EmbeddingRoute,
};

static CL100K_ENCODER: std::sync::LazyLock<tiktoken_rs::CoreBPE> = std::sync::LazyLock::new(|| {
    tiktoken_rs::cl100k_base().expect("Failed to initialize cl100k_base encoder")
});

const MAX_RETRY_ATTEMPTS: usize = 4; // 1 initial + 3 retries
const RETRY_BASE_SECS: u64 = 2;
const RETRY_JITTER_RANGE: std::ops::RangeInclusive<i64> = -1000..=1000;
const RETRY_AFTER_MAX: Duration = Duration::from_secs(10);

pub mod ad_hoc;
pub mod app_context;
pub mod config;
pub mod metrics_utils;
pub mod organization;
pub mod recently_seen;
pub mod route;

pub async fn handle_batch(
    requests: Vec<EmbeddingRequest>,
    _offsets: &[Offset], // TODO - tie errors to offsets
    context: Arc<AppContext>,
) -> Result<Vec<EmbeddingResponse>> {
    let mut handles = vec![];

    for request in requests.into_iter() {
        let team_id = request.team_id;
        let labels = RequestLabels::from(&request);
        let Some(request) = apply_ai_opt_in(&context, request, team_id).await? else {
            counter!(
                DROPPED_REQUESTS,
                labels.and([("cause", "ai_opt_in")]).render()
            )
            .increment(1);
            continue;
        };

        let ctx = context.clone();
        handles.push(async move {
            let mut results = vec![];
            for model in &request.models {
                let (model, embedding) =
                    handle_single(ctx.clone(), *model, request.clone()).await?;
                results.push(ModelResult {
                    model,
                    outcome: EmbeddingResult::Success { embedding },
                });
            }
            Ok::<_, anyhow::Error>(EmbeddingResponse { request, results })
        });
    }

    let results: Result<Vec<_>> = futures::future::join_all(handles)
        .await
        .into_iter()
        .collect();

    results
}

pub async fn handle_single(
    context: Arc<AppContext>,
    model: EmbeddingModel,
    request: EmbeddingRequest,
) -> Result<(EmbeddingModel, Vec<f64>)> {
    let labels = RequestLabels::from(&request)
        .and_model(model)
        .and([("from", "kafka")]);

    counter!(MESSAGES_RECEIVED, labels.render()).increment(1);
    let (embedding, _) = match generate_embedding(context, model, &request.content, &labels).await {
        Ok(r) => r,
        Err(e) => {
            counter!(EMBEDDING_FAILED, labels.render()).increment(1);
            error!("Failed to handle request: {request:?}");
            return Err(e);
        }
    };

    counter!(EMBEDDINGS_GENERATED, labels.render()).increment(1);

    Ok((model, embedding))
}

// Exponential backoff (base 2) with jitter, in milliseconds, for retry `attempt`.
fn retry_backoff_ms(attempt: usize) -> u64 {
    let base_ms = RETRY_BASE_SECS.pow(attempt as u32 + 1) * 1000;
    let jitter_ms = rand::thread_rng().gen_range(RETRY_JITTER_RANGE);
    (base_ms as i64 + jitter_ms).max(0) as u64
}

pub async fn generate_embedding(
    context: Arc<AppContext>,
    model: EmbeddingModel,
    content: &str,
    labels: &RequestLabels,
) -> Result<(Vec<f64>, usize)> {
    let total_time = common_metrics::timing_guard(EMBEDDING_TOTAL_TIME, labels.render());
    // Generate the text to actually send to the embedding provider
    let (text, token_count) = generate_embedding_text(content, &model, labels)?;

    context.respect_rate_limits(model, token_count).await;

    let request_time = common_metrics::timing_guard(EMBEDDING_REQUEST_TIME, labels.render());

    let response = send_embedding_request(
        &context.client,
        &context.route,
        context.retry_budget,
        &text,
        model,
        labels,
    )
    .await?;

    context.update_rate_limits(model, &response).await;

    let embedding = model
        .extract_embedding_from_response_body(&response.json().await?)
        .ok_or_else(|| anyhow::anyhow!("Failed to extract embedding"))?;

    request_time.label("outcome", "success").fin();
    total_time.label("outcome", "success").fin();

    counter!(EMBEDDING_TOTAL_TOKENS, labels.render()).increment(token_count as u64);

    Ok((embedding, token_count))
}

async fn send_embedding_request(
    client: &Client,
    route: &EmbeddingRoute,
    budget: RetryBudget,
    text: &str,
    model: EmbeddingModel,
    labels: &RequestLabels,
) -> Result<Response> {
    let started = tokio::time::Instant::now();
    let mut last_status = None;
    let mut last_error_body = None;
    let mut last_transport_error = None;

    for attempt in 0..MAX_RETRY_ATTEMPTS {
        let api_req = route.construct_request(text, model, labels, client);

        counter!(REQUESTS_SENT, labels.render()).increment(1);
        let wait = match client.execute(api_req).await {
            // Transport errors (timeouts, connection resets, etc.) are transient.
            // Retry them with backoff like a 5xx rather than aborting the whole
            // batch, which would panic and restart the worker.
            Err(e) => {
                warn!("Request to embedding provider failed ({e})");
                last_status = None;
                last_transport_error = Some(e);
                Duration::from_millis(retry_backoff_ms(attempt))
            }
            Ok(response) => {
                let status = response.status();
                let response_labels = labels
                    .clone()
                    .and([("status_code", status.as_u16().to_string())]);
                counter!(RESPONSES_RECEIVED, response_labels.render()).increment(1);

                if status.is_success() {
                    return Ok(response);
                }

                let retry_after = response
                    .headers()
                    .get(RETRY_AFTER)
                    .and_then(|value| value.to_str().ok())
                    .and_then(|value| retry_after_delay(value, Utc::now()));
                last_status = Some(status);
                last_error_body = response.text().await.ok();

                if !is_retryable(status) {
                    break;
                }
                warn!("Got {status} from embedding provider");
                retry_after.unwrap_or_else(|| Duration::from_millis(retry_backoff_ms(attempt)))
            }
        };

        if attempt + 1 < MAX_RETRY_ATTEMPTS {
            if !budget.allows(started.elapsed(), wait) {
                warn!(
                    "Not retrying in {}ms, it would pass the {}ms retry deadline",
                    wait.as_millis(),
                    budget.deadline.as_millis()
                );
                break;
            }
            if last_status == Some(StatusCode::TOO_MANY_REQUESTS) {
                counter!(RATE_LIMITED_RETRIES, labels.render()).increment(1);
            }
            warn!(
                "Retrying in {}ms (attempt {}/{})",
                wait.as_millis(),
                attempt + 1,
                MAX_RETRY_ATTEMPTS - 1
            );
            tokio::time::sleep(wait).await;
        }
    }

    // All attempts exhausted or non-retryable error
    match last_status {
        Some(status) => {
            error!(
                "Failed to generate embeddings, got {} from {}",
                status,
                model.provider()
            );
            if let Some(error_message) = last_error_body {
                error!("Error message from {}: {}", model.provider(), error_message);
            }
        }
        None => {
            error!(
                "Failed to generate embeddings, no response from {}: {}",
                model.provider(),
                last_transport_error
                    .map(|e| e.to_string())
                    .unwrap_or_else(|| "unknown error".to_string())
            );
        }
    }

    Err(anyhow::anyhow!("Failed to generate embeddings"))
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RetryBudget {
    pub request_timeout: Duration,
    pub deadline: Duration,
}

impl RetryBudget {
    fn allows(&self, elapsed: Duration, wait: Duration) -> bool {
        elapsed + wait + self.request_timeout <= self.deadline
    }
}

fn is_retryable(status: StatusCode) -> bool {
    status.is_server_error() || status == StatusCode::TOO_MANY_REQUESTS
}

fn retry_after_delay(value: &str, now: DateTime<Utc>) -> Option<Duration> {
    let delay = match value.trim().parse::<u64>() {
        Ok(seconds) => Duration::from_secs(seconds),
        Err(_) => (DateTime::parse_from_rfc2822(value.trim())
            .ok()?
            .with_timezone(&Utc)
            - now)
            .to_std()
            .unwrap_or(Duration::ZERO),
    };
    Some(delay.min(RETRY_AFTER_MAX))
}

// This is here, rather than on the embedding model, to avoid taking a dep on tiktoken in common/types. We
// can reconsider it later if we want
pub fn generate_embedding_text<'a>(
    content: &'a str,
    model: &EmbeddingModel,
    labels: &RequestLabels,
) -> Result<(Cow<'a, str>, usize)> {
    let content = model.escape_input(content);
    let (text, count) = match model {
        EmbeddingModel::OpenAITextEmbeddingSmall
        | EmbeddingModel::OpenAITextEmbeddingLarge
        | EmbeddingModel::OpenAITextEmbeddingSmall256 => {
            let encoder = &*CL100K_ENCODER;
            let mut tokens: Vec<_> = encoder
                .encode_with_special_tokens(&content)
                .into_iter()
                .take(model.model_input_window())
                .collect();

            if tokens.len() < model.model_input_window() {
                return Ok((content, tokens.len()));
            }

            // Truncation can split a multi-byte character's token sequence,
            // producing bytes that aren't valid UTF-8 on decode. Drop trailing
            // tokens until we land on a clean boundary.
            let text = loop {
                match encoder.decode(tokens.clone()) {
                    Ok(text) => break text,
                    Err(_) => {
                        tokens.pop();
                    }
                }
            };
            let token_count = tokens.len();
            (text, token_count)
        }
    };

    if text.len() < content.len() {
        counter!(MESSAGE_TRUNCATED, labels.render()).increment(1);
    }

    Ok((Cow::Owned(text), count))
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::sync::Mutex;

    use axum::{extract::State, http::HeaderMap, routing::post, Router};
    use chrono::TimeZone;

    use super::*;
    use crate::route::RouteSettings;

    type Script = Arc<Mutex<VecDeque<(StatusCode, Option<&'static str>)>>>;

    async fn scripted_response(State(script): State<Script>) -> (StatusCode, HeaderMap) {
        let (status, retry_after) = script.lock().unwrap().pop_front().unwrap();
        let mut headers = HeaderMap::new();
        if let Some(retry_after) = retry_after {
            headers.insert(RETRY_AFTER, retry_after.parse().unwrap());
        }
        (status, headers)
    }

    #[tokio::test(start_paused = true)]
    async fn test_send_embedding_request_retries() {
        let rate_limited = (StatusCode::TOO_MANY_REQUESTS, Some("7"));
        let cases = [
            (
                vec![rate_limited, (StatusCode::OK, None)],
                Ok(StatusCode::OK),
                2,
                Duration::from_secs(7)..=Duration::from_secs(7),
            ),
            (
                vec![
                    (StatusCode::TOO_MANY_REQUESTS, None),
                    (StatusCode::OK, None),
                ],
                Ok(StatusCode::OK),
                2,
                Duration::from_secs(1)..=Duration::from_secs(3),
            ),
            (
                vec![rate_limited; MAX_RETRY_ATTEMPTS],
                Err(()),
                MAX_RETRY_ATTEMPTS,
                Duration::from_secs(21)..=Duration::from_secs(21),
            ),
            (
                vec![(StatusCode::BAD_REQUEST, Some("7"))],
                Err(()),
                1,
                Duration::ZERO..=Duration::ZERO,
            ),
            (
                vec![(StatusCode::SERVICE_UNAVAILABLE, Some("10")); MAX_RETRY_ATTEMPTS],
                Err(()),
                3,
                Duration::from_secs(20)..=Duration::from_secs(20),
            ),
        ];
        let budget = RetryBudget {
            request_timeout: Duration::from_secs(10),
            deadline: Duration::from_secs(35),
        };

        for (responses, expected, requests_sent, elapsed_range) in cases {
            let request_count = responses.len();
            let script: Script = Arc::new(Mutex::new(responses.into()));
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let address = listener.local_addr().unwrap();
            let app = Router::new()
                .route("/v1/embeddings", post(scripted_response))
                .with_state(script.clone());
            tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });

            let base_url = format!("http://{address}/v1");
            let route = EmbeddingRoute::resolve(RouteSettings {
                openai_api_key: None,
                ai_gateway_url: Some(&base_url),
                ai_gateway_api_key: Some("phs_test"),
            })
            .unwrap();
            let client = Client::builder().pool_max_idle_per_host(0).build().unwrap();

            let started = tokio::time::Instant::now();
            let outcome = send_embedding_request(
                &client,
                &route,
                budget,
                "hello",
                EmbeddingModel::OpenAITextEmbeddingSmall,
                &RequestLabels::default(),
            )
            .await
            .map(|response| response.status())
            .map_err(|_| ());
            let elapsed = started.elapsed();

            assert_eq!(outcome, expected, "responses: {request_count}");
            assert!(
                elapsed_range.contains(&elapsed),
                "elapsed {elapsed:?} outside {elapsed_range:?}"
            );
            assert_eq!(
                request_count - script.lock().unwrap().len(),
                requests_sent,
                "responses: {request_count}"
            );
        }
    }

    #[test]
    fn test_retry_after_delay() {
        let now = Utc.with_ymd_and_hms(2026, 11, 12, 8, 0, 0).unwrap();
        let cases = [
            ("5", Some(Duration::from_secs(5))),
            (" 0 ", Some(Duration::ZERO)),
            ("120", Some(RETRY_AFTER_MAX)),
            (
                "Thu, 12 Nov 2026 08:00:03 GMT",
                Some(Duration::from_secs(3)),
            ),
            ("Thu, 12 Nov 2026 07:59:00 GMT", Some(Duration::ZERO)),
            ("Thu, 12 Nov 2026 09:00:00 GMT", Some(RETRY_AFTER_MAX)),
            ("-1", None),
            ("soon", None),
        ];

        for (value, expected) in cases {
            assert_eq!(retry_after_delay(value, now), expected, "value: {value:?}");
        }
    }

    #[test]
    fn test_generate_embedding_text_truncation_at_multibyte_boundary() {
        // Emojis like 🔥 encode to 3 tokens in cl100k_base. When content exceeds
        // the 8192 token window, truncation can split an emoji's token sequence,
        // producing bytes that aren't valid UTF-8 on decode.
        let padding = "word ".repeat(8180);
        let content = format!("{padding}{}", "🔥".repeat(100));
        let model = EmbeddingModel::default();

        let (text, _count) =
            generate_embedding_text(&content, &model, &RequestLabels::default()).unwrap();
        assert!(content.starts_with(&*text));
    }
}
