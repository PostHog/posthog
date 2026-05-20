use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    database::PostgresRouter,
    flags::flag_matching::FeatureFlagMatcher,
};
use uuid::Uuid;

use super::types::FeatureFlagEvaluationContext;

/// Evaluates all requested feature flags in the provided context, returning a [`FlagsResponse`].
pub async fn evaluate_feature_flags(
    context: FeatureFlagEvaluationContext,
    request_id: Uuid,
) -> Result<FlagsResponse, FlagError> {
    // Create router from the context
    let router = PostgresRouter::new(
        context.persons_reader,
        context.persons_writer,
        context.non_persons_reader,
        context.non_persons_writer,
    );

    let mut matcher = FeatureFlagMatcher::new(
        context.distinct_id,
        context.device_id,
        context.team_id,
        router,
        context.cohort_cache,
        context.group_type_cache,
        context.groups,
    )
    .with_cohort_membership_provider(context.cohort_membership_provider)
    .with_parallel_eval_threshold(context.parallel_eval_threshold)
    .with_rayon_dispatcher(context.rayon_dispatcher)
    .with_skip_writes(context.skip_writes)
    .with_realtime_cohort_evaluation(context.enable_realtime_cohort_evaluation)
    .with_detailed_analysis(context.detailed_analysis)
    .with_only_use_override_person_properties(context.only_use_override_person_properties);

    matcher
        .evaluate_all_feature_flags(
            context.feature_flags,
            context.person_property_overrides,
            context.group_property_overrides,
            context.hash_key_override, // Aka $anon_distinct_id
            request_id,
            context.flag_keys,
            context.optimize_experience_continuity_lookups,
        )
        .await
}
