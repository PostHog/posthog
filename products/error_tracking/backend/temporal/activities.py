import dataclasses

from django.utils import timezone

import structlog
from temporalio import activity

from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingRecommendationRun, ErrorTrackingRecommendationSettings
from products.error_tracking.backend.recommendations import cross_sell

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class StaleRecommendation:
    team_id: int
    recommendation_type: str


@activity.defn
async def get_stale_recommendations_activity() -> list[StaleRecommendation]:
    """Find all recommendation rows whose updated_at is older than the cross-sell interval."""
    cutoff = timezone.now() - cross_sell.RECOMMENDATION_INTERVAL

    disabled_team_ids = set(
        ErrorTrackingRecommendationSettings.objects.filter(enabled=False).values_list("team_id", flat=True)
    )

    team_ids = list(
        ErrorTrackingRecommendationRun.objects.filter(
            type=cross_sell.RECOMMENDATION_TYPE,
            updated_at__lt=cutoff,
        )
        .exclude(team_id__in=disabled_team_ids)
        .values_list("team_id", flat=True)
    )

    return [StaleRecommendation(team_id=tid, recommendation_type=cross_sell.RECOMMENDATION_TYPE) for tid in team_ids]


@dataclasses.dataclass
class ComputeRecommendationInput:
    team_id: int
    recommendation_type: str


@activity.defn
async def compute_recommendation_activity(input: ComputeRecommendationInput) -> bool:
    """Compute a single recommendation for a team and upsert the row."""
    if input.recommendation_type != cross_sell.RECOMMENDATION_TYPE:
        logger.warning(
            "error_tracking_recommendation_unknown_type",
            team_id=input.team_id,
            recommendation_type=input.recommendation_type,
        )
        return False

    try:
        team = await Team.objects.aget(id=input.team_id)
    except Team.DoesNotExist:
        logger.info("error_tracking_recommendation_team_missing", team_id=input.team_id)
        return False

    meta = cross_sell.compute(team)
    await ErrorTrackingRecommendationRun.objects.aupdate_or_create(
        team_id=input.team_id,
        type=input.recommendation_type,
        defaults={"meta": meta},
    )
    return True
