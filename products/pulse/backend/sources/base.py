from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig


class EvidenceRef(TypedDict):
    type: str  # "insight" | "dashboard" | "annotation" | ...
    ref: str
    label: str


def format_evidence_ref(evidence: EvidenceRef) -> str:
    """Render an evidence ref as the "type:ref" token the LLM sees and cites back."""
    return f"{evidence['type']}:{evidence['ref']}"


def parse_evidence_ref(ref: str) -> EvidenceRef:
    """Inverse of format_evidence_ref, for LLM citations that match no gathered item."""
    prefix, sep, rest = ref.partition(":")
    return EvidenceRef(type=prefix, ref=rest if sep else prefix, label="")


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: str  # "movement" | "health" | ... (only "movement" for now)
    title: str
    description: str
    numbers: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    fingerprint_hint: str = ""


class BriefSource(Protocol):
    name: str

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]: ...
