use crate::{
    api::{
        errors::FlagError,
        types::{FlagsQueryParams, FlagsResponse},
    },
    flags::{
        flag_analytics::SURVEY_TARGETING_FLAG_PREFIX,
        flag_models::{FeatureFlag, FeatureFlagList},
        flag_request::FlagRequest,
        flag_service::FlagService,
    },
};
use axum::extract::State;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use uuid::Uuid;

use super::{evaluation, types::FeatureFlagEvaluationContext};
use crate::router;

pub async fn fetch_and_filter(
    flag_service: &FlagService,
    project_id: i64,
    request: &FlagRequest,
    query_params: &FlagsQueryParams,
) -> Result<FeatureFlagList, FlagError> {
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    let flags_after_survey_filter = filter_survey_flags(
        all_flags.flags,
        query_params
            .only_evaluate_survey_feature_flags
            .unwrap_or(false),
    );

    let final_filtered_flags =
        filter_by_requested_keys(flags_after_survey_filter, request.flag_keys.as_deref());

    Ok(FeatureFlagList::new(final_filtered_flags))
}

/// Filters flags to only include survey flags if requested
/// This field is optional, passed in as a query param, and defaults to false
fn filter_survey_flags(flags: Vec<FeatureFlag>, only_survey_flags: bool) -> Vec<FeatureFlag> {
    if only_survey_flags {
        flags
            .into_iter()
            .filter(|flag| flag.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
            .collect()
    } else {
        flags
    }
}

/// Filters flags to only include those with keys in the requested set
/// This field is optional, passed in as part of the request body, and if it is not provided, we return all flags
fn filter_by_requested_keys(
    flags: Vec<FeatureFlag>,
    requested_keys: Option<&[String]>,
) -> Vec<FeatureFlag> {
    if let Some(keys) = requested_keys {
        let requested_keys_set: HashSet<String> = keys.iter().cloned().collect();
        flags
            .into_iter()
            .filter(|flag| requested_keys_set.contains(&flag.key))
            .collect()
    } else {
        flags
    }
}

#[allow(clippy::too_many_arguments)]
pub async fn evaluate_for_request(
    state: &State<router::State>,
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    filtered_flags: FeatureFlagList,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
    hash_key_override: Option<String>,
    request_id: Uuid,
    disable_flags: bool,
) -> FlagsResponse {
    // If flags are disabled, return empty FlagsResponse
    if disable_flags {
        return FlagsResponse::new(false, HashMap::new(), None, request_id);
    }

    if filtered_flags.flags.is_empty() {
        return FlagsResponse::new(false, HashMap::new(), None, request_id);
    }

    let ctx = FeatureFlagEvaluationContext {
        team_id,
        project_id,
        distinct_id,
        feature_flags: filtered_flags,
        reader: state.reader.clone(),
        writer: state.writer.clone(),
        cohort_cache: state.cohort_cache_manager.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
    };

    evaluation::evaluate_feature_flags(ctx, request_id).await
}
