use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use k8s_awareness::DiscoveredPod;

use crate::jobs::{AnalysisRequest, JobView};
use crate::kafka::lag::{self, ConsumerTarget, GroupLag, LagOverview};
use crate::proxy;
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

    pub fn unavailable(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            message: message.into(),
        }
    }

    pub fn too_many_requests(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "error": self.message }))).into_response()
    }
}

/// The API only accepts exact group/topic pairs present in the (cached)
/// discovered targets — prefix checks alone would let a fabricated group
/// read any prefixed topic, and the tool must not become a generic Kafka
/// browser. Prefix mismatches fail fast with a clearer message.
async fn validated_target(
    state: &AppState,
    group: &str,
    topic: &str,
) -> Result<ConsumerTarget, ApiError> {
    if !group.starts_with(&state.config.group_prefix) {
        return Err(ApiError::bad_request(format!(
            "group '{group}' is outside the '{}' prefix",
            state.config.group_prefix
        )));
    }
    if !topic.starts_with(&state.config.topic_prefix) {
        return Err(ApiError::bad_request(format!(
            "topic '{topic}' is outside the '{}' prefix",
            state.config.topic_prefix
        )));
    }

    let targets = state
        .discovery
        .get_or_refresh(|| lag::discover_targets(&state.config))
        .await
        .map_err(|e| ApiError::upstream(format!("target discovery failed: {e:#}")))?;
    let target = ConsumerTarget {
        group: group.to_string(),
        topic: topic.to_string(),
    };
    if !targets.contains(&target) {
        return Err(ApiError::bad_request(format!(
            "'{group}' / '{topic}' is not a discovered consumer target \
             (discovery refreshes every {}s)",
            state.config.discovery_cache_ttl_secs
        )));
    }
    Ok(target)
}

async fn get_lag_overview(State(state): State<AppState>) -> Result<Json<LagOverview>, ApiError> {
    let overview = state
        .overview
        .get_or_refresh(|| async {
            let targets = state
                .discovery
                .get_or_refresh(|| lag::discover_targets(&state.config))
                .await?;
            Ok(lag::scan_targets(&state.config, targets.as_ref().clone()).await)
        })
        .await
        .map_err(|e| ApiError::upstream(format!("lag overview failed: {e:#}")))?;
    Ok(Json(overview.as_ref().clone()))
}

#[derive(Deserialize)]
struct LagQuery {
    group: String,
    topic: String,
}

async fn get_lag(
    State(state): State<AppState>,
    Query(query): Query<LagQuery>,
) -> Result<Json<GroupLag>, ApiError> {
    let target = validated_target(&state, &query.group, &query.topic).await?;

    let group_lag = lag::scan_group_lag(&state.config, &target)
        .await
        .map_err(|e| ApiError::upstream(format!("lag scan failed: {e:#}")))?;

    Ok(Json(group_lag))
}

async fn create_analysis(
    State(state): State<AppState>,
    Json(request): Json<AnalysisRequest>,
) -> Result<(StatusCode, Json<serde_json::Value>), ApiError> {
    let target = validated_target(&state, &request.group, &request.topic).await?;
    if request.partition < 0 {
        return Err(ApiError::bad_request("partition must be non-negative"));
    }
    let Some(slot) = state.jobs.try_reserve_slot() else {
        return Err(ApiError::too_many_requests(
            "too many pending analyses; wait for current jobs to finish or cancel one",
        ));
    };

    let job_id = state
        .jobs
        .start(
            Arc::clone(&state.config),
            Arc::clone(&state.teams),
            target,
            request,
            slot,
        )
        .await
        .map_err(|e| ApiError::upstream(format!("failed to start analysis: {e:#}")))?;

    Ok((StatusCode::ACCEPTED, Json(json!({ "job_id": job_id }))))
}

async fn list_analyses(State(state): State<AppState>) -> Json<Vec<JobView>> {
    Json(state.jobs.list())
}

async fn get_analysis(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobView>, ApiError> {
    let job = state
        .jobs
        .get(&id)
        .ok_or_else(|| ApiError::not_found(format!("no analysis job '{id}'")))?;
    Ok(Json(job.view()))
}

async fn cancel_analysis(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<StatusCode, ApiError> {
    if state.jobs.cancel(&id) {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(ApiError::not_found(format!("no analysis job '{id}'")))
    }
}

#[derive(Serialize)]
struct PodsResponse {
    pods: Vec<DiscoveredPod>,
}

async fn list_pods(State(state): State<AppState>) -> Result<Json<PodsResponse>, ApiError> {
    let pods = state
        .pods
        .list_pods(&state.config)
        .await
        .map_err(|e| ApiError::unavailable(format!("pod discovery unavailable: {e:#}")))?;
    Ok(Json(PodsResponse { pods }))
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/", get(ui::index))
        .route("/api/lag", get(get_lag))
        .route("/api/lag/overview", get(get_lag_overview))
        .route("/api/analyses", get(list_analyses).post(create_analysis))
        .route(
            "/api/analyses/:id",
            get(get_analysis).delete(cancel_analysis),
        )
        .route("/api/pods", get(list_pods))
        // The consumer debug UI is served per pod; its relative `debug/...`
        // fetches resolve to the proxy route below. Pods are addressed by
        // namespace + name so identical names across lanes cannot collide.
        .route("/pods/:namespace/:name/", get(ui::consumer_debug))
        .route(
            "/pods/:namespace/:name/debug/*rest",
            get(proxy::proxy_debug),
        )
        .with_state(state)
}
