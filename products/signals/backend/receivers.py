"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

import json
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.implementation_pr import PrCloseReason
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_embeddings import (
    emit_report_embedding,
    emit_report_tombstone,
    render_report_document,
)
from products.signals.backend.tasks import close_dismissed_report_pr

logger = structlog.get_logger(__name__)

_SNOOZE_SOURCE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.RESOLVED})

# The fields the embedded report document is rendered from. A save touching none of them cannot
# change the document, so it skips both the prior-state read and the re-embed.
_DOCUMENT_FIELDS = frozenset({"title", "summary"})


def _schedule_tombstone(*, team_id: int, report_id: str, created_at: datetime, reason: str) -> None:
    """Retract the report's vector after the current transaction commits.

    Unconditional by design. The tombstone carries fixed placeholder text rather than the report's own,
    so it costs at most a spare row when nothing was ever embedded, and none of the callers has to
    answer the question they cannot answer cheaply: whether a live row exists.
    """

    def _emit() -> None:
        try:
            emit_report_tombstone(team_id=team_id, report_id=report_id, created_at=created_at)
        except Exception:
            logger.exception(
                "Failed to tombstone signal report embedding", report_id=report_id, tombstone_reason=reason
            )

    # After commit so a rolled-back transaction never retracts a vector that is still current.
    transaction.on_commit(_emit)


def _verdict_is_unsafe(content: str | None) -> bool:
    """Whether a `safety_judgment` artefact's content records an unsafe verdict.

    An unparseable verdict counts as unsafe: failing closed keeps content the judge may have rejected
    out of the index.
    """
    if not content:
        return False
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return True
    return isinstance(data, dict) and data.get("choice") is False


def _is_safety_suppressed(report_id: str, team_id: int) -> bool:
    """Whether the safety judge marked this report unsafe.

    An unsafe report's backing signals are deliberately never indexed: `create_scout_report` is passed
    `emit_signals=False` so the adversarial-looking descriptions can't become semantic-search
    candidates or matching context for unrelated signals. The report's own title and summary are that
    same attacker-influenced text, so embedding them would hand back exactly what the gate denies.

    Read from the durable `safety_judgment` artefact rather than a flag on the instance, so the gate
    holds for every writer, including the deletion path, which loads a fresh report the author of the
    verdict never touched.

    Pinned to the writer with `using("default")`. This runs immediately after the transaction that
    wrote the verdict commits, and `ReplicaRouter` documents replication lag on exactly that pattern,
    so a replica-routed read could miss the verdict and let the gate fail open on unsafe content.
    """
    content = (
        SignalReportArtefact.objects.using("default")
        .filter(report_id=report_id, team_id=team_id, type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT)
        .order_by("-created_at")
        .values_list("content", flat=True)
        .first()
    )
    return _verdict_is_unsafe(content)


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

    # Project only what this save needs. The bulk-state endpoint transitions up to 100 reports per
    # request and none of those saves touches title/summary, so selecting them there would de-TOAST a
    # large summary per row for a value that is discarded immediately.
    fields = [
        name
        for name, wanted in (("status", wants_status), ("title", wants_document), ("summary", wants_document))
        if wanted
    ]
    # Writer-pinned for the same reason as the safety verdict read: this runs against a row the caller
    # is about to overwrite, and a lagging replica could report stale text. That would make an A -> B -> A
    # edit look unchanged on the final save and skip re-emitting A over the B vector already published.
    prior = sender.objects.using("default").filter(pk=instance.pk).values(*fields).first()
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

    team_id = instance.team_id
    report_id = str(instance.id)
    # Snapshot now, because the instance can be saved again before the commit callback runs and the
    # document that gets embedded must be the one this save produced.
    created_at = instance.created_at

    # A user or agent edit (the PATCH endpoint, the scout `edit_report` channel) supplies text the
    # safety judge has never seen, and the report's existing verdict predates it. Rather than trust a
    # stale approval, retract whatever vector the report has and leave it unindexed until the pipeline
    # writes judged text again on its next research run.
    if getattr(instance, "_unreviewed_edit", False):
        # Consumed here: the marker describes the one save it was set for. Leaving it attached would
        # make every later save of the same in-memory instance retract again, so the judged rewrite
        # that should restore the report would tombstone it instead.
        instance._unreviewed_edit = False  # type: ignore[attr-defined]
        _schedule_tombstone(team_id=team_id, report_id=report_id, created_at=created_at, reason="unreviewed edit")
        return

    # An edit can still land on a deleted report: `update_scout_report` gates on team ownership, not
    # status. Emitting a live row for one would supersede the deletion tombstone and make the report
    # visible to embedding queries again.
    if instance.status == SignalReport.Status.DELETED:
        return

    content = render_report_document(instance.title, instance.summary)
    if content is None:
        return
    # A save can touch title/summary without changing them: the grouping pipeline rewrites `title`
    # for every signal that joins the report. Re-embedding identical text would spend an embedding
    # call to write a row identical to the one already stored.
    #
    # Restricted to saves that carry no status transition, because unchanged text does not imply a live
    # row. An unreviewed edit tombstones the report while Postgres keeps the edited text, so when the
    # next research run judges that same text and writes it back, the text matches but the current row
    # is a tombstone. Skipping there would leave the report retracted forever. A judged write always
    # carries `status`, and re-emitting on it is cheap because it happens once per research run, unlike
    # the per-joining-signal title rewrite this shortcut exists for.
    #
    # `update_fields=None` deliberately does NOT count. Every pipeline write names its fields, while a
    # bare `save()` is what Django admin does, so treating it as judged would let re-saving a report in
    # admin republish text an edit had retracted, under a verdict that predates it.
    carries_status_transition = update_fields is not None and "status" in update_fields
    if not carries_status_transition and getattr(instance, "_prior_document", None) == content:
        return

    def _emit() -> None:
        try:
            # Checked post-commit, because a scout report's safety verdict is written as an artefact
            # in the same transaction as the report row it judges, so it is only visible from here.
            if _is_safety_suppressed(report_id, team_id):
                return
            emit_report_embedding(team_id=team_id, report_id=report_id, content=content, created_at=created_at)
        except Exception:
            # A missing vector costs the ranking model one feature row. It must never fail the write
            # that produced the report.
            logger.exception("Failed to emit signal report embedding", report_id=report_id)

    # After commit so a rolled-back save never leaves a vector behind for text that was never stored.
    transaction.on_commit(_emit)


@receiver(post_save, sender=SignalReport)
def tombstone_report_embedding_on_delete(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Tombstone the report's embedding when the report is deleted.

    Deletion already tombstones the report's *signal* rows, via `soft_delete_report_signals` in the
    deletion workflow. Without the matching write for the report's own document, it would stay visible
    to any reader filtering on `NOT JSONExtractBool(metadata, 'deleted')`, which is what every existing
    signals read query does, so the first consumer of report embeddings would surface deleted reports.

    Deletion only flips `status`, so the document-change receiver above never fires for it.

    Emitted unconditionally, without consulting the report's current text or safety verdict. A report
    embedded while safe and only later judged unsafe still has a live vector, and one whose text was
    cleared before deletion still has the vector from when it had text, so any precondition here would
    strand exactly the rows that most need retracting. The tombstone carries fixed placeholder content,
    so writing one for a report that was never embedded is harmless.
    """
    if created:
        return
    if update_fields is not None and "status" not in update_fields:
        return
    if instance.status != SignalReport.Status.DELETED:
        return
    prior_status = getattr(instance, "_prior_status", None)
    if prior_status is None or prior_status == instance.status:
        return

    _schedule_tombstone(
        team_id=instance.team_id,
        report_id=str(instance.id),
        created_at=instance.created_at,
        reason="deletion",
    )


@receiver(post_delete, sender=SignalReport)
def tombstone_report_embedding_on_hard_delete(
    sender: type[SignalReport],
    instance: SignalReport,
    **kwargs: Any,
) -> None:
    """Tombstone the report's embedding when its row is removed from Postgres outright.

    The status receiver above covers the product's own deletion flow, which soft-deletes by flipping
    status to DELETED. It does not cover the paths that drop rows: `delete_team_reports_activity` in
    the reingestion workflow and the `cleanup_signals` command both issue a queryset `delete()`. Those
    leave the report's vector live until the table's three month TTL, with nothing left in Postgres to
    reconcile it against, which is worse than the soft-delete case because no later write can fix it.

    A report deleted through the soft path and later dropped tombstones twice. That costs one spare row
    and is the same trade the unconditional tombstone already makes everywhere else.
    """
    _schedule_tombstone(
        team_id=instance.team_id,
        report_id=str(instance.id),
        created_at=instance.created_at,
        reason="hard deletion",
    )


def _reconcile_report_embedding_with_verdict(instance: SignalReportArtefact) -> None:
    """Retract a report's embedding when its canonical safety verdict is unsafe.

    The summary workflow re-judges safety on every run, and a READY report runs research again whenever
    new signals join it, so a report can be embedded while safe and only later be judged unsafe, on the
    strength of a signal an attacker controls. Withholding future emissions is not enough on its own:
    the vector already written stays a semantic-search candidate, which is the boundary the judge exists
    to hold. The unsafe path marks the report FAILED without rewriting its text, so neither report-level
    receiver fires for it.

    Reconciles from the report's *latest* verdict rather than from the row that changed, because the row
    and the canonical verdict are not the same thing. Editing a superseded row to unsafe must not retract
    a report the latest verdict still approves, and deleting the latest safe row promotes an older unsafe
    one (see the artefact DELETE endpoint) without any write to that older row to announce it.

    Restoration is deliberately not symmetric. A report corrected back to safe stays unindexed until the
    pipeline next writes judged text, which re-emits it. Retraction is immediate and restoration is
    eventual, which is the right way round for a safety boundary.
    """
    if instance.type != SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT:
        return

    team_id = instance.team_id
    report_id = str(instance.report_id)

    def _emit() -> None:
        try:
            # Both reads happen post-commit rather than in the receiver body. Only then is the canonical
            # verdict settled, whether this change was an append, an in-place edit, or a delete that
            # promoted an older row, and a cascade that removed the report along with its artefacts
            # exits on the first query instead of paying for two per deleted verdict.
            #
            # Team-scoped: an artefact and the report it judges always belong to the same team, so
            # filtering on it keeps this lookup from reaching across tenants.
            report = (
                SignalReport.objects.using("default").filter(pk=report_id, team_id=team_id).values("created_at").first()
            )
            if report is None:
                return
            if not _is_safety_suppressed(report_id, team_id):
                return
            emit_report_tombstone(team_id=team_id, report_id=report_id, created_at=report["created_at"])
        except Exception:
            logger.exception(
                "Failed to tombstone signal report embedding", report_id=report_id, tombstone_reason="unsafe verdict"
            )

    transaction.on_commit(_emit)


@receiver(post_save, sender=SignalReportArtefact)
def reconcile_report_embedding_on_verdict_saved(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    created: bool,
    **kwargs: Any,
) -> None:
    """Not gated on `created`: `update_content` edits a verdict row in place, so a safe verdict flipped
    to unsafe arrives as an update rather than an append."""
    _reconcile_report_embedding_with_verdict(instance)


def _deleted_directly(origin: Any) -> bool:
    """Whether a delete was issued against artefacts themselves rather than cascading from a report.

    Django passes the instance or queryset that `delete()` was called on as `origin`, so a cascade
    from a report, or from the team above it, is distinguishable from the artefact DELETE endpoint
    without any query. Unknown origins count as direct, which keeps the reconciliation the safety
    boundary depends on rather than dropping it if this ever stops being populated.
    """
    if origin is None:
        return True
    model = origin.model if isinstance(origin, QuerySet) else type(origin)
    return model is SignalReportArtefact


@receiver(post_delete, sender=SignalReportArtefact)
def reconcile_report_embedding_on_verdict_deleted(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    origin: Any = None,
    **kwargs: Any,
) -> None:
    """Deleting the latest verdict reverts the report to the previous one, which can be unsafe.

    Skipped when the artefact is going away as part of its report's deletion. The report's own
    tombstone already retracts the vector, so reconciling each verdict on the way down would spend two
    queries per artefact to reach the same place. That is the difference between a bounded and an
    unbounded teardown: `delete_team_reports_activity` has five minutes to remove every report and
    artefact a team has accumulated, and deleting a team cascades wider still.
    """
    if not _deleted_directly(origin):
        return
    _reconcile_report_embedding_with_verdict(instance)


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

    # Set by mark_report_pending_input_activity right before this save, so the pipeline's two
    # doors into PENDING_INPUT (repo-selection failure vs. the agent requesting human input) are
    # distinguishable in the training stream — mirrors failure_reason on signal_report_completed.
    pending_reason = (
        getattr(instance, "_pending_reason", None) if instance.status == SignalReport.Status.PENDING_INPUT else None
    )

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
        "pending_reason": pending_reason,
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
