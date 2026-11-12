from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationResolutionState as ResolutionState,
)

from posthog.models.scoping.manager import resolve_effective_team_id

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import (
    RecommendationKey,
    validate_identity,
)
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution, subject_hash


def resolutions_by_key(team_id: int) -> dict[str, MarketingAnalyticsRecommendationResolution]:
    rows = RecommendationResolution.objects.for_team(team_id).values_list(
        "id",
        "rule",
        "source_type",
        "customer_id",
        "campaign_id",
        "subject",
        "resolution",
        "resolved_at",
        named=True,
    )
    return {
        RecommendationKey.from_fields(row).encoded: MarketingAnalyticsRecommendationResolution(
            id=str(row.id), resolution=ResolutionState(row.resolution), resolved_at=row.resolved_at.isoformat()
        )
        for row in rows
    }


def resolve(
    team_id: int,
    identity: MarketingAnalyticsRecommendationIdentity,
    resolution: ResolutionState,
    user_id: int,
) -> tuple[RecommendationResolution, bool]:
    validate_identity(identity)
    # Resolving a recommendation again, for example from another tab, replaces the earlier resolution.
    # Resolutions belong to the project, so a child environment writes the parent's row.
    project_id = resolve_effective_team_id(team_id)
    return RecommendationResolution.objects.for_team(project_id, canonical=True).update_or_create(
        team_id=project_id,
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
