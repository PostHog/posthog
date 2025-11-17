use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;

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
    pub timestamp: String, // This is clickhouse format
    pub embedding: Vec<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub enum EmbeddingModel {
    #[serde(rename = "text-embedding-3-small-1536")]
    #[default]
    OpenAITextEmbeddingSmall,
    #[serde(rename = "text-embedding-3-large-3072")]
    OpenAITextEmbeddingLarge,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ApiLimits {
    pub requests_per_minute: usize,
    pub tokens_per_minute: usize,
}

impl EmbeddingModel {
    pub fn name(&self) -> &'static str {
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

    pub fn model_input_window(&self) -> usize {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => 8192,
            EmbeddingModel::OpenAITextEmbeddingLarge => 8192,
        }
    }

    pub fn model_url(&self) -> &'static str {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
                "https://api.openai.com/v1/embeddings"
            }
        }
    }

    pub fn limits_key(&self) -> &'static str {
        // Based on our openai usage limits, these are distinct buckets
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall => "openai_text_embedding_small",
            EmbeddingModel::OpenAITextEmbeddingLarge => "openai_text_embedding_large",
        }
    }

    pub fn api_limits(&self) -> ApiLimits {
        // TODO - these are VERY conservative, but keep in mind each pod will max out at this.
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
                ApiLimits {
                    requests_per_minute: 3_000,
                    tokens_per_minute: 1_000_000,
                }
            }
        }
    }

    // This takes a function ref as an argument to avoid taking a dep on reqwest
    pub fn api_limits_from_response(
        &self,
        headers: &dyn Fn(&str) -> Option<String>,
    ) -> Option<ApiLimits> {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
                let rpm = headers("x-ratelimit-limit-requests")?.parse().ok()?;
                let tpm = headers("x-ratelimit-limit-tokens")?.parse().ok()?;
                Some(ApiLimits {
                    requests_per_minute: rpm,
                    tokens_per_minute: tpm,
                })
            }
        }
    }

    pub fn construct_request_body(&self, text: &str) -> Value {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
                let request = OAIEmbeddingRequest {
                    input: text.to_string(),
                    model: self.name().to_string(),
                };
                serde_json::to_value(request).expect("We are able to serialize the request")
            }
        }
    }

    pub fn extract_embedding_from_response_body(&self, response: &Value) -> Option<Vec<f64>> {
        match self {
            EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
                let response: OAIEmbeddingResponse =
                    serde_json::from_value(response.clone()).ok()?;
                response.data.into_iter().next().map(|d| d.embedding)
            }
        }
    }
}

#[derive(Serialize)]
struct OAIEmbeddingRequest {
    input: String,
    model: String,
}

#[derive(Deserialize)]
struct OAIEmbeddingResponse {
    data: Vec<OAIEmbeddingData>,
}

#[derive(Deserialize)]
struct OAIEmbeddingData {
    embedding: Vec<f64>,
}
