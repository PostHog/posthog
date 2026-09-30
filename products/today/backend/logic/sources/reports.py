"""Self-driving reports that relate to the person."""

from products.signals.backend.facade import api as signals

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import (
    URGENCY_ACT_NOW,
    URGENCY_THIS_WEEK,
    URGENCY_TODAY,
    URGENCY_WHEN_FREE,
    Candidate,
    SourceContext,
    app_url,
)
from .base import Source

_RELATION_ORDER = {
    signals.BriefingReportRelation.CLAIMED: 0,
    signals.BriefingReportRelation.WAITING_FOR_YOU: 1,
    signals.BriefingReportRelation.SUGGESTED_REVIEWER: 2,
    signals.BriefingReportRelation.URGENT_UNOWNED: 3,
}
_REASON = {
    signals.BriefingReportRelation.CLAIMED: ItemReason.CLAIMED_BY_YOU,
    signals.BriefingReportRelation.WAITING_FOR_YOU: ItemReason.WAITING_FOR_YOU,
    signals.BriefingReportRelation.SUGGESTED_REVIEWER: ItemReason.SUGGESTED_REVIEWER,
    signals.BriefingReportRelation.URGENT_UNOWNED: ItemReason.URGENT_FOR_PROJECT,
}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def _urgency(report: signals.BriefingReport) -> int:
    """A report the person blocks, or a P0, is for now; a claim or a P1 review is for today."""
    if report.priority == "P0" or report.relation in (
        signals.BriefingReportRelation.WAITING_FOR_YOU,
        signals.BriefingReportRelation.URGENT_UNOWNED,
    ):
        return URGENCY_ACT_NOW
    if report.relation == signals.BriefingReportRelation.CLAIMED or report.priority == "P1":
        return URGENCY_TODAY
    if report.priority in ("P2", None):
        return URGENCY_THIS_WEEK
    return URGENCY_WHEN_FREE


def _sort_key(report: signals.BriefingReport) -> tuple[float, ...]:
    """Relation first. Inside a relation: P0, then the higher chance of a merged PR, then priority, then newest.

    A report without a score (not scored yet, or scoring is off) follows the scored ones, so with
    no scores at all the order falls back to priority.
    """
    merge_chance = report.pr_merged_probability
    return (
        _RELATION_ORDER[report.relation],
        0 if report.priority == "P0" else 1,
        0 if merge_chance is not None else 1,
        -(merge_chance or 0.0),
        _PRIORITY_ORDER.get(report.priority or "", 5),
        -report.updated_at.timestamp(),
    )


class ReportsSource(Source):
    name = "reports"

    def collect(self, ctx: SourceContext) -> list[Candidate]:
        reports = signals.reports_for_briefing(team_id=ctx.team.id, user_id=ctx.user.id)
        return [
            Candidate(
                key=f"report:{report.report_id}",
                group=ItemGroup.REPORT,
                source=ItemSource.SELF_DRIVING,
                reason=_REASON[report.relation],
                title=report.title,
                url=app_url(ctx.team.id, f"inbox/{report.report_id}"),
                urgency=_urgency(report),
                sort_key=_sort_key(report),
                facts={
                    "priority": report.priority,
                    "status": report.status,
                    "has_implementation_pr": report.has_implementation_pr,
                    "summary": report.summary,
                },
            )
            for report in reports
        ]


def reports_for_me_count(ctx: SourceContext) -> int:
    return signals.reports_for_me_count(team_id=ctx.team.id, user_id=ctx.user.id)
