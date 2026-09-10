use std::sync::Arc;

use axum::{extract::Json, http::StatusCode};
use common_types::embedding::EmbeddingModel;
use serde::{Deserialize, Serialize};
use tracing::{error, warn};

use crate::{
    app_context::AppContext, generate_embedding, metrics_utils::RequestLabels,
    organization::apply_ai_opt_in, CL100K_ENCODER,
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
            // Count every token: capping the count at the input window first would make the
            // comparison below unsatisfiable.
            let token_count = CL100K_ENCODER.encode_with_special_tokens(content).len();
            token_count > model.model_input_window()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Build text of an exact token length by decoding that many tokens off a longer
    // stream. Repeated whole words keep every cut on a token boundary, so the result
    // re-encodes to the same count.
    fn content_with_tokens(count: usize) -> String {
        let encoder = &*CL100K_ENCODER;
        let stream = "word ".repeat(count + 16);
        let tokens: Vec<_> = encoder
            .encode_with_special_tokens(&stream)
            .into_iter()
            .take(count)
            .collect();
        let content = encoder.decode(tokens).expect("fixture decodes cleanly");
        assert_eq!(
            encoder.encode_with_special_tokens(&content).len(),
            count,
            "fixture should hold exactly {count} tokens"
        );
        content
    }

    #[test]
    fn short_content_does_not_truncate() {
        assert!(!check_would_truncate(
            "hello world",
            &EmbeddingModel::OpenAITextEmbeddingSmall
        ));
    }

    #[test]
    fn content_over_the_input_window_truncates() {
        // The check used to take() the input window's worth of tokens before comparing the
        // count against that same window, so it could never report a truncation.
        for model in [
            EmbeddingModel::OpenAITextEmbeddingSmall,
            EmbeddingModel::OpenAITextEmbeddingLarge,
        ] {
            let content = content_with_tokens(model.model_input_window() + 1);
            assert!(
                check_would_truncate(&content, &model),
                "{model:?} should truncate one token past its input window"
            );
        }
    }

    #[test]
    fn content_at_the_input_window_does_not_truncate() {
        // generate_embedding_text only drops tokens beyond the window, so content sitting
        // exactly on it survives intact.
        for model in [
            EmbeddingModel::OpenAITextEmbeddingSmall,
            EmbeddingModel::OpenAITextEmbeddingLarge,
        ] {
            let content = content_with_tokens(model.model_input_window());
            assert!(
                !check_would_truncate(&content, &model),
                "{model:?} should not truncate content exactly at its input window"
            );
        }
    }
}
