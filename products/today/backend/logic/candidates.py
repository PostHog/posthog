"""The item type every source returns and the ranker orders."""

from datetime import datetime
from typing import Any

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


@frozen
class Candidate:
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

    def to_payload(self) -> dict[str, Any]:
        """Plain JSON, so a Temporal activity can return it under either data converter."""
        return {
            "key": self.key,
            "group": self.group.value,
            "source": self.source.value,
            "reason": self.reason.value,
            "title": self.title,
            "url": self.url,
            "urgency": self.urgency,
            "sort_key": list(self.sort_key),
            "facts": dict(self.facts),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Candidate":
        return cls(
            key=payload["key"],
            group=ItemGroup(payload["group"]),
            source=ItemSource(payload["source"]),
            reason=ItemReason(payload["reason"]),
            title=payload["title"],
            url=payload["url"],
            urgency=int(payload["urgency"]),
            sort_key=tuple(payload["sort_key"]),
            facts=dict(payload["facts"]),
        )


@frozen
class SourceContext:
    team: Team
    user: User
    now: datetime


def app_url(team_id: int, path: str) -> str:
    return f"/project/{team_id}/{path.lstrip('/')}"
