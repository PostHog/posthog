"""The fact sheet: the ranked items and the only facts the writer may use."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from .candidates import URGENCY_LABELS, FactValue
from .ranking import RankedItem

# What each reason means for the person, so the writer can say why an item needs them.
REASON_GLOSSARY = {
    "claimed_by_you": "A self-driving report the person has claimed and is working on.",
    "waiting_for_you": "A self-driving report that stopped because it needs the person's answer or decision.",
    "suggested_reviewer": "A self-driving report that names the person as the right reviewer.",
    "urgent_for_project": "A P0 self-driving report that nobody in the project owns yet.",
    "dashboard_you_viewed": "A dashboard the person opened recently whose biggest metric moved week over week.",
    "insight_you_viewed": "An insight the person opened recently that moved week over week.",
    "alert_firing": "An alert on an insight the person set up that is firing right now.",
    "assigned_ticket": "A support ticket assigned to the person. Only metadata, never the customer's words.",
    "assigned_error_issue": "An active error tracking issue assigned to the person or one of their roles.",
    "review_requested": "A pull request where someone asked the person by name for a review.",
    "your_pull_request": "A pull request the person wrote that is failing checks or is approved and ready to merge.",
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
    urgency_label: str
    in_text: bool
    top: bool
    facts: dict[str, FactValue]

    @property
    def source_product(self) -> str | None:
        """For a report, the product its signals came from."""
        value = self.facts.get("source_product")
        return str(value) if value else None


class FactSheetCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    items_in_text: int
    reports_in_text: int


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
        counts=FactSheetCounts(
            items_in_text=sum(1 for i in items if i.in_text),
            reports_in_text=sum(1 for i in items if i.in_text and i.candidate.group == ItemGroup.REPORT),
        ),
        failed_sources=failed_sources,
        reason_glossary={
            reason: REASON_GLOSSARY[reason]
            for reason in sorted({item.candidate.reason.value for item in items})
            if reason in REASON_GLOSSARY
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
                urgency_label=URGENCY_LABELS.get(item.candidate.urgency, "when you have time"),
                in_text=item.in_text,
                top=item.top,
                facts=item.candidate.facts,
            )
            for item in items
        ],
    )
