use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use k8s_awareness::DiscoveredPod;

use crate::etcd;
use crate::jobs::{AnalysisRequest, JobView};
use crate::kafka::browse::{self, BrowseParams, BrowseStop, MessageFilter, MessageRecord};
use crate::kafka::client;
use crate::kafka::lag::{self, ConsumerTarget, GroupLag, LagOverview};
use crate::personhog;
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

#[derive(Deserialize)]
struct MessagesQuery {
    group: String,
    topic: String,
    partition: i32,
    /// Cursor; defaults to the group's committed offset (or the low
    /// watermark when the group never committed).
    start_offset: Option<i64>,
    limit: Option<usize>,
    token: Option<String>,
    event: Option<String>,
    distinct_id: Option<String>,
}

#[derive(Serialize)]
struct MessagesResponse {
    partition: i32,
    start_offset: i64,
    /// Cursor for the next page.
    next_offset: i64,
    low_watermark: i64,
    high_watermark: i64,
    scanned: u64,
    stop: BrowseStop,
    reached_end: bool,
    duration_ms: u64,
    messages: Vec<MessageRecord>,
    /// team_id per distinct token in `messages` (null when unresolvable).
    token_teams: HashMap<String, Option<i32>>,
}

/// Synchronous filtered scan of one partition, returning matched message
/// headers (never payloads) plus a cursor. Bounded per request by the page
/// limit, a scan budget, a deadline, and a byte budget, whichever hits first.
async fn get_messages(
    State(state): State<AppState>,
    Query(query): Query<MessagesQuery>,
) -> Result<Json<MessagesResponse>, ApiError> {
    let target = validated_target(&state, &query.group, &query.topic).await?;
    if query.partition < 0 {
        return Err(ApiError::bad_request("partition must be non-negative"));
    }
    let limit = query.limit.unwrap_or(100).clamp(1, 500);
    // An empty query-param value means "not filtered", so it can never pin a
    // filter to the empty string.
    let non_empty = |s: Option<String>| s.filter(|s| !s.is_empty());
    let filter = MessageFilter {
        token: non_empty(query.token),
        event: non_empty(query.event),
        distinct_id: non_empty(query.distinct_id),
    };

    let Ok(_permit) = Arc::clone(&state.browse_permits).try_acquire_owned() else {
        return Err(ApiError::too_many_requests(
            "too many concurrent message scans; wait for one to finish",
        ));
    };

    let config = Arc::clone(&state.config);
    let partition = query.partition;
    let requested_start = query.start_offset;
    let (bounds, start_offset, outcome) = tokio::task::spawn_blocking(move || {
        let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
        let bounds = lag::fetch_partition_bounds_blocking(&config, &target, partition, timeout)?;
        let start_offset = requested_start
            .unwrap_or_else(|| bounds.committed_offset.unwrap_or(bounds.low_watermark))
            .clamp(bounds.low_watermark, bounds.high_watermark);
        let params = BrowseParams {
            topic: target.topic.clone(),
            partition,
            start_offset,
            end_offset_exclusive: bounds.high_watermark,
            limit,
            scan_limit: config.browse_scan_message_count,
            deadline: Duration::from_secs(config.browse_deadline_secs),
            max_bytes: config.browse_max_fetch_bytes,
            poll_timeout: Duration::from_millis(config.kafka_fetch_poll_timeout_ms),
        };
        let consumer = client::fetch_consumer(&config).context("create fetch client")?;
        let outcome = browse::run_browse(&consumer, &params, &filter)?;
        anyhow::Ok((bounds, start_offset, outcome))
    })
    .await
    .context("browse task panicked")
    .and_then(|res| res)
    .map_err(|e| ApiError::upstream(format!("message scan failed: {e:#}")))?;

    let mut tokens: Vec<String> = outcome
        .records
        .iter()
        .filter_map(|record| record.token.clone())
        .collect();
    tokens.sort();
    tokens.dedup();
    let token_teams = state.teams.resolve(&tokens).await;

    Ok(Json(MessagesResponse {
        partition: query.partition,
        start_offset,
        next_offset: outcome.next_offset,
        low_watermark: bounds.low_watermark,
        high_watermark: bounds.high_watermark,
        scanned: outcome.scanned,
        stop: outcome.stop,
        reached_end: outcome.next_offset >= bounds.high_watermark,
        duration_ms: outcome.duration_ms,
        messages: outcome.records,
        token_teams,
    }))
}

/// The configured etcd handle, or 503 when `ETCD_ENDPOINTS` is unset.
fn etcd_handle(state: &AppState) -> Result<Arc<crate::etcd::EtcdHandle>, ApiError> {
    state
        .etcd
        .clone()
        .ok_or_else(|| ApiError::unavailable("etcd tools are disabled (ETCD_ENDPOINTS not set)"))
}

async fn etcd_client(state: &AppState) -> Result<etcd_client::Client, ApiError> {
    etcd_handle(state)?
        .client()
        .await
        .map_err(|e| ApiError::unavailable(format!("etcd unreachable: {e:#}")))
}

/// Every explorer operation must stay under one of the configured allowed
/// prefixes, so a deployment can scope what this unauthenticated-but-
/// internal tool may touch.
fn validated_etcd_key<'a>(state: &AppState, key: &'a str) -> Result<&'a str, ApiError> {
    if key.is_empty() {
        return Err(ApiError::bad_request("key must not be empty"));
    }
    let allowed = state.config.etcd_allowed_prefix_list();
    if !allowed.iter().any(|prefix| key.starts_with(prefix)) {
        return Err(ApiError::bad_request(format!(
            "key '{key}' is outside the allowed prefixes {allowed:?}"
        )));
    }
    Ok(key)
}

#[derive(Deserialize)]
struct EtcdKeysQuery {
    prefix: String,
    from_key: Option<String>,
    limit: Option<i64>,
}

async fn etcd_list_keys(
    State(state): State<AppState>,
    Query(query): Query<EtcdKeysQuery>,
) -> Result<Json<etcd::KeyList>, ApiError> {
    validated_etcd_key(&state, &query.prefix)?;
    let limit = query.limit.unwrap_or(500).clamp(1, 1000);
    let client = etcd_client(&state).await?;
    let list = etcd::list_keys(&client, &query.prefix, query.from_key.as_deref(), limit)
        .await
        .map_err(|e| ApiError::upstream(format!("etcd list failed: {e:#}")))?;
    Ok(Json(list))
}

#[derive(Deserialize)]
struct EtcdKeyQuery {
    key: String,
}

async fn etcd_get_key(
    State(state): State<AppState>,
    Query(query): Query<EtcdKeyQuery>,
) -> Result<Json<etcd::KeyDetail>, ApiError> {
    validated_etcd_key(&state, &query.key)?;
    let client = etcd_client(&state).await?;
    let detail = etcd::get_key(&client, &query.key)
        .await
        .map_err(|e| ApiError::upstream(format!("etcd get failed: {e:#}")))?
        .ok_or_else(|| ApiError::not_found(format!("no key '{}'", query.key)))?;
    Ok(Json(detail))
}

#[derive(Deserialize)]
struct EtcdPutRequest {
    key: String,
    value: String,
}

async fn etcd_put_key(
    State(state): State<AppState>,
    Json(request): Json<EtcdPutRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    validated_etcd_key(&state, &request.key)?;
    let client = etcd_client(&state).await?;
    let revision = etcd::put_key(&client, &request.key, &request.value)
        .await
        .map_err(|e| ApiError::upstream(format!("etcd put failed: {e:#}")))?;
    Ok(Json(json!({ "revision": revision })))
}

async fn etcd_delete_key(
    State(state): State<AppState>,
    Query(query): Query<EtcdKeyQuery>,
) -> Result<StatusCode, ApiError> {
    validated_etcd_key(&state, &query.key)?;
    let client = etcd_client(&state).await?;
    let deleted = etcd::delete_key(&client, &query.key)
        .await
        .map_err(|e| ApiError::upstream(format!("etcd delete failed: {e:#}")))?;
    if deleted {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(ApiError::not_found(format!("no key '{}'", query.key)))
    }
}

async fn personhog_topology(
    State(state): State<AppState>,
) -> Result<Json<personhog::TopologyView>, ApiError> {
    let client = etcd_client(&state).await?;
    let deadlines = personhog::Deadlines {
        handoff: Duration::from_secs(state.config.personhog_handoff_deadline_secs),
        warming: Duration::from_secs(state.config.personhog_warming_deadline_secs),
    };
    let view = personhog::fetch_topology(&client, &state.config.personhog_etcd_prefix, &deadlines)
        .await
        .map_err(|e| ApiError::upstream(format!("personhog topology failed: {e:#}")))?;
    Ok(Json(view))
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
        .route("/api/messages", get(get_messages))
        .route("/api/analyses", get(list_analyses).post(create_analysis))
        .route(
            "/api/analyses/:id",
            get(get_analysis).delete(cancel_analysis),
        )
        .route("/api/pods", get(list_pods))
        .route("/api/etcd/keys", get(etcd_list_keys))
        .route(
            "/api/etcd/key",
            get(etcd_get_key).put(etcd_put_key).delete(etcd_delete_key),
        )
        .route("/api/personhog/topology", get(personhog_topology))
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
