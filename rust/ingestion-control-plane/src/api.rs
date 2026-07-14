use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::kafka::lag::{self, GroupLag};
use crate::state::AppState;
use crate::ui;

pub struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    pub fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            message: message.into(),
        }
    }

    pub fn upstream(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_GATEWAY,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "error": self.message }))).into_response()
    }
}

#[derive(Serialize)]
struct TargetInfo {
    group: String,
    topic: String,
}

#[derive(Serialize)]
struct ConfigResponse {
    targets: Vec<TargetInfo>,
}

async fn get_config(State(state): State<AppState>) -> Json<ConfigResponse> {
    let targets = state
        .config
        .targets()
        .into_iter()
        .map(|t| TargetInfo {
            group: t.group,
            topic: t.topic,
        })
        .collect();
    Json(ConfigResponse { targets })
}

#[derive(Deserialize)]
struct LagQuery {
    group: String,
}

async fn get_lag(
    State(state): State<AppState>,
    Query(query): Query<LagQuery>,
) -> Result<Json<GroupLag>, ApiError> {
    let target = state.config.target_for_group(&query.group).ok_or_else(|| {
        ApiError::bad_request(format!("unknown consumer group '{}'", query.group))
    })?;

    let group_lag = lag::scan_group_lag(&state.config, &target)
        .await
        .map_err(|e| ApiError::upstream(format!("lag scan failed: {e:#}")))?;

    Ok(Json(group_lag))
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/", get(ui::index))
        .route("/api/config", get(get_config))
        .route("/api/lag", get(get_lag))
        .with_state(state)
}
