"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from products.signals.backend.implementation_pr import PrCloseReason
from products.signals.backend.models import SignalReport
from products.signals.backend.tasks import close_dismissed_report_pr

_SNOOZE_SOURCE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.RESOLVED})


@receiver(pre_save, sender=SignalReport)
def capture_prior_status_for_pr_close(
    sender: type[SignalReport],
    instance: SignalReport,
    **kwargs: Any,
) -> None:
    """Stash the row's prior status so post_save can tell a real transition from a no-op edit."""
    if instance.pk is None:
        instance._prior_status_for_pr_close = None  # type: ignore[attr-defined]
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields:
        instance._prior_status_for_pr_close = None  # type: ignore[attr-defined]
        return

    instance._prior_status_for_pr_close = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()  # type: ignore[attr-defined]


def _pr_close_reason(
    instance: SignalReport,
    *,
    created: bool,
    update_fields: set[str] | None,
    prior_status: str | None,
) -> PrCloseReason | None:
    if created:
        # Reports born SUPPRESSED by the scout safety/actionability judge never surfaced a PR.
        return None
    # React only to the save that performed the transition, not later edits.
    if update_fields is None or "status" not in update_fields:
        return None

    if instance.status == SignalReport.Status.SUPPRESSED:
        return "suppressed"

    if (
        instance.status == SignalReport.Status.POTENTIAL
        and prior_status in _SNOOZE_SOURCE_STATUSES
    ):
        return "snoozed"

    return None


@receiver(post_save, sender=SignalReport)
def close_pr_when_report_dismissed(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Close the implementation PR when a report is suppressed or snoozed.

    This is the single choke point for the archive→close side effect: every suppression surface
    (Slack, the REST state/bulk-state API, any future one) ends in a ``save`` that flips status
    to SUPPRESSED, and snoozing a ready/resolved report ends in READY/RESOLVED → POTENTIAL, so
    hooking the model here covers them all without each caller opting in.
    """
    prior_status = getattr(instance, "_prior_status_for_pr_close", None)
    reason = _pr_close_reason(
        instance,
        created=created,
        update_fields=update_fields,
        prior_status=prior_status,
    )
    if reason is None:
        return

    team_id = instance.team_id
    report_id = str(instance.id)
    # After commit so a rolled-back transition never closes a PR; best-effort inside the task.
    transaction.on_commit(
        lambda: close_dismissed_report_pr.delay(
            report_id=report_id,
            team_id=team_id,
            reason=reason,
        )
    )
