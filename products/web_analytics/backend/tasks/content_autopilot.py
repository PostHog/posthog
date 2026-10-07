import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.models.scoping import with_team_scope
from posthog.tasks.utils import CeleryQueue

from products.web_analytics.backend.content_autopilot.generation import (
    ProposalMode,
    finish_timed_out_run,
    generate_run,
    process_proposal,
)

logger = structlog.get_logger(__name__)

RUN_SOFT_TIME_LIMIT_SECONDS = 60 * 60
PROPOSAL_SOFT_TIME_LIMIT_SECONDS = 30 * 60
HARD_TIME_LIMIT_GRACE_SECONDS = 120


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=RUN_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RUN_SOFT_TIME_LIMIT_SECONDS + HARD_TIME_LIMIT_GRACE_SECONDS,
)
@with_team_scope()
def generate_content_autopilot_run_task(team_id: int, run_id: str) -> None:
    try:
        generate_run(team_id, run_id)
    except SoftTimeLimitExceeded:
        logger.warning("content_autopilot_run_timed_out", team_id=team_id, run_id=run_id)
        finish_timed_out_run(team_id, run_id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=PROPOSAL_SOFT_TIME_LIMIT_SECONDS,
    time_limit=PROPOSAL_SOFT_TIME_LIMIT_SECONDS + HARD_TIME_LIMIT_GRACE_SECONDS,
)
@with_team_scope()
def process_content_autopilot_proposal_task(team_id: int, proposal_id: str, mode: ProposalMode) -> None:
    process_proposal(team_id, proposal_id, mode)
