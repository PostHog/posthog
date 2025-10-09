use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::{
    embedding::{EmbeddingModel, EmbeddingRecord, EmbeddingRequest},
    format::format_ch_datetime,
};
use metrics::counter;
use reqwest::{Client, Method, Request, RequestBuilder};
use tracing::error;

use crate::{
    app_context::AppContext,
    metric_consts::{DROPPED_REQUESTS, EMBEDDINGS_GENERATED, MESSAGES_RECEIVED},
    organization::apply_ai_opt_in,
};

pub mod app_context;
pub mod config;
pub mod metric_consts;
pub mod organization;

pub async fn handle_batch(
    requests: Vec<EmbeddingRequest>,
    _offsets: &[Offset], // TODO - tie errors to offsets
    context: Arc<AppContext>,
) -> Result<Vec<EmbeddingRecord>> {
    let mut handles = vec![];

    counter!(MESSAGES_RECEIVED).increment(requests.len() as u64);

    for request in requests {
        let Some(request) = apply_ai_opt_in(&context, request).await? else {
            counter!(DROPPED_REQUESTS, &[("cause", "ai_opt_in")]).increment(1);
            continue;
        };
        for model in &request.models {
            handles.push(generate_embedding(context.clone(), *model, request.clone()));
        }
    }
    let results = futures::future::join_all(handles).await;
    results.into_iter().collect()
}

pub async fn generate_embedding(
    context: Arc<AppContext>,
    model: EmbeddingModel,
    request: EmbeddingRequest,
) -> Result<EmbeddingRecord> {
    // Generate the text to actually send to OpenAI
    let (text, token_count) = generate_embedding_text(&request.content, &model)?;

    let api_req = construct_request(
        &text,
        model,
        &context.config.openai_api_key,
        context.client.clone(),
    );

    context.respect_rate_limits(model, token_count).await;

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

    counter!(EMBEDDINGS_GENERATED, &[("model", model.name())]).increment(1);

    Ok(EmbeddingRecord {
        team_id: request.team_id,
        product: request.product.clone(),
        document_type: request.document_type.clone(),
        model_name: model,
        rendering: request.rendering.to_string(),
        document_id: request.document_id.to_string(),
        timestamp: format_ch_datetime(request.timestamp),
        embedding,
    })
}

// This is here, rather than on the embedding model, to avoid taking a dep on tiktoken in common/types. We
// can reconsider it later if we want
fn generate_embedding_text(content: &str, model: &EmbeddingModel) -> Result<(String, usize)> {
    match model {
        EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
            let encoder = tiktoken_rs::cl100k_base()?;
            let tokens: Vec<_> = encoder
                .encode_with_special_tokens(content)
                .into_iter()
                .take(model.model_input_window())
                .collect();
            let token_count = tokens.len();
            let text = encoder.decode(tokens)?;
            Ok((text, token_count))
        }
    }
}

fn construct_request(
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
        .json(&model.construct_request_body(content))
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json");

    // This expect is fine, because we have total control over everything in the
    // request, except the string of input content, which will serialize correctly.
    req.build().expect("we manage to build the request")
}
