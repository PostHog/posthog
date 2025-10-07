use std::{fmt::Display, str::FromStr};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

// Requests the embedding worker can process
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingRequest {
    pub team_id: i32,
    pub product: String,
    pub document_type: String,
    pub rendering: String,
    pub document_id: String,
    pub timestamp: DateTime<Utc>,
    pub content: String,
    pub models: Vec<EmbeddingModel>,
}

// Records the embedding worker emits, for ingestion into clickhouse
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingRecord {
    pub team_id: i32,
    pub product: String,
    pub document_type: String,
    pub model_name: String,
    pub rendering: String,
    pub document_id: String,
    pub timestamp: DateTime<Utc>,
    pub embedding: Vec<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub enum EmbeddingModel {
    #[serde(rename = "text-embedding-3-small-1536")]
    #[default]
    OpenAITextEmbeddingSmall,
    #[serde(rename = "text-embedding-3-large-3072")]
    OpenAITextEmbeddingLarge,
}

#[derive(Error, Debug, Clone)]
#[error("Invalid Model: {model}")]
pub struct ModelParsingError {
    pub model: String,
}

impl FromStr for EmbeddingModel {
    type Err = ModelParsingError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim() {
            "text-embedding-3-small" => Ok(EmbeddingModel::OpenAITextEmbeddingSmall),
            "text-embedding-3-large" => Ok(EmbeddingModel::OpenAITextEmbeddingLarge),
            m => Err(ModelParsingError {
                model: m.to_string(),
            }),
        }
    }
}

impl Display for EmbeddingModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => write!(f, "text-embedding-3-small"),
            EmbeddingModel::OpenAITextEmbeddingLarge => write!(f, "text-embedding-3-large"),
        }
    }
}
