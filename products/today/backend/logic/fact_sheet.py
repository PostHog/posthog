"""The fact sheet: the ranked items and the only facts the writer may use."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from ..models import DailyBriefing
from .candidates import URGENCY_LABELS, FactValue
from .ranking import RankedItem

# What each reason means for the person, so the writer can say why an item needs them.
REASON_GLOSSARY: dict[ItemReason, str] = {
    ItemReason.CLAIMED_BY_YOU: "A self-driving report the person has claimed and is working on.",
    ItemReason.WAITING_FOR_YOU: "A self-driving report that stopped because it needs the person's answer or decision.",
    ItemReason.SUGGESTED_REVIEWER: "A self-driving report that names the person as the right reviewer.",
    ItemReason.URGENT_FOR_PROJECT: "A P0 self-driving report that nobody in the project owns yet.",
    ItemReason.DASHBOARD_YOU_VIEWED: "A dashboard the person opened recently whose biggest metric moved week over week.",
    ItemReason.INSIGHT_YOU_VIEWED: "An insight the person opened recently that moved week over week.",
    ItemReason.ALERT_FIRING: "An alert on an insight the person set up that is firing right now.",
    ItemReason.ASSIGNED_TICKET: "A support ticket assigned to the person. Only metadata, never the customer's words.",
    ItemReason.ASSIGNED_ERROR_ISSUE: "An active error tracking issue assigned to the person or one of their roles.",
    ItemReason.REVIEW_REQUESTED: "A pull request where someone asked the person by name for a review.",
    ItemReason.YOUR_PULL_REQUEST: "A pull request the person wrote that is failing checks or is approved and ready to merge.",
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
    urgency: int
    in_text: bool
    top: bool
    source_product: str | None = None
    facts: dict[str, FactValue]


class FactSheetCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    items_in_text: int


class FactSheet(BaseModel):
    """Stored in `DailyBriefing.facts` and sent to the writer as JSON. Items are in rank order."""

    model_config = ConfigDict(frozen=True)

    first_name: str
    local_day: date
    counts: FactSheetCounts
    failed_sources: list[str]
    urgency_scale: dict[int, str] = Field(default_factory=lambda: dict(URGENCY_LABELS))
    reason_glossary: dict[str, str]
    items: list[FactSheetItem]

    @property
    def text_items(self) -> list[FactSheetItem]:
        return [item for item in self.items if item.in_text]


def stored_fact_sheet(briefing: DailyBriefing) -> FactSheet | None:
    """The briefing's fact sheet, or None for a row written before its draft."""
    return FactSheet.model_validate(briefing.facts) if briefing.facts else None


def build_fact_sheet(
    *,
    first_name: str,
    local_day: date,
    items: list[RankedItem],
    failed_sources: list[str],
) -> FactSheet:
    return FactSheet(
        first_name=first_name,
        local_day=local_day,
        counts=FactSheetCounts(items_in_text=sum(1 for i in items if i.in_text)),
        failed_sources=failed_sources,
        reason_glossary={
            reason.value: REASON_GLOSSARY[reason] for reason in sorted({item.candidate.reason for item in items})
        },
        items=[
            FactSheetItem(
                key=item.candidate.key,
                group=item.candidate.group,
                source=item.candidate.source,
                reason=item.candidate.reason,
                title=item.candidate.title,
                url=item.candidate.url,
                rank=item.rank,
                urgency=item.candidate.urgency,
                in_text=item.in_text,
                top=item.top,
                source_product=item.candidate.source_product,
                facts=item.candidate.facts,
            )
            for item in items
        ],
    )
