use std::sync::Arc;

use axum::{extract::State, http::HeaderMap, response::IntoResponse, Json};
use reqwest::StatusCode;
use serde_json::json;
use tracing::{debug, error, info, warn};

use crate::{
    app_context::AppContext,
    distributed::{tasks::ResolveBatchRequest, DistributedContext},
};

#[axum::debug_handler]
pub async fn resolve_batch_internal(
    State(ctx): State<Arc<AppContext>>,
    headers: HeaderMap,
    Json(request): Json<ResolveBatchRequest>,
) -> impl IntoResponse {
    let expected = &ctx.config.internal_api_secret;
    if !expected.is_empty() {
        let provided = headers
            .get("X-Internal-Api-Secret")
            .and_then(|v| v.to_str().ok());

        if provided != Some(expected) {
            warn!("internal resolve-batch rejected: invalid or missing secret");
            return (
                StatusCode::UNAUTHORIZED,
                Json(json!({ "error": "unauthorized" })),
            )
                .into_response();
        }
    }

    let task_count = request.tasks.len();
    debug!(task_count, "internal resolve-batch received");
    let resolution_ctx = DistributedContext::new(&ctx);

    match resolution_ctx.process_internal_request(request).await {
        Ok(response) => {
            info!(
                task_count,
                result_count = response.results.len(),
                "internal resolve-batch completed"
            );
            (StatusCode::OK, Json(response)).into_response()
        }
        Err(err) => {
            error!(task_count, error = %err, "internal resolve-batch failed");
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({ "error": "internal resolution failed" })),
            )
                .into_response()
        }
    }
}
