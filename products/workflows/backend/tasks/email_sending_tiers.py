from uuid import uuid4

import structlog
from celery import shared_task

from posthog.models.activity_logging.activity_log import Trigger
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.email_sending_tier import (
    raise_trusted_floor_for_team,
    recompute_email_sending_tiers,
)
from products.workflows.backend.services.email_sending_tier_audit import EMAIL_SENDING_TIER_SWEEP_JOB_TYPE
from products.workflows.backend.services.email_sending_tier_notifications import notify_email_sending_tier_changes

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def recompute_workflows_email_sending_tiers() -> None:
    """Move each team at most one trust tier, based on how much workflow email it sent and how
    clean the sending was. Runs in every rollout mode: tiers are stored before anything reads them,
    so enforcement can be switched on against a settled distribution."""
    # One job id groups every audit row this run writes.
    decisions = recompute_email_sending_tiers(
        trigger=Trigger(job_type=EMAIL_SENDING_TIER_SWEEP_JOB_TYPE, job_id=str(uuid4()), payload={})
    )
    notify_email_sending_tier_changes(decisions)
    logger.info(
        "workflows_email_sending_tier_sweep_finished",
        evaluated_teams=len(decisions),
        changed_teams=sum(1 for decision in decisions if decision.changed),
        promoted=sum(1 for decision in decisions if decision.new_tier > decision.previous_tier),
        demoted=sum(1 for decision in decisions if decision.new_tier < decision.previous_tier),
    )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=5,
    retry_jitter=True,
)
@skip_team_scope_audit
def raise_trusted_email_sending_tier_floor(team_id: int) -> None:
    """Queued when AWS first reports a team's tenant as healthy, so a trusted account gets its floor
    before its first send. The daily sweep applies the same rule if every retry fails."""
    raise_trusted_floor_for_team(team_id)
