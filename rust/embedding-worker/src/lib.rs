use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::embedding::{
    EmbeddingModel, EmbeddingRequest, EmbeddingResponse, EmbeddingResult, ModelResult,
};
use metrics::counter;
use reqwest::{Client, Method, Request, RequestBuilder};
use tracing::error;

use crate::{
    app_context::AppContext,
    metrics_utils::{
        RequestLabels, DROPPED_REQUESTS, EMBEDDINGS_GENERATED, EMBEDDING_FAILED,
        EMBEDDING_REQUEST_TIME, EMBEDDING_TOTAL_TIME, EMBEDDING_TOTAL_TOKENS, MESSAGES_RECEIVED,
        MESSAGE_TRUNCATED,
    },
    organization::apply_ai_opt_in,
};

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
    // Generate the text to actually send to OpenAI
    let (text, token_count) = generate_embedding_text(content, &model, labels)?;

    let api_req = construct_request(
        &text,
        model,
        &context.config.openai_api_key,
        context.client.clone(),
    );

    context.respect_rate_limits(model, token_count).await;

    let request_time = common_metrics::timing_guard(EMBEDDING_REQUEST_TIME, labels.render());
    let response = context.client.execute(api_req).await?; // Unhandled - network errors etc

    // TODO - implement 429 backoff and retry
    if !response.status().is_success() {
        error!(
            "Failed to generate embeddings, got non-200 from openai: {}",
            response.status()
        );

        if let Ok(error_message) = response.text().await {
            error!("Error message from OpenAI: {}", error_message);
        }

        return Err(anyhow::anyhow!("Failed to generate embeddings"));
    }

    context.update_rate_limits(model, &response).await;

    let embedding = model
        .extract_embedding_from_response_body(&response.json().await?)
        .ok_or_else(|| anyhow::anyhow!("Failed to extract embedding"))?;

    request_time.label("outcome", "success").fin();
    total_time.label("outcome", "success").fin();

    counter!(EMBEDDING_TOTAL_TOKENS, labels.render()).increment(token_count as u64);

    Ok((embedding, token_count))
}

// This is here, rather than on the embedding model, to avoid taking a dep on tiktoken in common/types. We
// can reconsider it later if we want
pub fn generate_embedding_text(
    content: &str,
    model: &EmbeddingModel,
    labels: &RequestLabels,
) -> Result<(String, usize)> {
    let (text, count) = match model {
        EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
            let encoder = tiktoken_rs::cl100k_base()?;
            let mut tokens: Vec<_> = encoder
                .encode_with_special_tokens(content)
                .into_iter()
                .take(model.model_input_window())
                .collect();
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

    Ok((text, count))
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
        assert!(content.starts_with(&text));
    }
}
