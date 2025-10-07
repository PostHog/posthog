use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::{EmbeddingModel, EmbeddingRecord, EmbeddingRequest};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tiktoken_rs::CoreBPE;
use tracing::error;

use crate::app_context::AppContext;

pub mod app_context;
pub mod config;
pub mod metric_consts;

pub async fn handle_batch(
    requests: Vec<EmbeddingRequest>,
    _offsets: &[Offset],
    context: Arc<AppContext>,
) -> Result<Vec<EmbeddingRecord>> {
    let mut handles = vec![];
    let client = Client::new();
    let api_key = context.config.openai_api_key.clone();
    for request in requests {
        for model in &request.models {
            handles.push(generate_embedding(
                client.clone(),
                api_key.clone(),
                model.clone(),
                request.clone(),
            ));
        }
    }
    let results = futures::future::join_all(handles).await;
    results.into_iter().collect()
}

#[derive(Serialize)]
struct OpenAIEmbeddingRequest {
    input: String,
    model: String,
}

#[derive(Deserialize)]
struct OpenAIEmbeddingResponse {
    data: Vec<EmbeddingData>,
}

#[derive(Deserialize)]
struct EmbeddingData {
    embedding: Vec<f64>,
}

pub async fn generate_embedding(
    client: Client,
    api_key: String,
    model: EmbeddingModel,
    request: EmbeddingRequest,
) -> Result<EmbeddingRecord> {
    // TODO - once we have a larger model zoo, we'll need to select this more carefully
    let encoder = tiktoken_rs::cl100k_base()?;

    // Generate the text to actually send to OpenAI
    // TODO - as above, a larger model zoo will require more careful selection of the dimensionality
    let text = generate_embedding_text(&request, &encoder, 8192)?;

    // Call OpenAI API to generate embeddings
    let api_request = OpenAIEmbeddingRequest {
        input: text,
        model: model.name().to_string(),
    };

    let response = client
        .post("https://api.openai.com/v1/embeddings")
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .json(&api_request)
        .send()
        .await?;

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

    let response_body: OpenAIEmbeddingResponse = match response.json().await {
        Ok(parsed) => parsed,
        Err(err) => {
            error!("Failed to parse OpenAI response: {}", err);
            return Err(anyhow::anyhow!("Failed to generate embeddings"));
        }
    };

    let embedding = response_body
        .data
        .first()
        .ok_or_else(|| anyhow::anyhow!("No embedding data returned from OpenAI"))?
        .embedding
        .clone();

    Ok(EmbeddingRecord {
        team_id: request.team_id,
        product: request.product.clone(),
        document_type: request.document_type.clone(),
        model_name: model,
        rendering: request.rendering.to_string(),
        document_id: request.document_id.to_string(),
        timestamp: request.timestamp,
        embedding,
    })
}

fn generate_embedding_text(
    request: &EmbeddingRequest,
    encoder: &CoreBPE,
    max_tokens: usize,
) -> Result<String> {
    let tokens = encoder
        .encode_with_special_tokens(&request.content)
        .into_iter()
        .take(max_tokens)
        .collect();
    encoder.decode(tokens)
}
