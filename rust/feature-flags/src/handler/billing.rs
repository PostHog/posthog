use crate::{
    api::{
        errors::FlagError,
        types::{ConfigResponse, FlagsResponse},
    },
    flags::{
        flag_analytics::{increment_request_count, SURVEY_TARGETING_FLAG_PREFIX},
        flag_models::FeatureFlagList,
        flag_request::FlagRequestType,
    },
};
use common_metrics::inc;
use limiters::redis::ServiceName;
use std::collections::HashMap;

use super::types::RequestContext;

pub async fn check_limits(
    context: &RequestContext,
    verified_token: &str,
) -> Result<Option<FlagsResponse>, FlagError> {
    let billing_limited = context
        .state
        .billing_limiter
        .is_limited(verified_token)
        .await;

    if billing_limited {
        return Ok(Some(FlagsResponse {
            errors_while_computing_flags: false,
            flags: HashMap::new(),
            quota_limited: Some(vec![ServiceName::FeatureFlags.as_string()]),
            request_id: context.request_id,
            config: ConfigResponse::default(),
        }));
    }
    Ok(None)
}

pub async fn record_usage(
    context: &RequestContext,
    filtered_flags: &FeatureFlagList,
    team_id: i32,
) {
    if filtered_flags
        .flags
        .iter()
        .all(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
    {
        if let Err(e) = increment_request_count(
            context.state.redis.clone(),
            team_id,
            1,
            FlagRequestType::Decide,
        )
        .await
        {
            inc(
                "flag_request_redis_error",
                &[("error".to_string(), e.to_string())],
                1,
            );
        }
    }
}
