"""The fact sheet: the items behind a briefing and the facts its text rests on."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from products.signals.backend.facade import api as signals

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from ..models import DailyBriefing

# The relation signals gives a report, as the reason the page shows for the item.
_REASON_FOR_RELATION = {
    signals.BriefingReportRelation.WAITING_FOR_YOU: ItemReason.WAITING_FOR_YOU,
    signals.BriefingReportRelation.CLAIMED: ItemReason.CLAIMED_BY_YOU,
    signals.BriefingReportRelation.SUGGESTED_REVIEWER: ItemReason.SUGGESTED_REVIEWER,
    signals.BriefingReportRelation.URGENT_UNOWNED: ItemReason.URGENT_FOR_PROJECT,
}


class FactSheetItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    url: str
    rank: int
    source_product: str | None = None
    # Short facts as text, never free text written by customers.
    facts: dict[str, str]


class FactSheet(BaseModel):
    """Stored in `DailyBriefing.facts`. Items are in rank order; the first one is the top item."""

    model_config = ConfigDict(frozen=True)

    items: list[FactSheetItem]


def stored_fact_sheet(briefing: DailyBriefing) -> FactSheet | None:
    """The briefing's fact sheet, or None for a row that is not written yet."""
    return FactSheet.model_validate(briefing.facts) if briefing.facts else None


def _report_facts(report: signals.BriefingReport) -> dict[str, str]:
    facts = {"status": report.status, "implementation_pr": "yes" if report.has_implementation_pr else "no"}
    if report.priority:
        facts["priority"] = report.priority
    return facts


def fact_sheet_for_reports(reports: Sequence[signals.BriefingReport], team_id: int) -> FactSheet:
    """The briefing's items: the reports in the order signals ranked them for the person."""
    return FactSheet(
        items=[
            FactSheetItem(
                key=f"report:{report.report_id}",
                group=ItemGroup.REPORT,
                source=ItemSource.SELF_DRIVING,
                reason=_REASON_FOR_RELATION[report.relation],
                title=report.title,
                url=f"/project/{team_id}/inbox/{report.report_id}",
                rank=rank,
                source_product=report.source_products[0] if report.source_products else None,
                facts=_report_facts(report),
            )
            for rank, report in enumerate(reports, start=1)
        ]
    )
