"""The fact sheet: the items behind a briefing and the facts its text rests on, as the agent stored them."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from ..models import DailyBriefing

FactValue = str | int | float | bool | None

# The urgency scale the agent ranks on. Lower is more urgent.
URGENCY_LABELS = {0: "act now", 1: "today", 2: "this week", 3: "when you have time"}


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
