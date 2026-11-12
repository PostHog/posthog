from django.db.models import QuerySet

from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationResolutionState as ResolutionState,
)

from posthog.models.utils import strict_fetch

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
    team_id: int, identity: MarketingAnalyticsRecommendationIdentity, resolution: ResolutionState, user_id: int
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


def resolutions_page(team_id: int, *, limit: int, offset: int) -> tuple[list[RecommendationResolution], int]:
    rows: QuerySet[RecommendationResolution] = strict_fetch(
        RecommendationResolution.objects.for_team(team_id).select_related("resolved_by")
    )
    return list(rows.order_by("-resolved_at", "id")[offset : offset + limit]), rows.count()
