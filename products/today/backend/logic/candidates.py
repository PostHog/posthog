"""The item type every source returns and the ranker orders."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..facade.enums import ItemGroup, ItemReason, ItemSource

FactValue = str | int | float | bool | None

# The scale every source maps its own facts onto, so items of different kinds can be compared.
# Lower is more urgent. The writer gets the label of each tier next to the item.
URGENCY_LABELS = {0: "act now", 1: "today", 2: "this week", 3: "when you have time"}
URGENCY_ACT_NOW = 0
URGENCY_TODAY = 1
URGENCY_THIS_WEEK = 2
URGENCY_WHEN_FREE = 3


class Candidate(BaseModel):
    """One item a source found. Crosses the Temporal boundary as JSON, so it validates on the way back."""

    model_config = ConfigDict(frozen=True)

    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    url: str
    urgency: int
    # Compared ascending among items of the same urgency and group; each source defines its own order.
    sort_key: tuple[float, ...]
    # Short scalar facts only. Never free text written by customers.
    facts: dict[str, FactValue]


@frozen
class SourceContext:
    team: Team
    user: User
    now: datetime


def app_url(team_id: int, path: str) -> str:
    return f"/project/{team_id}/{path.lstrip('/')}"
