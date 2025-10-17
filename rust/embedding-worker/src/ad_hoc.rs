use std::sync::Arc;

use anyhow::Result;
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

pub async fn handle_ad_hoc_request(
    context: Arc<AppContext>,
    request: AdHocEmbeddingRequest,
) -> Result<AdHocEmbeddingResponse> {
    let team_id = request.team_id;
    let Some(request) = apply_ai_opt_in(&context, request, team_id).await? else {
        return Err(anyhow::anyhow!("Organization not opted in to ai features"));
    };

    let would_truncate = check_would_truncate(&request.content, &request.model);

    if would_truncate && !request.no_truncate {
        return Err(anyhow::anyhow!("Content too long"));
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
