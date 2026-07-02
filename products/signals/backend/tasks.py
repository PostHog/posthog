import structlog
from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.signals.backend.implementation_pr import close_implementation_pr_for_report

logger = structlog.get_logger(__name__)


@shared_task(
    name="products.signals.backend.tasks.close_dismissed_report_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def close_dismissed_report_pr(report_id: str, team_id: int) -> None:
    """Comment on and close the implementation PR of a dismissed report. Best-effort — the helper
    swallows its own errors, so a missing PR / integration or a GitHub failure is a no-op."""
    close_implementation_pr_for_report(team_id, report_id)
