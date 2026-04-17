use std::sync::Arc;

use axum::{extract::State, response::IntoResponse, Json};
use reqwest::StatusCode;
use serde_json::json;

use crate::{
    app_context::AppContext,
    distributed::{tasks::ResolveBatchRequest, DistributedContext},
};

#[axum::debug_handler]
pub async fn resolve_batch_internal(
    State(ctx): State<Arc<AppContext>>,
    Json(request): Json<ResolveBatchRequest>,
) -> impl IntoResponse {
    let resolution_ctx = DistributedContext::new(&ctx);

    match resolution_ctx.process_internal_request(request).await {
        Ok(response) => (StatusCode::OK, Json(response)).into_response(),
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "error": "internal resolution failed",
                "details": err.to_string(),
            })),
        )
            .into_response(),
    }
}
