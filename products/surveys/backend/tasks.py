import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.surveys.backend.desktop_feedback import sweep_expired_desktop_feedback_media
from products.surveys.backend.global_cooldown import sync_survey_wait_period_flags

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sweep_expired_desktop_feedback_media_task() -> None:
    sweep_expired_desktop_feedback_media()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def sync_team_survey_wait_period_flags(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    if not sync_survey_wait_period_flags(team):
        # The value kept changing during this sync, so an older pass can have written the last flags.
        sync_team_survey_wait_period_flags.delay(team_id)
