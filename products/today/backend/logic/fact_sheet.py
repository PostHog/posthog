"""The fact sheet: the items behind a briefing and the facts its text rests on, as the agent gave them."""

from pydantic import BaseModel, ConfigDict

from ..facade.enums import ItemGroup, ItemReason, ItemSource
from ..models import DailyBriefing


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
    source_product: str | None = None
    # Short facts as text, never free text written by customers.
    facts: dict[str, str]


class FactSheet(BaseModel):
    """Stored in `DailyBriefing.facts`. Items are in rank order; the first one is the top item."""

    model_config = ConfigDict(frozen=True)

    items: list[FactSheetItem]


def stored_fact_sheet(briefing: DailyBriefing) -> FactSheet | None:
    """The briefing's fact sheet, or None for a row the agent has not written yet."""
    return FactSheet.model_validate(briefing.facts) if briefing.facts else None
