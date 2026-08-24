use std::sync::Arc;

use axum::http::StatusCode;
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

    /// Status the handler answers with. Only an internal failure is worth a retry.
    pub fn status_code(&self) -> StatusCode {
        match self {
            Self::NotOptedIn => StatusCode::FORBIDDEN,
            Self::ContentTooLong => StatusCode::BAD_REQUEST,
            Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
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

#[cfg(test)]
mod test {
    use axum::http::StatusCode;

    use crate::ad_hoc::AdHocError;

    // Two callers branch on this status. Error tracking retries anything at or above 500, and
    // the Python client only explains a missing opt-in when it sees a 403. Answering 5xx for a
    // rejection that can never succeed puts both back to retrying it forever.
    #[test]
    fn only_an_internal_failure_is_worth_retrying() {
        let cases = [
            (AdHocError::NotOptedIn, StatusCode::FORBIDDEN),
            (AdHocError::ContentTooLong, StatusCode::BAD_REQUEST),
            (
                AdHocError::Internal(anyhow::anyhow!("provider timed out")),
                StatusCode::INTERNAL_SERVER_ERROR,
            ),
        ];

        for (error, expected) in cases {
            assert_eq!(error.status_code(), expected, "{error:?}");
        }
    }

    // `_raise_for_embedding_response` in posthog/api/embedding_worker.py only adds its
    // actionable hint when the 403 body mentions "ai". Rewording this message without it
    // turns that hint back into the dead code this change made reachable.
    #[test]
    fn opt_in_rejection_names_ai_for_the_python_client() {
        assert!(AdHocError::NotOptedIn
            .message()
            .to_lowercase()
            .contains("ai"));
    }
}
