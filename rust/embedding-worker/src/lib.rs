use std::time::Duration;
use std::{borrow::Cow, sync::Arc};

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::embedding::{
    EmbeddingModel, EmbeddingRequest, EmbeddingResponse, EmbeddingResult, ModelResult,
};
use metrics::counter;
use rand::Rng;
use reqwest::{Client, Method, Request, RequestBuilder};
use tracing::{error, warn};

use crate::{
    app_context::AppContext,
    metrics_utils::{
        RequestLabels, DROPPED_REQUESTS, EMBEDDINGS_GENERATED, EMBEDDING_FAILED,
        EMBEDDING_REQUEST_TIME, EMBEDDING_TOTAL_TIME, EMBEDDING_TOTAL_TOKENS, MESSAGES_RECEIVED,
        MESSAGE_TRUNCATED, REQUESTS_SENT, RESPONSES_RECEIVED,
    },
    organization::apply_ai_opt_in,
};

const MAX_RETRY_ATTEMPTS: usize = 4; // 1 initial + 3 retries
const RETRY_BASE_SECS: u64 = 2;
const RETRY_JITTER_RANGE: std::ops::RangeInclusive<i64> = -1000..=1000;

pub mod ad_hoc;
pub mod app_context;
pub mod config;
pub mod metrics_utils;
pub mod organization;

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

    let mut last_status = None;
    let mut last_error_body = None;

    for attempt in 0..MAX_RETRY_ATTEMPTS {
        let api_req = construct_request(
            &text,
            model,
            &context.config.openai_api_key,
            context.client.clone(),
        );

        counter!(REQUESTS_SENT, labels.render()).increment(1);
        let response = context.client.execute(api_req).await?; // Unhandled - network errors etc

        let status = response.status();
        let response_labels = labels
            .clone()
            .and([("status_code", status.as_u16().to_string())]);
        counter!(RESPONSES_RECEIVED, response_labels.render()).increment(1);

        if status.is_success() {
            context.update_rate_limits(model, &response).await;

            let embedding = model
                .extract_embedding_from_response_body(&response.json().await?)
                .ok_or_else(|| anyhow::anyhow!("Failed to extract embedding"))?;

            request_time.label("outcome", "success").fin();
            total_time.label("outcome", "success").fin();

            counter!(EMBEDDING_TOTAL_TOKENS, labels.render()).increment(token_count as u64);

            return Ok((embedding, token_count));
        }

        last_status = Some(status);
        last_error_body = response.text().await.ok();

        // Only retry on 5xx - for stuff like 429's, we want to crash and restart as a backoff
        if !status.is_server_error() {
            break;
        }

        if attempt < MAX_RETRY_ATTEMPTS - 1 {
            let base_ms = RETRY_BASE_SECS.pow(attempt as u32 + 1) * 1000;
            let jitter_ms = rand::thread_rng().gen_range(RETRY_JITTER_RANGE);
            let sleep_ms = (base_ms as i64 + jitter_ms).max(0) as u64;
            warn!(
                "Got {} from embedding provider, retrying in {}ms (attempt {}/{})",
                status,
                sleep_ms,
                attempt + 1,
                MAX_RETRY_ATTEMPTS - 1
            );
            tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
        }
    }

    // All attempts exhausted or non-retryable error
    let status = last_status.unwrap();
    error!(
        "Failed to generate embeddings, got {} from {}",
        status,
        model.provider()
    );
    if let Some(error_message) = last_error_body {
        error!("Error message from {}: {}", model.provider(), error_message);
    }

    Err(anyhow::anyhow!("Failed to generate embeddings"))
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
        EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
            let encoder = tiktoken_rs::cl100k_base()?;
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

pub fn construct_request(
    content: &str,
    model: EmbeddingModel,
    api_key: &str,
    client: Client,
) -> Request {
    let req = Request::new(
        Method::POST,
        model
            .model_url()
            .parse()
            .expect("The models enum only produces valid urls"),
    );

    let req = RequestBuilder::from_parts(client, req)
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .json(&model.construct_request_body(content));

    // This expect is fine, because we have total control over everything in the
    // request, except the string of input content, which will serialize correctly.
    req.build().expect("we manage to build the request")
}

#[cfg(test)]
mod tests {
    use super::*;

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
