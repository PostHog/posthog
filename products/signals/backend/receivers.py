"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

from typing import Any, cast

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from products.signals.backend.models import SignalReport
from products.signals.backend.tasks import close_dismissed_report_pr

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=SignalReport)
def close_pr_when_report_dismissed(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    """Close the implementation PR when a report is dismissed (transitioned into SUPPRESSED).

    This is the single choke point for the dismiss→close side effect: every dismissal surface
    (Slack, the REST state/bulk-state API, any future one) ends in a ``save`` that flips status
    to SUPPRESSED, so hooking the model here covers them all without each caller opting in.
    """
    if created:
        # Reports born SUPPRESSED by the scout safety/actionability judge never surfaced a PR.
        return
    if instance.status != SignalReport.Status.SUPPRESSED:
        return
    # React only to the save that performed the transition, not later edits of an
    # already-suppressed report. Dismissals always save with update_fields (from transition_to).
    if update_fields is None or "status" not in update_fields:
        return

    team_id = instance.team_id
    report_id = str(instance.id)
    # After commit so a rolled-back dismissal never closes a PR; best-effort inside the task.
    transaction.on_commit(lambda: cast(Any, close_dismissed_report_pr).delay(report_id=report_id, team_id=team_id))
