use std::sync::Arc;

use anyhow::Result;
use common_kafka::kafka_consumer::Offset;
use common_types::error_tracking::{EmbeddingModel, EmbeddingRecord, NewFingerprintEvent};
use reqwest::Client;
use serde::{Deserialize, Serialize};
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
    // Generate text representation of the exception and frames
    let text = generate_text_representation(&fingerprint);

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

fn generate_text_representation(fingerprint: &NewFingerprintEvent) -> String {
    let mut text_parts = Vec::new();

    for exception in &fingerprint.exception_list {
        // Add exception type and value
        text_parts.push(format!(
            "{}: {}",
            exception.exception_type,
            exception
                .exception_value
                .chars()
                .take(300)
                .collect::<String>()
        ));

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

            text_parts.push(frame_parts.join(" "));
        }
    }

    text_parts.join("\n")
}
