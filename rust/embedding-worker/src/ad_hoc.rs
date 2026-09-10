use std::sync::Arc;

use axum::{extract::Json, http::StatusCode};
use common_types::embedding::EmbeddingModel;
use serde::{Deserialize, Serialize};
use tracing::{error, warn};

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

/// Callers retry 5xx and give up on 4xx, so the status code has to separate the two:
/// an opted-out organization and over-long content are permanent and never succeed on
/// retry, while anything else here is transient enough to be worth retrying.
pub async fn handle_ad_hoc_request(
    context: Arc<AppContext>,
    request: AdHocEmbeddingRequest,
) -> Result<Json<AdHocEmbeddingResponse>, StatusCode> {
    let team_id = request.team_id;
    let request = match apply_ai_opt_in(&context, request, team_id).await {
        Ok(Some(request)) => request,
        Ok(None) => {
            warn!("Ad hoc embedding request for team {team_id} rejected: organization not opted in to ai features");
            return Err(StatusCode::FORBIDDEN);
        }
        Err(e) => {
            error!(
                "Ad hoc embedding request for team {team_id} failed to resolve organization: {:?}",
                e
            );
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    };

    let would_truncate = check_would_truncate(&request.content, &request.model);

    if would_truncate && !request.no_truncate {
        warn!("Ad hoc embedding request for team {team_id} rejected: content too long");
        return Err(StatusCode::BAD_REQUEST);
    }

    let (embedding, token_count) = match generate_embedding(
        context.clone(),
        request.model,
        &request.content,
        &RequestLabels::from(&request),
    )
    .await
    {
        Ok(result) => result,
        Err(e) => {
            error!(
                "Ad hoc embedding request for team {team_id} failed: {:?}",
                e
            );
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    };

    Ok(Json(AdHocEmbeddingResponse {
        embedding,
        tokens_used: token_count,
        did_truncate: would_truncate,
    }))
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
