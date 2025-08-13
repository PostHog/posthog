use crate::{
    api::types::FlagsResponse,
    flags::{flag_group_type_mapping::GroupTypeMappingCache, flag_matching::FeatureFlagMatcher},
};
use uuid::Uuid;

use super::types::FeatureFlagEvaluationContext;

/// Evaluates all requested feature flags in the provided context, returning a [`FlagsResponse`].
pub async fn evaluate_feature_flags(
    context: FeatureFlagEvaluationContext,
    request_id: Uuid,
) -> FlagsResponse {
    let group_type_mapping_cache = GroupTypeMappingCache::new(context.project_id);

    let mut matcher = FeatureFlagMatcher::new(
        context.distinct_id,
        context.team_id,
        context.project_id,
        context.reader,
        context.writer,
        context.cohort_cache,
        Some(group_type_mapping_cache),
        context.groups,
    );

    matcher
        .evaluate_all_feature_flags(
            context.feature_flags,
            context.person_property_overrides,
            context.group_property_overrides,
            context.hash_key_override,
            request_id,
            context.flag_keys,
        )
        .await
}
