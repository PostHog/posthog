use std::sync::Arc;

use axum::{extract::State, response::IntoResponse, Json};
use reqwest::StatusCode;
use serde_json::json;
use tracing::{debug, error, info};

use crate::{
    app_context::AppContext,
    distributed::{tasks::ResolveBatchRequest, DistributedContext},
};

#[axum::debug_handler]
pub async fn resolve_batch_internal(
    State(ctx): State<Arc<AppContext>>,
    Json(request): Json<ResolveBatchRequest>,
) -> impl IntoResponse {
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
