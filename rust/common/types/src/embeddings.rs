use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

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
    pub model_name: EmbeddingModel,
    pub rendering: String,
    pub document_id: String,
    pub timestamp: DateTime<Utc>,
    pub embedding: Vec<f64>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub enum EmbeddingModel {
    #[serde(rename = "text-embedding-3-small-1536")]
    #[default]
    OpenAITextEmbeddingSmall,
    #[serde(rename = "text-embedding-3-large-3072")]
    OpenAITextEmbeddingLarge,
}

impl EmbeddingModel {
    pub fn name(&self) -> &str {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => "text-embedding-3-small",
            EmbeddingModel::OpenAITextEmbeddingLarge => "text-embedding-3-large",
        }
    }

    pub fn model_dimension(&self) -> usize {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => 1536,
            EmbeddingModel::OpenAITextEmbeddingLarge => 3072,
        }
    }
}
