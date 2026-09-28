"""Django signal receivers for the signals product.

Kept in one place so cross-cutting side effects of report state changes have a single home,
rather than being sprinkled across every dismissal entrypoint (Slack, REST, bulk, …).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_embeddings import (
    emit_report_embeddings,
    emit_report_tombstone,
    render_report_documents,
)
from products.signals.backend.scout_harness.suggestions import mark_stale_if_fleet_changed
from products.signals.backend.suggested_reviewer_index import sync_suggested_reviewer_index
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

if TYPE_CHECKING:
    from products.signals.backend.implementation_pr import PrCloseReason

logger = structlog.get_logger(__name__)

_SNOOZE_SOURCE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.RESOLVED})

# The fields the embedded report document is rendered from. A save touching none of them cannot
# change the document, so it skips both the prior-state read and the re-embed.
_DOCUMENT_FIELDS = frozenset({"title", "summary"})


def connect_task_run_assignment_sync() -> None:
    connect_task_run_post_save(
        sync_task_run_pr_to_assignments,
        dispatch_uid="signals_sync_task_run_pr_to_assignments",
    )
    connect_task_run_post_save(
        schedule_implementation_handover,
        dispatch_uid="signals_schedule_implementation_handover",
    )


def schedule_implementation_handover(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # Fires on every TaskRun save (a hot model), so the in-memory checks run before the first query.
    if created:
        # A run is created before the agent does anything, and a handover only acts on a finished
        # run, so the save that matters is a later one.
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"status", "output"}.intersection(update_fields):
        return
    # Only the self-driving implementation run can carry a replacement. Report research and repo
    # selection share the report and the internal flag with it, so `ai_stage` is what separates
    # them, and the pipeline stamps it once at run creation (see `pipeline_identity`).
    if (instance.state or {}).get("ai_stage") != "implementation":
        return
    from products.signals.backend.tasks import reconcile_implementation_replacement

    team_id = instance.team_id
    for replacement_id in SignalReportArtefact.objects.filter(
        team_id=team_id, task_id=instance.task_id, type="implementation_replacement"
    ).values_list("id", flat=True):
        # The id is bound as a default argument because the hooks run after the loop ends, so a
        # closure over the loop variable would send every one of them the last id. `robust=True`
        # keeps a broker failure here from cancelling the other hooks this save queued, and Django
        # cannot log a `partial` in that path because it reads the callback's qualified name.
        def enqueue_replacement(queued: str = str(replacement_id)) -> None:
            reconcile_implementation_replacement.delay(team_id, queued)

        transaction.on_commit(enqueue_replacement, robust=True)


@receiver(post_save, sender=SignalReportArtefact)
def schedule_handover_for_work_change(sender: type, instance: SignalReportArtefact, **kwargs: Any) -> None:
    if instance.type not in {"implementation_replacement", "work_claim", "work_release", "pull_request"}:
        return
    from products.signals.backend.supersession import schedule_report_replacements

    team_id, report_id = instance.team_id, str(instance.report_id)
    transaction.on_commit(lambda: schedule_report_replacements(team_id, report_id), robust=True)


@receiver(post_save, sender=SignalReport)
def schedule_handover_for_report_change(sender: type, instance: SignalReport, **kwargs: Any) -> None:
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"status", "run_count"}.intersection(update_fields):
        return
    from products.signals.backend.supersession import schedule_report_replacements

    team_id, report_id = instance.team_id, str(instance.id)
    transaction.on_commit(lambda: schedule_report_replacements(team_id, report_id), robust=True)


def sync_task_run_pr_to_assignments(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """Copy a PR reported by a PR-bearing task run onto its signal report assignments."""
    try:
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "output" not in update_fields:
            return
        output = instance.output if isinstance(instance.output, dict) else {}
        # Function-local: the assignment sync reaches the tasks facade and the task module reaches
        # the signals contracts, both forbidden at django.setup() by the startup-import-budget test.
        from products.signals.backend.pull_requests import apply_report_completion
        from products.signals.backend.report_assignments import sync_task_pull_request_to_assignments  # noqa: PLC0415
        from products.signals.backend.tasks import link_report_tracker_issues  # noqa: PLC0415
        from products.tasks.backend.facade.api import read_pr_urls

        pr_urls = read_pr_urls(output)
        if not pr_urls:
            return
        ai_stage = (instance.state or {}).get("ai_stage")
        if ai_stage in {"research", "repo_selection"} or (isinstance(ai_stage, str) and ai_stage.startswith("scout:")):
            return
        with transaction.atomic():
            reports = list(
                SignalReport.objects.select_for_update()
                .filter(team_id=instance.team_id)
                .filter(SignalReport.reports_for_task_filter(str(instance.task_id)))
                .order_by("id")
            )
            for pr_url in pr_urls:
                primary = pr_url == output.get("pr_url")
                updated = sync_task_pull_request_to_assignments(
                    team_id=instance.team_id,
                    task_id=str(instance.task_id),
                    pr_url=pr_url,
                    pr_state=output.get("pr_state") if primary and isinstance(output.get("pr_state"), str) else None,
                    pr_merged=primary and output.get("pr_merged") is True,
                )
                if updated:
                    # Dispatch after commit so a rolled-back sync never edits a pull request body.
                    transaction.on_commit(
                        partial(
                            link_report_tracker_issues.delay,
                            team_id=instance.team_id,
                            task_id=str(instance.task_id),
                            pr_url=pr_url,
                        )
                    )
            for report in reports:
                apply_report_completion(report)
    except Exception:
        logger.exception("signals.task_run_pr_assignment_sync_failed", task_run_id=str(instance.id))


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
        instance._prior_documents = None  # type: ignore[attr-defined]
        return

    update_fields = kwargs.get("update_fields")
    wants_status = update_fields is None or "status" in update_fields
    wants_document = update_fields is None or bool(_DOCUMENT_FIELDS & set(update_fields))
    if not wants_status and not wants_document:
        instance._prior_status = None  # type: ignore[attr-defined]
        instance._prior_documents = None  # type: ignore[attr-defined]
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
    instance._prior_documents = (  # type: ignore[attr-defined]
        render_report_documents(prior["title"], prior["summary"]) if prior and wants_document else None
    )


def _status_changed_on_this_save(
    instance: SignalReport,
    *,
    created: bool,
    update_fields: set[str] | None,
    prior_status: str | None,
) -> bool:
    """Whether this save is the one that moved the report to another status."""
    if created:
        # Reports born SUPPRESSED by the scout safety/actionability judge never surfaced a PR.
        return False
    # React only to the save that performed the transition, not later edits.
    if update_fields is not None and "status" not in update_fields:
        return False
    return prior_status is not None and prior_status != instance.status


def _pr_close_reason(
    instance: SignalReport,
    *,
    created: bool,
    update_fields: set[str] | None,
    prior_status: str | None,
) -> PrCloseReason | None:
    if not _status_changed_on_this_save(
        instance, created=created, update_fields=update_fields, prior_status=prior_status
    ):
        return None
    # The pull request's own observed state drove this transition, so there is nothing left to close.
    if getattr(instance, "_status_from_pr_state", False):
        return None

    if instance.status == SignalReport.Status.SUPPRESSED:
        return "suppressed"

    if instance.status == SignalReport.Status.POTENTIAL and prior_status in _SNOOZE_SOURCE_STATUSES:
        return "snoozed"

    # Only a resolve that a caller asked for through the state API supersedes the PR. The PR-merge
    # webhook also lands in RESOLVED, and its PR is merged, so there is nothing to close there.
    if instance.status == SignalReport.Status.RESOLVED and getattr(instance, "_close_pr_on_resolve", False):
        return "resolved"

    return None


@receiver(post_save, sender=SignalReport)
def close_pr_when_report_dismissed(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Close the implementation PR when a report is suppressed, snoozed, or resolved by a caller.

    This is the single choke point for the dismiss→close side effect: every suppression surface
    (Slack, the REST state/bulk-state API, any future one) ends in a ``save`` that flips status
    to SUPPRESSED, and snoozing a ready/resolved report ends in READY/RESOLVED → POTENTIAL, so
    hooking the model here covers them all without each caller opting in. A resolve closes the PR
    only when the state API flagged it (see ``_pr_close_reason``).
    """
    # Function-local: the task module reaches the signals contracts, which the
    # startup-import-budget test forbids at django.setup().
    from products.signals.backend.tasks import close_dismissed_report_pr, close_report_tracker_issue  # noqa: PLC0415

    prior_status = getattr(instance, "_prior_status", None)
    # The person who asked for this transition, when a caller set it before the save. GitHub
    # credits the App for the close, so the comment left beside it is the only place they appear.
    # Absent on every automated transition (PR webhook, judges, temporal), which stays unattributed.
    actor_user_id = getattr(instance, "_transition_actor_user_id", None)
    reason = _pr_close_reason(
        instance,
        created=created,
        update_fields=update_fields,
        prior_status=prior_status,
    )
    if reason is None:
        if not _status_changed_on_this_save(
            instance, created=created, update_fields=update_fields, prior_status=prior_status
        ):
            return
        team_id = instance.team_id
        report_id = str(instance.id)
        if getattr(instance, "_status_from_pr_state", False) and instance.status == SignalReport.Status.RESOLVED:
            transaction.on_commit(
                lambda: close_report_tracker_issue.delay(
                    report_id=report_id, team_id=team_id, completed=True, actor_user_id=actor_user_id
                )
            )
        elif instance.status == SignalReport.Status.DELETED:
            # A deleted report leaves the inbox for good, so nothing will ever answer its work
            # item. The issue closes as not done, because no pull request completed the work.
            transaction.on_commit(
                lambda: close_report_tracker_issue.delay(
                    report_id=report_id, team_id=team_id, completed=False, actor_user_id=actor_user_id
                )
            )
        return

    team_id = instance.team_id
    report_id = str(instance.id)
    # After commit so a rolled-back transition never closes a PR; best-effort inside the task.
    transaction.on_commit(
        lambda: close_dismissed_report_pr.delay(
            report_id=report_id,
            team_id=team_id,
            reason=reason,
            actor_user_id=actor_user_id,
        )
    )


@receiver(post_save, sender=SignalReport)
def arm_pending_checks_when_report_resolved(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: set[str] | None = None,
    **kwargs: Any,
) -> None:
    """Start the soak clock on the report's pending checks the moment it resolves.

    A check written during research predates any fix, so it carries a soak duration rather than a
    date. The resolve is what it waits for, and hooking the model rather than each caller makes
    every resolve path the same clock: a merged pull request's webhook, a manual resolve in the
    inbox, and an MCP state write all finish in a ``save``. Plenty of fixes never have a pull
    request to date a window from, which is why the report's own transition is the event.
    """
    if instance.status != SignalReport.Status.RESOLVED:
        return
    if not _status_changed_on_this_save(
        instance, created=created, update_fields=update_fields, prior_status=getattr(instance, "_prior_status", None)
    ):
        return
    team_id = instance.team_id
    report_id = str(instance.id)
    resolved_at = timezone.now()
    # After commit, so a rolled-back resolve never arms a check, and best-effort: a report that
    # resolved is the outcome that matters, and a failure here leaves the checks pending rather
    # than losing them.
    transaction.on_commit(
        partial(_arm_pending_checks_safely, team_id=team_id, report_id=report_id, resolved_at=resolved_at)
    )


def _arm_pending_checks_safely(*, team_id: int, report_id: str, resolved_at: datetime) -> None:
    # Function-local: the authoring module reaches the execution module and from there the alerts
    # facade, which the startup-import-budget test keeps off django.setup().
    from products.signals.backend.report_check_authoring import arm_pending_checks  # noqa: PLC0415

    try:
        arm_pending_checks(team_id=team_id, report_id=report_id, resolved_at=resolved_at)
    except Exception:
        logger.exception("signals.report_check.arm_on_resolve_failed", report_id=report_id, team_id=team_id)


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

    # The inverse marker: a judged rewrite that re-sent the exact stored document. The text is
    # unchanged, but the current embedding row may be a tombstone from an earlier unreviewed edit, so
    # the no-op shortcut below must not skip this save. Consumed like `_unreviewed_edit`: it
    # describes the one save it was set for.
    reviewed_reindex = getattr(instance, "_reviewed_reindex", False)
    if reviewed_reindex:
        instance._reviewed_reindex = False  # type: ignore[attr-defined]

    # An edit can still land on a deleted report: `update_scout_report` gates on team ownership, not
    # status. Emitting a live row for one would supersede the deletion tombstone and make the report
    # visible to embedding queries again.
    if instance.status == SignalReport.Status.DELETED:
        return

    documents = render_report_documents(instance.title, instance.summary)
    prior_documents = getattr(instance, "_prior_documents", None) or {}
    removed_renderings = tuple(rendering for rendering in prior_documents if rendering not in documents)
    # A save can touch title/summary without changing them: the grouping pipeline rewrites `title`
    # for every signal that joins the report. Re-embedding identical text would spend an embedding
    # call to write a row identical to the one already stored.
    #
    # Applied per rendering, because each one is a separate row under its own key: a summary-only edit
    # changes the composed document while the title rendering stays byte-identical, and only the
    # changed one is worth an embedding call.
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
    if not carries_status_transition and not reviewed_reindex:
        documents = {
            rendering: content for rendering, content in documents.items() if prior_documents.get(rendering) != content
        }
    if not documents and not removed_renderings:
        return

    def _emit() -> None:
        try:
            if removed_renderings:
                emit_report_tombstone(
                    team_id=team_id, report_id=report_id, created_at=created_at, renderings=removed_renderings
                )
            # Checked post-commit, because a scout report's safety verdict is written as an artefact
            # in the same transaction as the report row it judges, so it is only visible from here.
            if not documents or _is_safety_suppressed(report_id, team_id):
                return
            emit_report_embeddings(team_id=team_id, report_id=report_id, documents=documents, created_at=created_at)
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


def _sync_report_latest_actionability(instance: SignalReportArtefact) -> None:
    if instance.type != SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT:
        return
    SignalReport.refresh_latest_actionability(team_id=instance.team_id, report_id=instance.report_id)


@receiver(post_save, sender=SignalReportArtefact)
def sync_report_latest_actionability_on_save(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    created: bool,
    **kwargs: Any,
) -> None:
    """Keep the report's cached actionability equal to its newest judgment.

    On the artefact write path rather than at each producer, because a judgment reaches a report
    from the research pipeline, a custom agent, a scout edit, the artefact REST API and the MCP
    tools. Not gated on `created`, because `update_content` edits a judgment row in place.
    """
    _sync_report_latest_actionability(instance)


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


@receiver(post_delete, sender=SignalReportArtefact)
def sync_report_latest_actionability_on_delete(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    origin: Any = None,
    **kwargs: Any,
) -> None:
    """Deleting the newest judgment reverts the report to the one before it.

    Skipped for a cascade, where the report itself is going away, so a team teardown does not pay
    a read and a write per artefact for a row nobody will read.
    """
    if not _deleted_directly(origin):
        return
    _sync_report_latest_actionability(instance)


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
    (SignalReportArtefact.ArtefactType.DISMISSAL, "corrected_repository", "dismissal_corrected_repository"),
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


@receiver(post_save, sender="signals.SignalScoutConfig")
@receiver(post_delete, sender="signals.SignalScoutConfig")
def mark_scout_suggestions_stale_on_fleet_change(sender: Any, instance: Any, **kwargs: Any) -> None:
    """A suggestion batch describes gaps in the fleet it was generated against, so a scout being
    enabled, disabled, or removed flips a `fresh` batch to `stale`; regeneration waits for the
    normal refresh. Saves that cannot change the enabled set (`update_fields` without `enabled`)
    skip the read entirely, and nothing here may fail the config write."""
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "enabled" not in update_fields:
        return
    try:
        mark_stale_if_fleet_changed(instance.team_id)
    except Exception:
        logger.warning("scout_suggestions: failed to mark batch stale", team_id=instance.team_id, exc_info=True)


@receiver(post_save, sender=SignalReportArtefact)
def sync_suggested_reviewer_index_on_save(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    created: bool,
    **kwargs: Any,
) -> None:
    """Rebuild the report's reviewer index whenever a reviewers row is written.

    Not gated on `created`: `update_content` edits a reviewers row in place, and editing the
    current row changes the report's reviewer set.
    """
    if instance.type != SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
        return
    sync_suggested_reviewer_index(team_id=instance.team_id, report_id=str(instance.report_id))


@receiver(post_delete, sender=SignalReportArtefact)
def sync_suggested_reviewer_index_on_delete(
    sender: type[SignalReportArtefact],
    instance: SignalReportArtefact,
    origin: Any = None,
    **kwargs: Any,
) -> None:
    """Deleting the current reviewers row reverts the set to the previous one, or to none.

    Skipped for a cascade: the index rows go down with the report that owns them, so rebuilding
    per artefact on the way down would only spend queries to reach the same empty state.
    """
    if instance.type != SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS or not _deleted_directly(origin):
        return
    sync_suggested_reviewer_index(team_id=instance.team_id, report_id=str(instance.report_id))
