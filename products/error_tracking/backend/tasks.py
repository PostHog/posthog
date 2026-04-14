import structlog
from celery import shared_task

from posthog.models.team.team import Team
from posthog.tasks.utils import CeleryQueue

from products.error_tracking.backend.models import ErrorTrackingRecommendationRun
from products.error_tracking.backend.recommendations import ALL_RECOMMENDATIONS, RECOMMENDATIONS_BY_TYPE

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def run_error_tracking_recommendation(team_id: int, recommendation_type: str) -> None:
    """Compute a single recommendation for a team and upsert the materialized row."""
    recommendation_cls = RECOMMENDATIONS_BY_TYPE.get(recommendation_type)
    if recommendation_cls is None:
        logger.warning(
            "error_tracking_recommendation_unknown_type",
            team_id=team_id,
            recommendation_type=recommendation_type,
        )
        return

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.info("error_tracking_recommendation_team_missing", team_id=team_id)
        return

    meta = recommendation_cls.compute(team)
    ErrorTrackingRecommendationRun.objects.update_or_create(
        team_id=team_id,
        type=recommendation_type,
        defaults={"meta": meta},
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def run_all_error_tracking_recommendations() -> None:
    """Recompute all recommendations for every team that has at least one recommendation row."""
    team_ids = ErrorTrackingRecommendationRun.objects.values_list("team_id", flat=True).distinct()
    for team_id in team_ids:
        for recommendation in ALL_RECOMMENDATIONS:
            run_error_tracking_recommendation.delay(team_id, recommendation.type)
