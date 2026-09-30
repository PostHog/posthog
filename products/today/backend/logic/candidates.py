"""The item type every source returns and the ranker orders."""

from datetime import datetime
from typing import Any

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

    def to_payload(self) -> dict[str, Any]:
        """Plain JSON, so a Temporal activity can return it under either data converter."""
        return {
            "key": self.key,
            "group": self.group.value,
            "source": self.source.value,
            "reason": self.reason.value,
            "title": self.title,
            "url": self.url,
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
