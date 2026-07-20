"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

import json
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.implementation_pr import PrCloseReason
from products.signals.backend.models import SignalReport, SignalReportArtefact
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
    new_status = instance.status
    team = instance.team
    transition_at = timezone.now()

    def _capture() -> None:
        try:
            # A single transaction can save the report through several statuses (e.g. ready →
            # candidate on re-promotion in mark_report_ready_activity), queuing one callback per
            # intermediate snapshot. Only the transition matching the durable, committed status
            # emits — transient intermediate labels would corrupt the training stream. The skipped
            # callback stashes its prior status on the shared instance so the emitting one reports
            # the committed transition (in_progress → candidate), not a phantom hop through a
            # state that never committed (ready → candidate).
            current_status = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
            if current_status != new_status:
                if getattr(instance, "_collapsed_prior_status", None) is None:
                    instance._collapsed_prior_status = properties["previous_status"]  # type: ignore[attr-defined]
                return
            collapsed_prior = getattr(instance, "_collapsed_prior_status", None)
            instance._collapsed_prior_status = None  # type: ignore[attr-defined]
            previous_status = collapsed_prior or properties["previous_status"]
            posthoganalytics.capture(
                event="signal_report_status_changed",
                distinct_id=str(team.uuid),
                properties={
                    **properties,
                    "previous_status": previous_status,
                    **_classification_snapshot(
                        report_id,
                        include_dismissal=_is_dismissal_transition(previous_status, new_status),
                        transition_at=transition_at,
                    ),
                },
                groups=groups(team.organization, team),
            )
        except Exception:
            # Analytics must never break the transition that triggered it.
            logger.exception("Failed to capture signal_report_status_changed", report_id=report_id)

    # After commit so a rolled-back transition never emits a phantom label. Post-commit also means
    # artefacts written in the same transaction (e.g. the dismissal) are visible to the snapshot.
    transaction.on_commit(_capture)


# Latest-wins artefact values snapshotted onto `signal_report_status_changed`. Captured with the
# event because artefacts can be re-judged or edited later — a training join by report_id after
# the fact could otherwise see different values than existed when the transition happened.
_SNAPSHOT_ARTEFACT_FIELDS = [
    (SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, "priority", "priority"),
    (SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, "actionability", "actionability"),
    (SignalReportArtefact.ArtefactType.DISMISSAL, "reason", "dismissal_reason"),
]


def _is_dismissal_transition(previous_status: str, new_status: str) -> bool:
    """Whether this transition is one the state API writes dismissal feedback for: a dismissal
    (into suppressed) or a snooze (researched report back to potential)."""
    return new_status == SignalReport.Status.SUPPRESSED or (
        new_status == SignalReport.Status.POTENTIAL and previous_status in _SNOOZE_SOURCE_STATUSES
    )


# A dismissal artefact only counts as this transition's feedback if it was written around the
# transition itself (same request/transaction). Generous so request ordering and clock skew never
# exclude genuine feedback; a dismiss → restore → re-dismiss inside one minute is the only
# (negligible) false-inclusion window.
_DISMISSAL_FRESHNESS = timedelta(minutes=1)


def _classification_snapshot(
    report_id: str, *, include_dismissal: bool, transition_at: datetime
) -> dict[str, str | None]:
    # One DISTINCT ON query for all three types: the bulk-state endpoint can transition up to 100
    # reports in a request, and each one's post-commit callback takes this path before the
    # response returns, so per-type queries would multiply into hundreds.
    latest_by_type = {
        row[0]: (row[1], row[2])
        for row in SignalReportArtefact.objects.filter(
            report_id=report_id, type__in=[artefact_type for artefact_type, _, _ in _SNAPSHOT_ARTEFACT_FIELDS]
        )
        .order_by("type", "-created_at")
        .distinct("type")
        .values_list("type", "content", "created_at")
    }
    snapshot: dict[str, str | None] = {}
    for artefact_type, content_key, prop in _SNAPSHOT_ARTEFACT_FIELDS:
        content, created_at = latest_by_type.get(artefact_type, (None, None))
        # Dismissal artefacts are append-only and never cleared, and the state API only writes one
        # when the user actually gave feedback — so a stale reason from an earlier dismissal must
        # not ride along on later transitions (including feedback-less re-dismissals). Only a
        # dismissal/snooze label whose feedback was written as part of this transition includes it.
        if artefact_type == SignalReportArtefact.ArtefactType.DISMISSAL and (
            not include_dismissal or created_at is None or created_at < transition_at - _DISMISSAL_FRESHNESS
        ):
            snapshot[prop] = None
            continue
        value = None
        if content:
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    value = data.get(content_key)
            except (json.JSONDecodeError, TypeError, ValueError):
                value = None
        snapshot[prop] = value if isinstance(value, str) else None
    return snapshot
