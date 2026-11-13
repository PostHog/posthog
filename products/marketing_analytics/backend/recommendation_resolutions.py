from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolutionState as ResolutionState,
)

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import validate_identity
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution, subject_hash


def resolve(
    team_id: int,
    identity: MarketingAnalyticsRecommendationIdentity,
    resolution: ResolutionState,
    user_id: int,
) -> tuple[RecommendationResolution, bool]:
    validate_identity(identity)
    # Resolving a recommendation again, for example from another tab, replaces the earlier resolution.
    return RecommendationResolution.objects.for_team(team_id).update_or_create(
        team_id=team_id,
        rule=identity.rule,
        source_type=identity.source_type,
        customer_id=identity.customer_id,
        campaign_id=identity.campaign_id,
        subject_hash=subject_hash(identity.subject),
        defaults={"resolution": resolution, "resolved_by_id": user_id},
        create_defaults={"subject": identity.subject, "resolution": resolution, "resolved_by_id": user_id},
    )


def restore(team_id: int, resolution_id: str) -> bool:
    resolution = RecommendationResolution.objects.for_team(team_id).filter(id=resolution_id).first()
    if resolution is None:
        return False
    # A hard delete through the instance, so the activity log records the restore.
    resolution.delete()
    return True
