use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::error_tracking::{EmbeddingModel, EmbeddingRecord, NewFingerprintEvent};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tiktoken_rs::CoreBPE;
use tracing::error;

use crate::app_context::AppContext;

pub mod app_context;
pub mod config;
pub mod metric_consts;

pub async fn handle_batch(
    fingerprints: Vec<NewFingerprintEvent>,
    _offsets: &[Offset],
    context: Arc<AppContext>,
) -> Result<Vec<EmbeddingRecord>> {
    let mut handles = vec![];
    let client = Client::new();
    let api_key = context.config.openai_api_key.clone();
    for fingerprint in fingerprints {
        for model in &fingerprint.models {
            handles.push(generate_embedding(
                client.clone(),
                api_key.clone(),
                model.clone(),
                fingerprint.clone(),
            ));
        }
    }
    let results = futures::future::join_all(handles).await;
    results.into_iter().collect()
}

const EMBEDDING_VERSION: i64 = 1;

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
    fingerprint: NewFingerprintEvent,
) -> Result<EmbeddingRecord> {
    // TODO - once we have a larger model zoo, we'll need to select this more carefully
    let encoder = tiktoken_rs::cl100k_base()?;

    // Generate text representation of the exception and frames
    // TODO - as above, a larger model zoo will require more careful selection of the model
    let text = generate_text_representation(&fingerprint, &encoder, 8192)?;

    // Call OpenAI API to generate embeddings
    let request = OpenAIEmbeddingRequest {
        input: text,
        model: model.to_string(),
    };

    let response = client
        .post("https://api.openai.com/v1/embeddings")
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .json(&request)
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

    let embeddings = response_body
        .data
        .first()
        .ok_or_else(|| anyhow::anyhow!("No embedding data returned from OpenAI"))?
        .embedding
        .clone();

    Ok(EmbeddingRecord::new(
        fingerprint.team_id,
        model,
        EMBEDDING_VERSION,
        fingerprint.fingerprint.to_string(),
        embeddings,
    ))
}

fn generate_text_representation(
    fingerprint: &NewFingerprintEvent,
    encoder: &CoreBPE,
    max_tokens: usize,
) -> Result<String> {
    let mut tokens = Vec::new();

    for exception in &fingerprint.exception_list {
        // Add exception type and value
        let type_and_value = &format!(
            "{}: {}\n",
            exception.exception_type,
            exception
                .exception_value
                .chars()
                .take(300)
                .collect::<String>()
        );

        tokens.extend(encoder.encode_with_special_tokens(type_and_value));

        if tokens.len() > max_tokens {
            tokens.truncate(max_tokens);
            return encoder.decode(tokens);
        }

        // Add frame information
        for frame in &exception.frames {
            let mut frame_parts = Vec::new();

            // Add resolved or mangled name
            if let Some(resolved_name) = &frame.resolved_name {
                frame_parts.push(resolved_name.clone());
            } else {
                frame_parts.push(frame.mangled_name.clone());
            }

            // Add source file if available
            if let Some(source) = &frame.source {
                frame_parts.push(format!("in {source}"));
            }

            // Add line number if available
            if let Some(line) = frame.line {
                frame_parts.push(format!("line {line}"));
            }

            if let Some(column) = frame.column {
                frame_parts.push(format!("column {column}"));
            }

            let mut frame_str = frame_parts.join(" ");
            frame_str.push('\n');
            let encoded = encoder.encode_with_special_tokens(&frame_str);
            if encoded.len() + tokens.len() > max_tokens {
                return encoder.decode(tokens);
            }

            tokens.extend(encoded);
        }
    }

    encoder.decode(tokens)
}
