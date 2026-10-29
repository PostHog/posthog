from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models import Team, User
from posthog.models.scoping import with_team_scope

from products.marketing_analytics.backend.models.conversion_setup import ConversionRecommendationRun


@shared_task(
    ignore_result=True, max_retries=0, soft_time_limit=150, time_limit=180, queue=CeleryQueue.ANALYTICS_LIMITED.value
)
@with_team_scope()
def generate_conversion_recommendations(team_id: int, run_id: str) -> None:
    from products.marketing_analytics.backend.services.conversion_recommendations import (
        ConversionRecommendationService,  # noqa: PLC0415 — keeps query dependencies off Celery startup
    )

    run = ConversionRecommendationRun.objects.for_team(team_id).filter(pk=run_id).first()
    if run is None:
        return
    team = Team.objects.get(pk=team_id)
    user = User.objects.filter(pk=run.requested_by_id).first()
    if user is None:
        ConversionRecommendationRun.objects.for_team(team_id).filter(pk=run_id).update(
            status=ConversionRecommendationRun.Status.FAILED,
            completed_at=timezone.now(),
            error="The requesting user no longer has access. Sign in with an active account and scan again.",
        )
        return
    ConversionRecommendationService(team, user).execute(run_id)
