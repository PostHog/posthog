use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::sse::{Event, KeepAlive, Sse},
};
use futures_util::stream::Stream;
use serde::Deserialize;
use std::convert::Infallible;
use tracing::{error, info, warn};

use crate::router::State as AppState;

#[derive(Debug, Deserialize)]
pub struct SseQueryParams {
    #[serde(alias = "api_key", alias = "$token")]
    pub token: Option<String>,
}

/// SSE endpoint for real-time feature flag definition updates.
///
/// Returns a Server-Sent Events stream that pushes flag definition updates when
/// feature flags are changed for the team. The client is responsible for evaluating
/// the flags locally using the provided definitions.
///
/// Query parameters:
/// - `token` (or `api_key` or `$token`): PostHog API token (required)
///
/// The endpoint:
/// - Authenticates the token to determine the team
/// - Sends connection confirmation on initial connect
/// - Subscribes to Redis Pub/Sub for the team's feature flag updates
/// - When a flag is updated, sends the raw flag definition data
/// - Uses Axum's built-in keep-alive mechanism (sends comment every 15 seconds)
/// - Cleans up subscriptions when the client disconnects
///
/// Event format:
/// ```text
/// event: connected
/// data: {"team_id": 1}
///
/// event: message
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
        state.redis_client.clone(),
        state.dedicated_redis_client.clone(),
        state.database_pools.non_persons_reader.clone(),
        state.config.team_cache_ttl_seconds,
        state.config.flags_cache_ttl_seconds,
        state.config.clone(),
    );

    let team = match flag_service.get_team_from_cache_or_pg(&token).await {
        Ok(team) => team,
        Err(e) => {
            warn!("SSE authentication failed for token: {:?}", e);
            return Err(StatusCode::UNAUTHORIZED);
        }
    };

    let team_id = team.id;

    info!("New SSE connection for team {}", team_id);

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

    // Create SSE stream
    // Note: KeepAlive::default() handles connection keep-alive by sending comments every 15 seconds.
    let stream = async_stream::stream! {
        // Send connection confirmation
        yield Ok(Event::default()
            .event("connected")
            .data(format!(r#"{{"team_id": {team_id}}}"#)));

        // Stream events from Redis
        while let Some(event) = rx.recv().await {
            // Send raw flag definition data
            if let Ok(data_json) = serde_json::to_string(&event.data) {
                yield Ok(Event::default()
                    .event("message")
                    .data(data_json));
            } else {
                error!("Failed to serialize flag data for team {}", team_id);
            }
        }

        info!("SSE channel closed for team {}", team_id);
    };

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}
