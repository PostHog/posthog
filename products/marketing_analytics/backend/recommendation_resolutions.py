from django.db.models import QuerySet

from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolutionState as ResolutionState,
)

from posthog.models.utils import strict_fetch

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import validate_identity
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution, subject_hash


def resolve(
    team_id: int,
    identity: MarketingAnalyticsRecommendationIdentity,
    resolution: ResolutionState,
    user_id: int,
    name: str,
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
        defaults={"name": name, "resolution": resolution, "resolved_by_id": user_id},
        create_defaults={
            "subject": identity.subject,
            "name": name,
            "resolution": resolution,
            "resolved_by_id": user_id,
        },
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
