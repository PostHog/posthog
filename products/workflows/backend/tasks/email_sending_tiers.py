import structlog
from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.email_sending_tier import recompute_email_sending_tiers
from products.workflows.backend.services.email_sending_tier_notifications import notify_email_sending_tier_changes

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def recompute_workflows_email_sending_tiers() -> None:
    """Move each team at most one trust tier, based on how much workflow email it sent and how
    clean the sending was. Runs in every rollout mode: tiers are stored before anything reads them,
    so enforcement can be switched on against a settled distribution."""
    decisions = recompute_email_sending_tiers()
    notify_email_sending_tier_changes(decisions)
    logger.info(
        "workflows_email_sending_tier_sweep_finished",
        evaluated_teams=len(decisions),
        changed_teams=sum(1 for decision in decisions if decision.changed),
        promoted=sum(1 for decision in decisions if decision.new_tier > decision.previous_tier),
        demoted=sum(1 for decision in decisions if decision.new_tier < decision.previous_tier),
    )
