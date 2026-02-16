use std::sync::Arc;

use axum::{
    extract::{Json, State},
    response::IntoResponse,
};

use reqwest::StatusCode;

use serde_json::json;
use tracing::warn;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    stages::pipeline::ExceptionEventPipeline,
    types::{batch::Batch, event::AnyEvent, stage::Stage},
};

impl IntoResponse for UnhandledError {
    fn into_response(self) -> axum::response::Response {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "error": "An unexpected error occurred while processing the events",
                "details": self.to_string(),
            })),
        )
            .into_response()
    }
}

impl IntoResponse for Batch<Result<AnyEvent, EventError>> {
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

#[axum::debug_handler]
pub async fn process_events(
    State(ctx): State<Arc<AppContext>>,
    Json(events): Json<Vec<AnyEvent>>,
) -> Result<Batch<Result<AnyEvent, EventError>>, UnhandledError> {
    let pipeline = ExceptionEventPipeline::new(ctx);
    let input = Batch::from(events);
    let output = pipeline.process(input).await?;
    Ok(output)
}
