"""Self-driving reports that relate to the person."""

from products.signals.backend.facade import api as signals

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import Candidate, SourceContext, app_url

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


def collect(ctx: SourceContext) -> list[Candidate]:
    reports = signals.reports_for_briefing(team_id=ctx.team.id, user_id=ctx.user.id)
    return [
        Candidate(
            key=f"report:{report.report_id}",
            group=ItemGroup.REPORT,
            source=ItemSource.SELF_DRIVING,
            reason=_REASON[report.relation],
            title=report.title,
            url=app_url(ctx.team.id, f"inbox/{report.report_id}"),
            sort_key=(
                _RELATION_ORDER[report.relation],
                _PRIORITY_ORDER.get(report.priority or "", 5),
                -report.updated_at.timestamp(),
            ),
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
