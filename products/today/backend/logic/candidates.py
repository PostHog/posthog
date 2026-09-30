"""The item type every source returns and the ranker orders."""

from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..facade.enums import ItemGroup, ItemReason, ItemSource

FactValue = str | int | float | bool | None


@frozen
class Candidate:
    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    url: str
    # Compared ascending inside the item's group; each source defines its own order.
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
