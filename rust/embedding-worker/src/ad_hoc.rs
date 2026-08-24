use std::sync::Arc;

use common_types::embedding::EmbeddingModel;
use serde::{Deserialize, Serialize};

use crate::{
    app_context::AppContext, generate_embedding, metrics_utils::RequestLabels,
    organization::apply_ai_opt_in,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdHocEmbeddingRequest {
    pub team_id: i32,
    pub content: String,
    #[serde(default)]
    pub model: EmbeddingModel,
    #[serde(default)]
    pub no_truncate: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdHocEmbeddingResponse {
    pub embedding: Vec<f64>,
    pub tokens_used: usize,
    pub did_truncate: bool,
}

/// Why an ad-hoc embedding request was rejected.
///
/// Callers need to tell these apart. A missing AI opt-in is a permanent, user-fixable
/// condition, and the Python client turns it into an actionable message — which it can't do
/// when every failure arrives as an opaque 500 indistinguishable from a transient outage.
#[derive(Debug)]
pub enum AdHocError {
    NotOptedIn,
    ContentTooLong,
    Internal(anyhow::Error),
}

impl AdHocError {
    /// Response body. Internal failures stay generic: the detail goes to the log, not the caller.
    pub fn message(&self) -> &'static str {
        match self {
            Self::NotOptedIn => "Organization has not opted in to AI data processing",
            Self::ContentTooLong => "Content too long",
            Self::Internal(_) => "Embedding request failed",
        }
    }
}

impl From<anyhow::Error> for AdHocError {
    fn from(error: anyhow::Error) -> Self {
        Self::Internal(error)
    }
}

impl From<sqlx::Error> for AdHocError {
    fn from(error: sqlx::Error) -> Self {
        Self::Internal(error.into())
    }
}

pub async fn handle_ad_hoc_request(
    context: Arc<AppContext>,
    request: AdHocEmbeddingRequest,
) -> Result<AdHocEmbeddingResponse, AdHocError> {
    let team_id = request.team_id;
    let Some(request) = apply_ai_opt_in(&context, request, team_id).await? else {
        return Err(AdHocError::NotOptedIn);
    };

    let would_truncate = check_would_truncate(&request.content, &request.model);

    if would_truncate && !request.no_truncate {
        return Err(AdHocError::ContentTooLong);
    }

    let (embedding, token_count) = generate_embedding(
        context.clone(),
        request.model,
        &request.content,
        &RequestLabels::from(&request),
    )
    .await?;

    Ok(AdHocEmbeddingResponse {
        embedding,
        tokens_used: token_count,
        did_truncate: would_truncate,
    })
}

pub fn check_would_truncate(content: &str, model: &EmbeddingModel) -> bool {
    match model {
        EmbeddingModel::OpenAITextEmbeddingSmall | EmbeddingModel::OpenAITextEmbeddingLarge => {
            let encoder = tiktoken_rs::cl100k_base().expect("We can construct the encoder");
            let tokens: Vec<_> = encoder
                .encode_with_special_tokens(content)
                .into_iter()
                .take(model.model_input_window())
                .collect();
            let token_count = tokens.len();
            token_count > model.model_input_window()
        }
    }
}
