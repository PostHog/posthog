use std::sync::Arc;

use axum::{
    extract::{Json, State},
    response::IntoResponse,
};

use common_types::ClickHouseEvent;
use reqwest::StatusCode;

use serde_json::json;
use tracing::warn;

use crate::{
    app_context::AppContext, error::UnhandledError, stages::pipeline::ExceptionEventPipeline,
    types::batch::Batch,
};

impl IntoResponse for UnhandledError {
    fn into_response(self) -> axum::response::Response {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "error": self.to_string(),
                "results": []
            })),
        )
            .into_response()
    }
}

impl IntoResponse for Batch<ClickHouseEvent> {
    fn into_response(self) -> axum::response::Response {
        match serde_json::to_value(Vec::from(self)) {
            Ok(value) => (StatusCode::OK, Json(value)).into_response(),
            Err(e) => {
                warn!("Failed to serialize response: {}", e);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({
                        "error": "Failed to serialize response",
                        "details": e.to_string()
                    })),
                )
                    .into_response()
            }
        }
    }
}

pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    Json(events): Json<Vec<ClickHouseEvent>>,
) -> Result<Batch<ClickHouseEvent>, UnhandledError> {
    let pipeline = ExceptionEventPipeline::new(ctx);
    let input = Batch::from(events);
    let output = input.apply_stage(pipeline).await?;
    Ok(output)
}
