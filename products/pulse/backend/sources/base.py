from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig

SourceItemKind = Literal["movement", "context", "health"]
EvidenceType = Literal["insight", "dashboard", "annotation", "alert", "subscription"]


class EvidenceRef(TypedDict):
    type: EvidenceType
    ref: str
    label: str


def format_evidence_ref(evidence: EvidenceRef) -> str:
    """Render an evidence ref as the "type:ref" token the LLM sees and cites back."""
    return f"{evidence['type']}:{evidence['ref']}"


def parse_evidence_ref(ref: str) -> EvidenceRef:
    """Inverse of format_evidence_ref, for LLM citations that match no gathered item."""
    prefix, sep, rest = ref.partition(":")
    return EvidenceRef(type=prefix, ref=rest if sep else prefix, label="")


def build_fingerprint_hint(source_name: str, *refs: str) -> str:
    """Canonical fingerprint grammar: `{source.name}:{stable-ref}[:{stable-ref}...]`.

    Dismissal suppression keys off persisted fingerprints, so every source must mint
    hints through this helper — changing the grammar later orphans suppressions.
    """
    return ":".join([source_name, *refs])


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: SourceItemKind
    title: str
    description: str
    numbers: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    fingerprint_hint: str = ""


class BriefSource(Protocol):
    name: str

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]: ...
