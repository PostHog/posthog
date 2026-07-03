from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report


@shared_task(
    name="products.signals.backend.tasks.close_dismissed_report_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def close_dismissed_report_pr(report_id: str, team_id: int, reason: PrCloseReason = "suppressed") -> None:
    close_implementation_pr_for_report(team_id, report_id, reason=reason)
