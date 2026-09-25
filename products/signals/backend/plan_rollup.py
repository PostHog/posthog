"""A plan closes when its steps do.

A `part_of` link says "this report is a step in that plan". The steps carry the work and each one
closes on its own pull request; the plan usually carries nothing of its own, so without this module
it stays in the inbox forever after the last step merges.

The roll-up runs from the report's status change rather than from the pull request webhook, so
every way a step can close reaches it: a merged pull request, a manual resolve in the inbox, a
bulk state change, and an MCP state write. Plenty of steps close without a pull request at all.
"""

from django.db import transaction

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
)
from products.signals.backend.report_links import incoming_links, outgoing_links

logger = structlog.get_logger(__name__)

# The walk has to reach every hierarchy the write path accepts, or a plan deeper than the budget
# stays open forever: nothing re-runs the roll-up for it, because the steps that would have
# triggered it are already closed. `validated_report_link_write` accepts a `part_of` chain up to
# `MAX_REPORT_LINK_GRAPH_LEVELS`, so that is the depth this walk must finish, and matching it keeps
# the two from drifting apart. A level costs one indexed read, and a cycle is rejected on write.
MAX_PLAN_ROLLUP_LEVELS = SignalReportArtefact.MAX_REPORT_LINK_GRAPH_LEVELS

_CLOSED_STATUSES = (SignalReport.Status.RESOLVED, SignalReport.Status.SUPPRESSED)


def _pending_replacement(team_id: int, report_id: str) -> bool:
    """A plan waiting on a replacement is mid-decision, so it is left alone like any other report."""
    from products.signals.backend.supersession import pending_replacement

    # Writer-pinned like every other read this walk decides on: the replacement may have been
    # written moments ago by the same close that triggered this roll-up, and reading a replica that
    # has not caught up would close a plan whose replacement is still running.
    return pending_replacement(team_id, report_id, using="default") is not None


# A pull request in any of these states is still going somewhere. A merged or closed one
# already moved the report through `_apply_pr_report_state`, so it decides nothing here, and
# `unknown` counts as live for the same reason the link gates count it as work: it is the column
# default and the state an attach keeps when the GitHub lookup fails.
_LIVE_PR_STATES = (
    SignalReportPullRequest.State.OPEN,
    SignalReportPullRequest.State.DRAFT,
    SignalReportPullRequest.State.UNKNOWN,
)


def _own_work_in_flight(team_id: int, report_id: str) -> bool:
    """A plan someone pressed Implement on carries its own pull request, so its steps do not decide it.

    Closing it on the steps' verdict would hide a plan whose own work is still open, and an archiving
    roll-up would go further: the dismissal receiver closes the live pull request behind it.
    """
    from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports

    prs = fetch_implementation_prs_for_reports([report_id], team_id=team_id, using="default").get(report_id, [])
    return any(pr.state in _LIVE_PR_STATES for pr in prs)


def _rolled_up_status(*, team_id: int, parent: SignalReport) -> SignalReport.Status | None:
    """The status the plan's steps put it in, or None while they disagree or work remains.

    Every step resolved (or resolved and archived together, with at least one resolved) resolves
    the plan, because the plan's work is done. Every step archived archives the plan, because
    nobody is going to do it. Any step still open leaves the plan alone.

    A deleted step is not a verdict, so it is dropped rather than counted either way. The reader
    already drops a deleted source; the status filter keeps that true if a caller ever asks the
    reader for deleted sources. A plan whose every step was deleted has no steps left and stays
    where it is.
    """
    child_ids = [
        edge.source_id for edge in incoming_links(team_id=team_id, report_id=parent.id, kinds=(ReportLinkKind.PART_OF,))
    ]
    if not child_ids:
        return None
    statuses = list(
        SignalReport.objects.using("default")
        .filter(team_id=team_id, id__in=child_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("status", flat=True)
    )
    if not statuses:
        return None
    if any(status not in _CLOSED_STATUSES for status in statuses):
        return None
    if any(status == SignalReport.Status.RESOLVED for status in statuses):
        return SignalReport.Status.RESOLVED
    return SignalReport.Status.SUPPRESSED


def _close_parent(*, parent: SignalReport, target: SignalReport.Status) -> bool:
    """Apply the rolled-up status to the plan. True when the status actually moved.

    Archiving a resolved plan is refused for the same reason `_apply_pr_report_state` refuses it:
    a resolve is a person's verdict, and a later archived step must not undo it.
    """
    if parent.status == target:
        return False
    if target == SignalReport.Status.SUPPRESSED and parent.status == SignalReport.Status.RESOLVED:
        return False
    try:
        updated_fields = parent.transition_to(target)
    except (InvalidStatusTransition, ValueError, TypeError):
        logger.info(
            "signals.plan_rollup.transition_skipped",
            report_id=str(parent.id),
            report_status=parent.status,
            target=target.value,
        )
        return False
    # The walk below already visits this report's own parents, so the status-change receiver must
    # not start a second walk from here.
    parent._plan_rollup = True  # type: ignore[attr-defined]
    with transaction.atomic():
        parent.save(update_fields=updated_fields)
        if target == SignalReport.Status.SUPPRESSED:
            SignalReportArtefact.append_dismissal(
                team_id=parent.team_id,
                report_id=str(parent.id),
                content=Dismissal(),
                attribution=ArtefactAttribution.system(),
            )
    return True


def roll_up_plan_parents(*, team_id: int, report_id: str, include_report: bool = False) -> list[str]:
    """Close the plans a just-closed step belongs to, and their plans in turn.

    Returns the ids of the reports whose status moved, newest ancestor last, which is what the
    tests assert on.
    """
    frontier = [
        edge.target_id for edge in outgoing_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.PART_OF,))
    ]
    if include_report:
        frontier = [str(report_id)]
    visited: set[str] = set() if include_report else {str(report_id)}
    closed: list[str] = []
    for _ in range(MAX_PLAN_ROLLUP_LEVELS):
        if not frontier:
            return closed
        next_frontier: list[str] = []
        for parent_id in frontier:
            if parent_id in visited:
                continue
            visited.add(parent_id)
            with transaction.atomic():
                parent = SignalReport.objects.select_for_update().filter(team_id=team_id, id=parent_id).first()
                if parent is None or parent.status == SignalReport.Status.DELETED:
                    continue
                if _pending_replacement(team_id, parent_id):
                    continue
                if _own_work_in_flight(team_id, parent_id):
                    continue
                target = _rolled_up_status(team_id=team_id, parent=parent)
                if target is None:
                    # Undecided now, not undecided forever: a step of this plan may be a plan that
                    # closes later in this same walk. A step can be `part_of` both its plan and
                    # that plan's plan, and the shortcut edge can be the older one, so the walk
                    # reaches the outer plan before the inner one settles. Unmark it, and the
                    # level bound still bounds the walk.
                    visited.discard(parent_id)
                    continue
                if _close_parent(parent=parent, target=target):
                    closed.append(parent_id)
                if parent.status not in _CLOSED_STATUSES:
                    continue
            next_frontier.extend(
                edge.target_id
                for edge in outgoing_links(team_id=team_id, report_id=parent_id, kinds=(ReportLinkKind.PART_OF,))
            )
        frontier = next_frontier
    logger.warning("signals.plan_rollup.depth_exceeded", report_id=str(report_id), team_id=team_id)
    return closed
