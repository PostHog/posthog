use crate::{api::errors::FlagError, flags::flag_request::FlagRequest, team::team_models::Team};
use axum::http::{header::ORIGIN, header::USER_AGENT};
use chrono;
use common_cookieless::{CookielessServerHashMode, EventData, TeamData};

use super::types::RequestContext;

pub async fn handle_distinct_id(
    context: &RequestContext,
    request: &FlagRequest,
    team: &Team,
    distinct_id: String,
) -> Result<String, FlagError> {
    let event_data = EventData {
        ip: &context.ip.to_string(),
        timestamp_ms: context
            .meta
            .sent_at
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis()) as u64,
        host: context
            .headers
            .get(ORIGIN)
            .map(|h| h.to_str().unwrap_or(""))
            .unwrap_or(""),
        user_agent: context
            .headers
            .get(USER_AGENT)
            .map(|h| h.to_str().unwrap_or(""))
            .unwrap_or(""),
        event_time_zone: request.timezone.as_deref(),
        hash_extra: request.cookieless_hash_extra.as_deref(),
        distinct_id: &distinct_id,
    };

    let team_data = TeamData {
        team_id: team.id,
        timezone: team.timezone.clone(),
        cookieless_server_hash_mode: CookielessServerHashMode::from(
            team.cookieless_server_hash_mode,
        ),
    };

    context
        .state
        .cookieless_manager
        .compute_cookieless_distinct_id(event_data, team_data)
        .await
        .map_err(FlagError::CookielessError)
}
