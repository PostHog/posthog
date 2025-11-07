use common_types::embedding::{EmbeddingModel, EmbeddingRequest};

use crate::ad_hoc::AdHocEmbeddingRequest;

pub const MESSAGES_RECEIVED: &str = "embedding_worker_messages_received";
pub const EMBEDDINGS_GENERATED: &str = "embedding_worker_embeddings_generated";
pub const LIMITS_UPDATED: &str = "embedding_worker_limits_updated";
pub const LIMIT_BALANCE: &str = "embedding_worker_limit_balance";
pub const DROPPED_REQUESTS: &str = "embedding_worker_dropped_requests";
pub const MESSAGE_TRUNCATED: &str = "embedding_worker_content_truncated";
pub const EMBEDDING_FAILED: &str = "embedding_worker_embedding_failed";
pub const EMBEDDING_TOTAL_TIME: &str = "embedding_worker_embedding_total_time";
pub const EMBEDDING_REQUEST_TIME: &str = "embedding_worker_embedding_request_time";
pub const EMBEDDING_TOTAL_TOKENS: &str = "embedding_worker_embedding_total_tokens";

pub struct RequestLabels {
    labels: Vec<(String, String)>,
}

impl RequestLabels {
    pub fn and<E, K, V>(mut self, extra: E) -> Self
    where
        E: IntoIterator<Item = (K, V)>,
        K: ToString,
        V: ToString,
    {
        self.labels.extend(
            extra
                .into_iter()
                .map(|(k, v)| (k.to_string(), v.to_string())),
        );
        self
    }

    pub fn and_model(self, model: EmbeddingModel) -> Self {
        self.and([("model", model.name())])
    }

    pub fn render(&self) -> &[(String, String)] {
        &self.labels
    }
}

impl From<&EmbeddingRequest> for RequestLabels {
    fn from(request: &EmbeddingRequest) -> Self {
        Self {
            labels: vec![
                ("product".to_string(), request.product.as_str().to_string()),
                (
                    "document_type".to_string(),
                    request.document_type.as_str().to_string(),
                ),
                (
                    "rendering".to_string(),
                    request.rendering.as_str().to_string(),
                ),
            ],
        }
    }
}

impl From<&AdHocEmbeddingRequest> for RequestLabels {
    fn from(request: &AdHocEmbeddingRequest) -> Self {
        Self {
            labels: vec![("from".to_string(), "api".to_string())],
        }
        .and_model(request.model)
    }
}
