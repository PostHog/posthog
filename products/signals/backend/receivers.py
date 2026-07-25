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
from products.signals.backend.report_embeddings import emit_report_embedding, render_report_document
from products.signals.backend.tasks import close_dismissed_report_pr

logger = structlog.get_logger(__name__)

_SNOOZE_SOURCE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.RESOLVED})

# The fields the embedded report document is rendered from. A save touching none of them cannot
# change the document, so it skips both the prior-state read and the re-embed.
_DOCUMENT_FIELDS = frozenset({"title", "summary"})


@receiver(pre_save, sender=SignalReport)
def capture_prior_state(
    sender: type[SignalReport],
    instance: SignalReport,
    **kwargs: Any,
) -> None:
    """Stash the row's prior status and rendered document so post_save receivers can tell a real
    status transition, or a real text change, from a no-op edit.

    Both are read in one query because a full save (``update_fields=None``) needs both, and a second
    round-trip per save would double the read cost of the bulk-state endpoint's 100-report path.
    """
    # UUIDModel PKs carry a Python-side default, so pk is set at construction, never None — use
    # _state.adding to tell an unsaved row (no prior status) from an update.
    if instance._state.adding:
        instance._prior_status = None  # type: ignore[attr-defined]
        instance._prior_document = None  # type: ignore[attr-defined]
        return

    update_fields = kwargs.get("update_fields")
    wants_status = update_fields is None or "status" in update_fields
    wants_document = update_fields is None or bool(_DOCUMENT_FIELDS & set(update_fields))
    if not wants_status and not wants_document:
        instance._prior_status = None  # type: ignore[attr-defined]
        instance._prior_document = None  # type: ignore[attr-defined]
        return

    prior = sender.objects.filter(pk=instance.pk).values("status", "title", "summary").first()
    instance._prior_status = prior["status"] if prior and wants_status else None  # type: ignore[attr-defined]
    instance._prior_document = (  # type: ignore[attr-defined]
        render_report_document(prior["title"], prior["summary"]) if prior and wants_document else None
    )


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
def emit_report_embedding_on_document_change(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Embed the report whenever its title or summary changes.

    Same single-choke-point argument as the label stream below: the matcher writes the text when it
    creates a report, the summary workflow rewrites it on `IN_PROGRESS -> READY`, re-research rewrites
    it on each subsequent run, and the scout channel rewrites it through `update_authored_content`.
    All of them finish in a ``save``, so hooking the model covers every producer without each one
    opting in.
    """
    if update_fields is not None and not (_DOCUMENT_FIELDS & set(update_fields)):
        return

    content = render_report_document(instance.title, instance.summary)
    if content is None:
        return
    # A save can touch title/summary without changing them: the grouping pipeline rewrites `title`
    # for every signal that joins the report. Re-embedding identical text would spend an embedding
    # call to write a row identical to the one already stored.
    if getattr(instance, "_prior_document", None) == content:
        return

    team_id = instance.team_id
    report_id = str(instance.id)
    # Snapshot now, because the instance can be saved again before the commit callback runs and the
    # document that gets embedded must be the one this save produced.
    created_at = instance.created_at

    def _emit() -> None:
        try:
            emit_report_embedding(team_id=team_id, report_id=report_id, content=content, created_at=created_at)
        except Exception:
            # A missing vector costs the ranking model one feature row. It must never fail the write
            # that produced the report.
            logger.exception("Failed to emit signal report embedding", report_id=report_id)

    # After commit so a rolled-back save never leaves a vector behind for text that was never stored.
    transaction.on_commit(_emit)


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
    # Set by the state API when this same request is about to write a dismissal artefact. Read here
    # rather than inferred from the transition, because a resolve carries feedback only when the
    # caller supplied it — a PR-merge resolve from the tasks webhook writes none, and must not pick
    # up an unrelated earlier reason that happens to fall inside the freshness window.
    wrote_dismissal_feedback = bool(getattr(instance, "_wrote_dismissal_feedback", False))

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
                        include_dismissal=wrote_dismissal_feedback
                        or _is_dismissal_transition(previous_status, new_status),
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
    """Whether this transition inherently carries dismissal feedback: a dismissal (into suppressed)
    or a snooze (researched report back to potential).

    Resolve is deliberately absent. It carries feedback only when the caller supplied a reason or
    note, which the state API signals explicitly via `_wrote_dismissal_feedback` — a resolve driven
    by the tasks PR-merge webhook writes none, and inferring it from the status would attach
    whatever unrelated reason last landed inside the freshness window."""
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
