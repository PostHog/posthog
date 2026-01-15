from django.db.models import Q

import structlog
import posthoganalytics
from celery import shared_task

from posthog.models import Team

from products.surveys.backend.models import SurveyRecommendation

logger = structlog.get_logger(__name__)

SURVEY_RECOMMENDATIONS_FEATURE_FLAG = "survey-recommendations"


@shared_task(ignore_result=True, max_retries=1)
def generate_survey_recommendations_for_team(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("Team not found for survey recommendations", team_id=team_id)
        return

    try:
        from products.surveys.backend.recommendations import generate_recommendations

        saved_count = generate_recommendations(team)

        logger.info(
            "Survey recommendations generated",
            team_id=team_id,
            saved_count=saved_count,
        )

    except Exception as e:
        logger.exception(
            "Failed to generate survey recommendations",
            team_id=team_id,
            error=str(e),
        )
        raise


@shared_task(ignore_result=True)
def generate_survey_recommendations_for_all_teams() -> None:
    from posthog.caching.utils import active_teams

    team_ids = active_teams()
    teams = Team.objects.filter(id__in=team_ids).only("id", "organization_id")

    enabled_teams = [
        team
        for team in teams
        if posthoganalytics.feature_enabled(
            SURVEY_RECOMMENDATIONS_FEATURE_FLAG,
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    ]

    logger.info(
        "Scheduling survey recommendations for teams",
        total_active_teams=len(team_ids),
        enabled_teams=len(enabled_teams),
    )

    for i, team in enumerate(enabled_teams):
        delay_seconds = i * 30
        generate_survey_recommendations_for_team.apply_async(
            args=[team.id],
            countdown=delay_seconds,
        )


@shared_task(ignore_result=True)
def cleanup_stale_recommendations() -> None:
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    cutoff = now - timedelta(days=30)

    orphaned_count = (
        SurveyRecommendation.objects.filter(
            status=SurveyRecommendation.Status.ACTIVE,
        )
        .filter(
            Q(source_insight__isnull=False, source_insight__deleted=True)
            | Q(source_feature_flag__isnull=False, source_feature_flag__deleted=True)
            | Q(source_experiment__isnull=False, source_experiment__feature_flag__deleted=True)
        )
        .update(
            status=SurveyRecommendation.Status.DISMISSED,
            dismissed_at=now,
        )
    )

    if orphaned_count:
        logger.info("Dismissed orphaned survey recommendations", count=orphaned_count)

    stale_count = SurveyRecommendation.objects.filter(
        status=SurveyRecommendation.Status.ACTIVE,
        created_at__lt=cutoff,
    ).update(
        status=SurveyRecommendation.Status.DISMISSED,
        dismissed_at=now,
    )

    if stale_count:
        logger.info("Dismissed stale survey recommendations", count=stale_count)
