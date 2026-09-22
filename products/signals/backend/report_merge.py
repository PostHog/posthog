"""Fold duplicate reports into the one report that survives them.

Grouping puts the same issue in two reports often enough that the inbox needs a repair tool, and
the pieces of that repair cannot be composed safely by hand. Signals live in ClickHouse and have
to be re-emitted under the survivor's id, the duplicate's dismissal must not close a pull request
the survivor now owns, and the two reports' counters have to stay consistent. So the whole thing
is one operation with one transaction.

The caller names the survivor and the sources. Nothing here guesses which report should win, and
nothing here rewrites content: titles, summaries, charts and metrics are left exactly as they
were, so the survivor's embeddings are untouched and the outcome of a merge is predictable
without reading an LLM's mind. A caller that wants a combined summary edits the survivor
afterwards, where the safety judge runs.
"""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.db.models import F

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    Dismissal,
    NoteArtefact,
    ReportLink,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportGithubComment,
    SignalReportTask,
)
from products.signals.backend.recurrence import latest_recurrence_report

logger = structlog.get_logger(__name__)

# One call folds a handful of twins at most. The cap bounds the row locks the merge takes and the
# ClickHouse re-emits it schedules.
MAX_MERGE_SOURCE_REPORTS = 10
MAX_MERGE_REASON_LENGTH = 500

# Written onto the source's dismissal artefact. Deliberately not in
# `SIGNAL_REPORT_DISMISSAL_REASON_CHOICES`: like `refunded`, it is a code this server path writes,
# never one a caller may pick. Grouping reads it to decide whether a `duplicate_of` link redirects
# signals (see `merge_survivor`), so a caller that could set it by hand could redirect another
# report's signals through the plain `state` endpoint.
MERGE_DISMISSAL_REASON = "merged"

# A source must still be live for a merge to mean anything: a resolved or already-archived report
# has had its verdict, and folding it in would undo that verdict silently.
MERGEABLE_SOURCE_STATUSES = frozenset(
    {
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.CANDIDATE,
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.READY,
        SignalReport.Status.FAILED,
    }
)

# Log artefacts describe work done on a report, so they follow the work to the survivor. Four log
# types stay behind:
#   - `report_link` and `related_to` state how *the source* relates to other reports. Moving a row
#     that names the survivor would make the survivor link to itself, which the write path forbids,
#     and moving the rest can close a cycle that `validate_report_link` would have refused.
#   - `title_change` and `summary_change` record edits to the source's own text, which the merge
#     never copies over. On the survivor they would claim its title changed to the source's.
#   - `work_claim` and `work_release` decide who owns a report now. `active_claims` reads the
#     newest claim per report, so moving an older report's claim history in can mask the
#     survivor's own live claim and make a claimed report look unclaimed.
# `signal_finding` is in neither artefact family, and it is the per-signal evidence, so it moves
# with the signals.
_MOVED_ARTEFACT_TYPES = frozenset(SignalReportArtefact.LOG_ARTEFACT_TYPES) - {
    SignalReportArtefact.ArtefactType.REPORT_LINK,
    SignalReportArtefact.ArtefactType.RELATED_TO,
    SignalReportArtefact.ArtefactType.TITLE_CHANGE,
    SignalReportArtefact.ArtefactType.SUMMARY_CHANGE,
    SignalReportArtefact.ArtefactType.WORK_CLAIM,
    SignalReportArtefact.ArtefactType.WORK_RELEASE,
} | {SignalReportArtefact.ArtefactType.SIGNAL_FINDING}


class ReportMergeError(Exception):
    """A merge the caller asked for cannot be applied. `detail` is caller-facing."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@frozen
class MergedSource:
    """What the merge did to one source report."""

    report_id: str
    artefacts_moved: int
    signals_moved: int
    released_claim: bool


@frozen
class MergeResult:
    survivor_id: str
    sources: tuple[MergedSource, ...]


def _latest_dismissal_reason(report: SignalReport) -> str | None:
    latest = (
        SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
        )
        .order_by("-created_at")
        .values_list("content", flat=True)
        .first()
    )
    if latest is None:
        return None
    try:
        return Dismissal.model_validate_json(latest).reason
    except ValueError:
        return None


def was_merged_away(report: SignalReport) -> bool:
    """Whether this report was folded into another one and so no longer holds its own signals.

    Only the latest dismissal counts, matching `fixed_dismissal_at`. A reviewer who re-dismisses a
    merged report with another code has overruled the merge as the report's current verdict, and
    restoring it is their call again.
    """
    return report.status == SignalReport.Status.SUPPRESSED and _latest_dismissal_reason(report) == (
        MERGE_DISMISSAL_REASON
    )


def _merge_target(report: SignalReport, *, lock: bool) -> SignalReport | None:
    """The report this one was merged into, or None when it was not merged away."""
    if not was_merged_away(report):
        return None
    for content in (
        SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            type=SignalReportArtefact.ArtefactType.REPORT_LINK,
        )
        .order_by("-created_at")
        .values_list("content", flat=True)
    ):
        try:
            link = ReportLink.model_validate_json(content)
        except ValueError:
            continue
        if link.kind != ReportLinkKind.DUPLICATE_OF:
            continue
        survivors = SignalReport.objects.filter(team_id=report.team_id, id=link.report_id).exclude(
            status=SignalReport.Status.DELETED
        )
        if lock:
            survivors = survivors.select_for_update()
        return survivors.first()
    return None


def merge_survivor(report: SignalReport, *, lock: bool = False) -> SignalReport:
    """Follow the merge chain to the report that now holds this one's signals.

    Grouping calls this before attaching a signal. A merged report keeps absorbing matches
    otherwise: its signals stay in the semantic index under its own id until the re-emit lands,
    and a suppressed report accrues them silently, so the duplicate the merge just archived would
    quietly grow again.
    """
    visited = {report.id}
    while survivor := _merge_target(report, lock=lock):
        if survivor.id in visited:
            return report
        visited.add(survivor.id)
        report = survivor
    return report


def signal_target_report(report: SignalReport, *, lock: bool = False) -> SignalReport:
    """The report a signal that matched `report` should actually attach to.

    Two pointers can move a match: a merge sends it to the survivor, and a recurrence sends it to
    the fresh report a resolved one spawned. Either can follow the other (a survivor is later
    resolved and recurs, a recurrence is later merged away), so this walks both until the report
    stops moving.
    """
    visited: set[UUID] = set()
    while report.id not in visited:
        visited.add(report.id)
        resolved = merge_survivor(latest_recurrence_report(report, lock=lock), lock=lock)
        if resolved.id == report.id:
            break
        report = resolved
    return report


def _release_source_claim(source: SignalReport, attribution: ArtefactAttribution) -> bool:
    """End an active claim on the source so the merge does not carry live work onto the survivor.

    A claim held by the caller themselves is left alone: it is the same actor continuing the same
    work, and the survivor's own claim (if any) already belongs to them.
    """
    from products.signals.backend.report_assignments import (
        release_claim,  # noqa: PLC0415 — keeps the GitHub integration off the grouping import path
    )
    from products.signals.backend.report_claims import actor_owns_claim, get_active_claim  # noqa: PLC0415 — same

    claim = get_active_claim(team_id=source.team_id, report_id=str(source.id))
    if claim is None or actor_owns_claim(claim, attribution):
        return False
    release_claim(claim, attribution)
    return True


def _move_side_rows(source: SignalReport, survivor: SignalReport) -> None:
    """Re-parent the per-report rows that live outside the artefact log.

    Each of these has a uniqueness constraint the survivor may already satisfy, so a colliding row
    stays on the source rather than failing the merge. Reading either report then still finds the
    fact once.
    """
    survivor_task_ids = set(
        SignalReportTask.objects.filter(report_id=survivor.id).values_list("task_id", flat=True),
    )
    SignalReportTask.objects.filter(team_id=source.team_id, report_id=source.id).exclude(
        task_id__in=survivor_task_ids
    ).update(report_id=survivor.id)

    survivor_comments = set(
        SignalReportGithubComment.all_teams.filter(report_id=survivor.id).values_list("repository", "number"),
    )
    for comment in SignalReportGithubComment.all_teams.filter(team_id=source.team_id, report_id=source.id):
        if (comment.repository, comment.number) in survivor_comments:
            continue
        comment.report_id = survivor.id
        comment.save(update_fields=["report", "updated_at"])

    SignalReportCheck.objects.for_team(source.team_id).filter(report_id=source.id).update(report_id=survivor.id)

    # The task FK is the tasks product's own column, so it moves through the facade. Implementation
    # runs are looked up through it, and the survivor now owns the source's implementation work.
    from products.tasks.backend.facade import (
        api as tasks_facade,  # noqa: PLC0415 — cross-product import kept off the module import path
    )

    tasks_facade.reassign_signal_report_tasks(
        team_id=source.team_id, source_report_id=str(source.id), survivor_report_id=str(survivor.id)
    )


def _merge_source_into(
    *,
    survivor: SignalReport,
    source: SignalReport,
    attribution: ArtefactAttribution,
    reason: str | None,
) -> MergedSource:
    released_claim = _release_source_claim(source, attribution)

    moved_artefacts = (
        SignalReportArtefact.objects.filter(
            team_id=source.team_id, report_id=source.id, type__in=sorted(_MOVED_ARTEFACT_TYPES)
        )
        # An artefact's `claim` must name a claim on the same report, and claim history stays on
        # the source, so the pointer is dropped rather than left dangling across two reports. The
        # row's own actor attribution is what the work log renders, and that is preserved.
        .update(report_id=survivor.id, claim=None)
    )

    _move_side_rows(source, survivor)

    # From the source's Postgres counters, not from a ClickHouse count: these are the numbers the
    # pipeline maintains and the promotion gate reads, and taking them here keeps the survivor
    # exact whatever the re-emit's lag turns out to be. The source keeps its own counters as the
    # historical record of what it collected.
    SignalReport.objects.filter(id=survivor.id).update(
        signal_count=F("signal_count") + source.signal_count,
        total_weight=F("total_weight") + source.total_weight,
    )

    SignalReportArtefact.add_log(
        team_id=source.team_id,
        report_id=str(source.id),
        content=ReportLink(kind=ReportLinkKind.DUPLICATE_OF, report_id=str(survivor.id), reason=reason),
        attribution=attribution,
    )

    _dismiss_as_merged(source, survivor=survivor, attribution=attribution, reason=reason)

    return MergedSource(
        report_id=str(source.id),
        artefacts_moved=moved_artefacts,
        signals_moved=source.signal_count,
        released_claim=released_claim,
    )


def _dismiss_as_merged(
    source: SignalReport,
    *,
    survivor: SignalReport,
    attribution: ArtefactAttribution,
    reason: str | None,
) -> None:
    """Archive the source the way every other dismissal surface does: `transition_to` then `save`.

    The `post_save` receivers hang off that save, so the merge gets the tracker-issue close, the
    `signal_report_status_changed` analytics and the embedding tombstone without opting into any
    of them. The pull-request close fires too, and skips itself, because the source's
    `pull_request` artefacts already moved to the survivor inside this transaction and
    `implementation_pr_needed_by_another_report` sees the survivor still holding the PR.
    """
    updated_fields = source.transition_to(SignalReport.Status.SUPPRESSED)
    source._wrote_dismissal_feedback = True  # type: ignore[attr-defined]
    source._transition_actor_user_id = attribution.user_id  # type: ignore[attr-defined]
    source.save(update_fields=updated_fields)

    note = f"Merged into report {survivor.id}."
    SignalReportArtefact.append_dismissal(
        team_id=source.team_id,
        report_id=str(source.id),
        content=Dismissal(
            reason=MERGE_DISMISSAL_REASON,
            note=f"{note} {reason}" if reason else note,
            user_id=attribution.user_id,
        ),
        attribution=attribution,
    )


def _survivor_note(sources: list[SignalReport], reason: str | None) -> str:
    listed = "\n".join(f"- {source.id}: {source.title or 'Untitled report'}" for source in sources)
    body = f"Merged {len(sources)} duplicate report{'' if len(sources) == 1 else 's'} into this one:\n{listed}"
    if reason:
        body = f"{body}\n\n{reason}"
    return f"{body}\n\nTitles and summaries are not combined by a merge."


def merge_reports(
    *,
    team: Team,
    survivor: SignalReport,
    source_ids: list[str],
    attribution: ArtefactAttribution,
    reason: str | None = None,
) -> MergeResult:
    """Fold every source report into `survivor`, atomically.

    Raises `ReportMergeError` when a source is not a live report of this team, or names the
    survivor itself. Either the whole call applies or none of it does, so a caller never has to
    reason about a half-merged pair.
    """
    if not source_ids:
        raise ReportMergeError("At least one source report is required.")
    if len(source_ids) > MAX_MERGE_SOURCE_REPORTS:
        raise ReportMergeError(
            f"A merge takes at most {MAX_MERGE_SOURCE_REPORTS} source reports. Split it into several calls."
        )

    ordered_ids: list[str] = []
    for raw_id in source_ids:
        key = str(raw_id)
        if key == str(survivor.id):
            raise ReportMergeError("A report cannot be merged into itself.")
        if key not in ordered_ids:
            ordered_ids.append(key)

    with transaction.atomic():
        # Locked in id order, survivor included, so two merges naming overlapping reports queue
        # instead of deadlocking.
        locked_ids = sorted({*ordered_ids, str(survivor.id)})
        locked = {
            str(report.id): report
            for report in SignalReport.objects.select_for_update()
            .filter(team_id=team.id, id__in=locked_ids)
            .order_by("id")
        }
        if str(survivor.id) not in locked:
            raise ReportMergeError("The report to merge into was not found in this project.")
        survivor = locked[str(survivor.id)]

        sources: list[SignalReport] = []
        for source_id in ordered_ids:
            source = locked.get(source_id)
            if source is None:
                raise ReportMergeError(f"Report {source_id} was not found in this project.")
            if source.status not in MERGEABLE_SOURCE_STATUSES:
                raise ReportMergeError(
                    f"Report {source_id} is {source.status} and cannot be merged. Only a live report can be a source."
                )
            sources.append(source)

        try:
            merged = [
                _merge_source_into(survivor=survivor, source=source, attribution=attribution, reason=reason)
                for source in sources
            ]
        except ArtefactContentValidationError as e:
            # `add_log` enforces the `report_link` invariants: no self-link, same team, and no
            # cycle within one kind. A merge that would close a duplicate_of cycle is a merge the
            # caller cannot have, not a server fault.
            raise ReportMergeError(str(e))

        SignalReportArtefact.add_log(
            team_id=team.id,
            report_id=str(survivor.id),
            content=NoteArtefact(note=_survivor_note(sources, reason)),
            attribution=attribution,
        )

        team_id = team.id
        survivor_id = str(survivor.id)
        moved_ids = [item.report_id for item in merged]
        transaction.on_commit(
            lambda: _schedule_signal_move(team_id=team_id, survivor_id=survivor_id, source_ids=moved_ids)
        )

    survivor.refresh_from_db()
    logger.info(
        "signals_reports_merged",
        team_id=team.id,
        survivor_report_id=str(survivor.id),
        source_report_ids=[item.report_id for item in merged],
    )
    return MergeResult(survivor_id=str(survivor.id), sources=tuple(merged))


def _schedule_signal_move(*, team_id: int, survivor_id: str, source_ids: list[str]) -> None:
    from products.signals.backend.tasks import (  # noqa: PLC0415 — keeps the celery app off the API import path
        move_merged_report_signals,
    )

    move_merged_report_signals.delay(team_id=team_id, survivor_report_id=survivor_id, source_report_ids=source_ids)
