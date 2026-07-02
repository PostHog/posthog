from dataclasses import dataclass, field
from typing import Protocol

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: str  # "movement" | "health" | ... (only "movement" for now)
    title: str
    description: str
    numbers: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    fingerprint_hint: str = ""


class BriefSource(Protocol):
    name: str

    def has_data(self, team: Team, config: BriefConfig | None) -> bool: ...

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]: ...
