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
from django.db.models.functions import Coalesce

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
)
from products.signals.backend.recurrence import latest_recurrence_report
from products.signals.backend.signal_metadata import REASSIGN_SIGNAL_ROW_CAP

logger = structlog.get_logger(__name__)

# One call folds a handful of twins at most. The cap bounds the row locks the merge takes and the
# ClickHouse re-emits it schedules.
MAX_MERGE_SOURCE_REPORTS = 10
MAX_MERGE_REASON_LENGTH = 500

# Deliberately not in `SIGNAL_REPORT_DISMISSAL_REASON_CHOICES`. Like `refunded`, this server path
# writes it and no caller may pick it, because `merge_survivor` reads it to decide whether a
# `duplicate_of` link redirects signals.
MERGE_DISMISSAL_REASON = "merged"

# Both ends of a merge must be a live report. A resolved or already-archived source has had its
# verdict, and folding it in would undo that verdict silently. A resolved survivor is terminal for
# new signals, so it would take the sources' signals somewhere the pipeline never looks at again
# while archiving those sources for good.
#
# IN_PROGRESS is excluded although it is live: a research run is writing to that report right now,
# and `SUPPRESSED -> READY` is a legal transition, so `mark_report_ready_activity` would resurrect
# the report after the merge moved its signals and work log away. CANDIDATE is safe because a run
# that starts later needs `SUPPRESSED -> IN_PROGRESS`, which the model refuses.
MERGEABLE_STATUSES = frozenset(
    {
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.CANDIDATE,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.READY,
        SignalReport.Status.FAILED,
    }
)

# Log artefacts describe work done on a report, so they follow the work to the survivor. Three
# families stay behind, each because moving them corrupts the survivor:
#   - `report_link` / `related_to` state how *the source* relates to other reports, so a moved row
#     can make the survivor link to itself or close a cycle `validate_report_link` would refuse.
#   - `title_change` / `summary_change` would claim the survivor's title changed to the source's.
#   - `work_claim` / `work_release` decide ownership, and `active_claims` reads the newest claim per
#     report, so a moved claim can mask the survivor's live claim.
# `signal_finding` is in neither family and is the per-signal evidence, so it moves with them.
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


def was_merged_away(report: SignalReport) -> bool:
    """Whether this report was folded into another one and so no longer holds its own signals.

    Any `merged` dismissal counts, unlike `fixed_dismissal_at`, which reads only the latest. A
    fixed dismissal is a verdict a reviewer can overrule; a merge is structural. The signals and
    the work log are on the survivor either way, so a later dismissal with another code must not
    make the report restorable or stop it redirecting matches.
    """
    if report.status != SignalReport.Status.SUPPRESSED:
        return False
    for content in SignalReportArtefact.objects.filter(
        team_id=report.team_id,
        report_id=report.id,
        type=SignalReportArtefact.ArtefactType.DISMISSAL,
    ).values_list("content", flat=True):
        try:
            if Dismissal.model_validate_json(content).reason == MERGE_DISMISSAL_REASON:
                return True
        except ValueError:
            continue
    return False


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
    """End any active claim on the source, so no claim is left stranded on an archived report.

    Claim history stays on the source (see `_MOVED_ARTEFACT_TYPES`), so a claim left active there
    would make the survivor look unclaimed while the work is still owned, and another actor could
    take it. That holds whoever owns the claim, the merge caller included: they re-claim the
    survivor, which is the report the work now belongs to.
    """
    from products.signals.backend.report_assignments import (
        release_claim,  # noqa: PLC0415 — keeps the GitHub integration off the grouping import path
    )
    from products.signals.backend.report_claims import get_active_claim  # noqa: PLC0415 — same

    claim = get_active_claim(team_id=source.team_id, report_id=str(source.id))
    if claim is None:
        return False
    release_claim(claim, attribution)
    return True


def _move_side_rows(source: SignalReport, survivor: SignalReport) -> None:
    """Re-parent the per-report rows that live outside the artefact log.

    Each of these has a uniqueness constraint the survivor may already satisfy, so a colliding row
    stays on the source rather than failing the merge. Reading either report then still finds the
    fact once.

    `SignalReportTask` stays on the source even though it names the same work. Billing charges one
    flat credit per report whose implementation bridge shipped a pull request in the period
    (`billing.get_signals_billing_credits_by_team`), so moving a bridge would collapse two charges
    into one and could make the survivor look billed in an earlier period. The survivor still
    reaches the work through the `task_run` and `pull_request` artefacts that do move, which is
    what implementation-PR resolution reads.
    """
    survivor_comments = set(
        SignalReportGithubComment.all_teams.filter(report_id=survivor.id).values_list("repository", "number"),
    )
    for comment in SignalReportGithubComment.all_teams.filter(team_id=source.team_id, report_id=source.id):
        if (comment.repository, comment.number) in survivor_comments:
            continue
        comment.report_id = survivor.id
        comment.save(update_fields=["report", "updated_at"])

    SignalReportCheck.objects.for_team(source.team_id).filter(report_id=source.id).update(report_id=survivor.id)


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
        # An artefact's `claim` must name a claim on the same report and claim history stays on the
        # source, so the pointer is dropped rather than left dangling. Actor attribution, which is
        # what the work log renders, is preserved.
        .update(report_id=survivor.id, claim=None)
    )

    _move_side_rows(source, survivor)

    # From the source's Postgres counters rather than a ClickHouse count, because the pipeline
    # maintains these and the promotion gate reads them, so the survivor stays exact whatever the
    # re-emit's lag turns out to be. The source keeps its own as a historical record.
    SignalReport.objects.filter(id=survivor.id).update(
        signal_count=F("signal_count") + source.signal_count,
        total_weight=F("total_weight") + source.total_weight,
        # A scout's corroborations past the per-report note cap exist only as this counter, with no
        # artefact rows behind them, so leaving it on the source would drop the only record.
        corroboration_count=Coalesce(F("corroboration_count"), 0) + (source.corroboration_count or 0),
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


def _requested_source_ids(source_ids: list[str], *, survivor_id: str) -> list[str]:
    """The sources to merge, de-duplicated and in request order, or a `ReportMergeError`."""
    if not source_ids:
        raise ReportMergeError("At least one source report is required.")
    if len(source_ids) > MAX_MERGE_SOURCE_REPORTS:
        raise ReportMergeError(
            f"A merge takes at most {MAX_MERGE_SOURCE_REPORTS} source reports. Split it into several calls."
        )
    ordered: list[str] = []
    for raw_id in source_ids:
        key = str(raw_id)
        if key == survivor_id:
            raise ReportMergeError("A report cannot be merged into itself.")
        if key not in ordered:
            ordered.append(key)
    return ordered


def _mergeable_source(report: SignalReport | None, requested_id: str) -> SignalReport:
    if report is None:
        raise ReportMergeError(f"Report {requested_id} was not found in this project.")
    if report.status not in MERGEABLE_STATUSES:
        raise ReportMergeError(
            f"Report {requested_id} is {report.status} and cannot be merged. Only a live report can be a source."
        )
    # The signal move reads one bounded page and never pages or retries, so a source past the cap
    # would leave the remainder pointing at itself while the survivor's counters already include
    # them. Refusing upfront keeps that inconsistency from being created at all.
    if report.signal_count > REASSIGN_SIGNAL_ROW_CAP:
        raise ReportMergeError(
            f"Report {requested_id} has more than {REASSIGN_SIGNAL_ROW_CAP} signals and is too large to merge."
        )
    return report


def merge_reports(
    *,
    team: Team,
    survivor: SignalReport,
    source_ids: list[str],
    attribution: ArtefactAttribution,
    reason: str | None = None,
) -> MergeResult:
    """Fold every source report into `survivor`, atomically.

    Raises `ReportMergeError` when the survivor or a source is not a live report of this team, or
    when a source names the survivor itself. Either the whole call applies or none of it does, so a caller never has to
    reason about a half-merged pair.
    """
    ordered_ids = _requested_source_ids(source_ids, survivor_id=str(survivor.id))

    with transaction.atomic():
        # Locked in id order, survivor included, so overlapping merges queue instead of deadlocking.
        locked = {
            str(report.id): report
            for report in SignalReport.objects.select_for_update()
            .filter(team_id=team.id, id__in=sorted({*ordered_ids, str(survivor.id)}))
            .order_by("id")
        }
        if str(survivor.id) not in locked:
            raise ReportMergeError("The report to merge into was not found in this project.")
        survivor = locked[str(survivor.id)]
        if survivor.status not in MERGEABLE_STATUSES:
            raise ReportMergeError(
                f"The report to merge into is {survivor.status} and cannot take on duplicates. "
                "Only a live report can be the survivor."
            )
        sources = [_mergeable_source(locked.get(source_id), source_id) for source_id in ordered_ids]

        try:
            merged = [
                _merge_source_into(survivor=survivor, source=source, attribution=attribution, reason=reason)
                for source in sources
            ]
        except ArtefactContentValidationError as e:
            # `add_log` enforces the `report_link` invariants, so a merge that would close a
            # duplicate_of cycle is a merge the caller cannot have, not a server fault.
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
    """Queue the ClickHouse move, and never fail the request if the broker refuses it.

    This runs after the merge has committed, and a retried call answers 409 because the sources
    are archived by then, so raising here would report a completed merge as a 500 with no way to
    re-drive it. Grouping still routes new matches through the merge pointer, so the cost of a
    lost dispatch is that the moved signals stay indexed under the archived source.
    """
    from products.signals.backend.tasks import (  # noqa: PLC0415 — keeps the celery app off the API import path
        move_merged_report_signals,
    )

    try:
        move_merged_report_signals.delay(team_id=team_id, survivor_report_id=survivor_id, source_report_ids=source_ids)
    except Exception:
        logger.exception(
            "signals_merged_report_signal_move_not_queued",
            team_id=team_id,
            survivor_report_id=survivor_id,
            source_report_ids=source_ids,
        )
