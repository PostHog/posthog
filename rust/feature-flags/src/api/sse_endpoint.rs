use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::sse::{Event, KeepAlive, Sse},
};
use bytes::Bytes;
use futures_util::stream::Stream;
use serde::Deserialize;
use std::{convert::Infallible, time::Duration};
use tracing::{error, info, warn};

use crate::router::State as AppState;

#[derive(Debug, Deserialize)]
pub struct SseQueryParams {
    #[serde(alias = "api_key", alias = "$token")]
    pub token: Option<String>,
    pub distinct_id: Option<String>,
    #[serde(default)]
    pub person_properties: Option<serde_json::Value>,
    #[serde(default)]
    pub group_properties: Option<serde_json::Value>,
    #[serde(default)]
    pub groups: Option<serde_json::Value>,
    #[serde(default = "default_evaluations")]
    pub evaluations: bool,
}

fn default_evaluations() -> bool {
    true
}

/// SSE endpoint for real-time feature flag updates.
///
/// Returns a Server-Sent Events stream that pushes flag updates when feature flags
/// are changed for the team. Supports two modes:
///
/// Mode 1 (evaluations=true, default): Server-side evaluation
///   - Evaluates flags for the specific user
///   - Returns evaluation results
///
/// Mode 2 (evaluations=false): Local evaluation
///   - Returns raw flag data
///   - Client evaluates locally
///
/// Query parameters:
/// - `token` (or `api_key` or `$token`): PostHog API token (required)
/// - `evaluations`: Whether to evaluate flags server-side (default: true)
/// - `distinct_id`: User's distinct ID (required if evaluations=true, optional otherwise)
/// - `person_properties`: JSON object with person properties (optional, only used if evaluations=true)
/// - `group_properties`: JSON object with group properties (optional, only used if evaluations=true)
/// - `groups`: JSON object with group memberships (optional, only used if evaluations=true)
///
/// The endpoint:
/// - Authenticates the token to determine the team
/// - Sends connection confirmation (no flag evaluation on initial connect)
/// - Subscribes to Redis Pub/Sub for the team's feature flag updates
/// - When a flag is updated:
///   - evaluations=true: Evaluates all flags for the user and sends results
///   - evaluations=false: Sends raw flag data for local evaluation
/// - Sends heartbeats every 30 seconds to keep the connection alive
/// - Cleans up subscriptions when the client disconnects
///
/// Event format:
/// ```
/// event: connected
/// data: {"team_id": 1}
///
/// event: message (evaluations=true)
/// data: {"flags": {"my-flag": false, "other-flag": "control"}, "errors_while_computing_flags": false}
///
/// event: message (evaluations=false)
/// data: {"id": 123, "key": "my-flag", "active": true, "filters": {...}, ...}
/// ```
pub async fn feature_flags_stream(
    State(state): State<AppState>,
    Query(params): Query<SseQueryParams>,
) -> Result<Sse<impl Stream<Item = Result<Event, Infallible>>>, StatusCode> {
    // Extract and validate token
    let token = match params.token {
        Some(t) if !t.is_empty() => t,
        _ => {
            warn!("SSE request missing token parameter");
            return Err(StatusCode::UNAUTHORIZED);
        }
    };

    // Authenticate token and get team
    let flag_service = crate::flags::flag_service::FlagService::new(
        state.redis_reader.clone(),
        state.redis_writer.clone(),
        state.database_pools.non_persons_reader.clone(),
    );

    let team = match flag_service.get_team_from_cache_or_pg(&token).await {
        Ok(team) => team,
        Err(e) => {
            warn!("SSE authentication failed for token: {:?}", e);
            return Err(StatusCode::UNAUTHORIZED);
        }
    };

    let team_id = team.id;
    let evaluations = params.evaluations;

    // Extract distinct_id - required only if evaluations=true
    let distinct_id = if evaluations {
        match params.distinct_id {
            Some(id) if !id.is_empty() => Some(id),
            _ => {
                warn!("SSE request missing distinct_id parameter (required when evaluations=true)");
                return Err(StatusCode::BAD_REQUEST);
            }
        }
    } else {
        params.distinct_id
    };

    info!(
        "New SSE connection for team {} (evaluations: {}, distinct_id: {:?})",
        team_id, evaluations, distinct_id
    );

    // Get the SSE manager from state
    let sse_manager = match &state.sse_manager {
        Some(manager) => manager,
        None => {
            error!("SSE manager not initialized");
            return Err(StatusCode::SERVICE_UNAVAILABLE);
        }
    };

    // Create a channel for this client
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

    // Subscribe to Redis channel for this team
    if let Err(e) = sse_manager.subscribe(team_id, tx).await {
        error!("Failed to subscribe to team {}: {}", team_id, e);
        return Err(StatusCode::INTERNAL_SERVER_ERROR);
    }

    // Build request body for flag evaluation (only needed if evaluations=true)
    let body_bytes = if evaluations {
        let mut request_body = serde_json::json!({
            "token": token,
            "distinct_id": distinct_id,
        });

        if let Some(props) = params.person_properties {
            request_body["person_properties"] = props;
        }

        if let Some(gprops) = params.group_properties {
            request_body["group_properties"] = gprops;
        }

        if let Some(g) = params.groups {
            request_body["groups"] = g;
        }

        Some(Bytes::from(
            serde_json::to_vec(&request_body).unwrap_or_default(),
        ))
    } else {
        None
    };

    // Clone state for the stream
    let state_for_stream = state.clone();

    // Create SSE stream
    let stream = async_stream::stream! {
        use crate::handler::{process_request, RequestContext};
        use crate::api::types::FlagsQueryParams;
        use axum::http::HeaderMap;
        use std::net::IpAddr;
        use uuid::Uuid;

        // Helper to evaluate flags
        let evaluate = |body: Bytes| async {
            let context = RequestContext {
                request_id: Uuid::new_v4(),
                state: axum::extract::State(state_for_stream.clone()),
                ip: IpAddr::from([127, 0, 0, 1]),
                headers: HeaderMap::new(),
                meta: FlagsQueryParams {
                    lib_version: None,
                    sent_at: None,
                    only_evaluate_survey_feature_flags: None,
                    version: Some("2".to_string()),
                    config: Some(false),
                    compression: None,
                },
                body,
            };

            process_request(context).await
        };

        // Send connection confirmation (no evaluation yet)
        yield Ok(Event::default()
            .event("connected")
            .data(format!(r#"{{"team_id": {team_id}}}"#)));

        // Stream events from Redis
        loop {
            match tokio::time::timeout(Duration::from_secs(30), rx.recv()).await {
                Ok(Some(event)) => {
                    if evaluations {
                        // Mode 1: Evaluate flags for the user and send results
                        if let Some(ref body) = body_bytes {
                            match evaluate(body.clone()).await {
                                Ok(response) => {
                                    let flag_results = serde_json::json!({
                                        "flags": response.flags,
                                        "errors_while_computing_flags": response.errors_while_computing_flags,
                                    });
                                    if let Ok(data_json) = serde_json::to_string(&flag_results) {
                                        yield Ok(Event::default()
                                            .event("message")
                                            .data(data_json));
                                    } else {
                                        error!("Failed to serialize flag results for team {}", team_id);
                                    }
                                }
                                Err(e) => {
                                    error!("Failed to re-evaluate flags for team {}: {:?}", team_id, e);
                                }
                            }
                        }
                    } else {
                        // Mode 2: Send raw flag data (for local evaluation)
                        if let Ok(data_json) = serde_json::to_string(&event.data) {
                            yield Ok(Event::default()
                                .event("message")
                                .data(data_json));
                        } else {
                            error!("Failed to serialize flag data for team {}", team_id);
                        }
                    }
                }
                Ok(None) => {
                    // Channel closed
                    info!("SSE channel closed for team {}", team_id);
                    break;
                }
                Err(_) => {
                    // Timeout - send heartbeat
                    yield Ok(Event::default().comment("heartbeat"));
                }
            }
        }
    };

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}
