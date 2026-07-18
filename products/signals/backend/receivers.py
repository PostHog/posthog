"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.implementation_pr import PrCloseReason
from products.signals.backend.models import SignalReport
from products.signals.backend.tasks import close_dismissed_report_pr

logger = structlog.get_logger(__name__)

_SNOOZE_SOURCE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.RESOLVED})


@receiver(pre_save, sender=SignalReport)
def capture_prior_status(
    sender: type[SignalReport],
    instance: SignalReport,
    **kwargs: Any,
) -> None:
    """Stash the row's prior status so post_save receivers can tell a real transition from a no-op edit."""
    # UUIDModel PKs carry a Python-side default, so pk is set at construction, never None — use
    # _state.adding to tell an unsaved row (no prior status) from an update.
    if instance._state.adding:
        instance._prior_status = None  # type: ignore[attr-defined]
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields:
        instance._prior_status = None  # type: ignore[attr-defined]
        return

    instance._prior_status = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()  # type: ignore[attr-defined]


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
    if update_fields is not None and "status" not in update_fields:
        return None
    if prior_status is None or prior_status == instance.status:
        return None

    if instance.status == SignalReport.Status.SUPPRESSED:
        return "suppressed"

    if instance.status == SignalReport.Status.POTENTIAL and prior_status in _SNOOZE_SOURCE_STATUSES:
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
    prior_status = getattr(instance, "_prior_status", None)
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


@receiver(post_save, sender=SignalReport)
def capture_status_change_analytics(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Emit `signal_report_status_changed` for every real status transition.

    This is the server-side label stream for the inbox ranking model: every transition surface
    (REST state/bulk-state, Slack dismissal, the pipeline, PR-merge resolution in the tasks
    webhook) ends in a ``save`` that flips status, so hooking the model here yields one complete,
    client-independent record of outcomes (resolved / suppressed / snoozed / …) per report.
    """
    if created:
        return
    if update_fields is not None and "status" not in update_fields:
        return
    prior_status = getattr(instance, "_prior_status", None)
    if prior_status is None or prior_status == instance.status:
        return

    # Snapshot now — the instance may be mutated again before the commit callback runs.
    properties = {
        "team_id": instance.team_id,
        "report_id": str(instance.id),
        "previous_status": prior_status,
        "status": instance.status,
        "signal_count": instance.signal_count,
        "total_weight": instance.total_weight,
        "run_count": instance.run_count,
        "report_created_at": instance.created_at.isoformat() if instance.created_at else None,
        "promoted_at": instance.promoted_at.isoformat() if instance.promoted_at else None,
    }
    report_id = str(instance.id)
    team = instance.team

    def _capture() -> None:
        try:
            posthoganalytics.capture(
                event="signal_report_status_changed",
                distinct_id=str(team.uuid),
                properties=properties,
                groups=groups(team.organization, team),
            )
        except Exception:
            # Analytics must never break the transition that triggered it.
            logger.exception("Failed to capture signal_report_status_changed", report_id=report_id)

    # After commit so a rolled-back transition never emits a phantom label.
    transaction.on_commit(_capture)
