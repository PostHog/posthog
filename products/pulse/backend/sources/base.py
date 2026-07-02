from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig


class EvidenceRef(TypedDict):
    type: str  # "insight" | "dashboard" | "annotation" | ...
    ref: str
    label: str


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: str  # "movement" | "context" | "health" | ...
    title: str
    description: str
    numbers: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    fingerprint_hint: str = ""


class BriefSource(Protocol):
    name: str

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]: ...
