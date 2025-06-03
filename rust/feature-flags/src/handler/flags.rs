use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    flags::{flag_models::FeatureFlagList, flag_request::FlagRequest, flag_service::FlagService},
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
) -> Result<FeatureFlagList, FlagError> {
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;
    if let Some(flag_keys) = &request.flag_keys {
        let keys: HashSet<String> = flag_keys.iter().cloned().collect();
        let filtered = all_flags
            .flags
            .into_iter()
            .filter(|f| keys.contains(&f.key))
            .collect();
        Ok(FeatureFlagList::new(filtered))
    } else {
        Ok(all_flags)
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
) -> FlagsResponse {
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
