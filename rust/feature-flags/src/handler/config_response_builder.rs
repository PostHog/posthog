use crate::{
    api::{
        errors::FlagError,
        types::{FlagsResponse, SessionRecordingField},
    },
    config_cache::get_cached_config,
    team::team_models::Team,
};
use limiters::redis::QuotaResource;

use super::types::RequestContext;

/// Build response using cached config from Python's HyperCache.
///
/// This function reads the pre-computed config blob from Python's
/// RemoteConfig.build_config() stored in HyperCache.
///
/// Session recording quota checks are performed in Rust because
/// Python caches config without per-request quota state.
pub async fn build_response_from_cache(
    flags_response: FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<FlagsResponse, FlagError> {
    let mut response = flags_response;

    if !context.meta.config.unwrap_or(false) {
        return Ok(response);
    }

    let cached_config = get_cached_config(&context.state.config_hypercache_reader, &team.api_token)
        .await?
        .ok_or_else(|| {
            FlagError::Internal(format!(
                "Config cache miss for team {} - Python has not populated the cache",
                team.id
            ))
        })?;

    let is_recordings_limited = if context.state.config.flags_session_replay_quota_check {
        context
            .state
            .session_replay_billing_limiter
            .is_limited(&team.api_token)
            .await
    } else {
        false
    };

    response.config = cached_config.clone().into();

    if is_recordings_limited {
        apply_recordings_quota_limit(&mut response, cached_config.quota_limited);
    } else {
        response.quota_limited = cached_config.quota_limited;
    }

    tracing::debug!(team_id = team.id, "Used cached config from HyperCache");

    Ok(response)
}

/// Apply session recording quota limit by disabling recording and updating quota_limited array.
fn apply_recordings_quota_limit(
    response: &mut FlagsResponse,
    existing_quota_limited: Option<Vec<String>>,
) {
    response.config.session_recording = Some(SessionRecordingField::Disabled(false));

    let mut limited = existing_quota_limited.unwrap_or_default();
    let recordings_str = QuotaResource::Recordings.as_str().to_string();
    if !limited.contains(&recordings_str) {
        limited.push(recordings_str);
    }
    response.quota_limited = Some(limited);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::cached_remote_config::CachedRemoteConfig;
    use crate::api::types::ConfigResponse;
    use crate::api::types::SessionRecordingField;
    use std::collections::HashMap;
    use uuid::Uuid;

    fn create_base_response() -> FlagsResponse {
        FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4())
    }

    #[test]
    fn test_apply_recordings_quota_limit_adds_to_empty() {
        let mut response = create_base_response();
        apply_recordings_quota_limit(&mut response, None);

        assert!(matches!(
            response.config.session_recording,
            Some(SessionRecordingField::Disabled(false))
        ));
        assert_eq!(response.quota_limited, Some(vec!["recordings".to_string()]));
    }

    #[test]
    fn test_apply_recordings_quota_limit_merges_existing() {
        let mut response = create_base_response();
        apply_recordings_quota_limit(&mut response, Some(vec!["feature_flags".to_string()]));

        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string(), "recordings".to_string()])
        );
    }

    #[test]
    fn test_apply_recordings_quota_limit_no_duplicate() {
        let mut response = create_base_response();
        apply_recordings_quota_limit(&mut response, Some(vec!["recordings".to_string()]));

        assert_eq!(response.quota_limited, Some(vec!["recordings".to_string()]));
    }

    #[test]
    fn test_cached_config_converts_to_config_response() {
        let cached = CachedRemoteConfig {
            supported_compression: Some(vec!["gzip".to_string()]),
            heatmaps: Some(true),
            default_identified_only: Some(true),
            ..Default::default()
        };

        let config: ConfigResponse = cached.into();

        assert_eq!(config.supported_compression, vec!["gzip".to_string()]);
        assert_eq!(config.heatmaps, Some(true));
        assert_eq!(config.default_identified_only, Some(true));
    }
}
