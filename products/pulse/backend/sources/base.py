from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypedDict

from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig


# Kept in sync with models.ResourceType (same members) — a cited evidence ref becomes a ResourceLink.
class EvidenceType(StrEnum):
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    ANNOTATION = "annotation"
    EXPERIMENT = "experiment"
    EVENT = "event"


class SourceItemKind(StrEnum):
    MOVEMENT = "movement"
    HEALTH = "health"


class EvidenceRef(TypedDict):
    type: str  # one of EvidenceType
    ref: str
    label: str
    url: str  # deep link into the app; "" when the ref has no navigable target


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: str  # one of SourceItemKind
    title: str
    description: str
    # `metrics`, not `numbers`: these are the source's computed metric values (pct_change,
    # totals, ...) that the LLM may reference and that become the opportunity baseline snapshot.
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    fingerprint_hint: str = ""


def build_evidence_index(items: list[SourceItem]) -> dict[str, EvidenceRef]:
    """Assign stable citation ids (c1..cN) to the distinct evidence refs across all items.

    Deduped by (type, ref) in item then evidence order, so the same physical resource cited by
    two items shares one id. Both synthesize (rendering ids for the LLM) and persist (resolving
    the ids the LLM cited back to structured refs) call this on the same items, so the ids match
    deterministically without passing the index across the Temporal boundary.
    """
    index: dict[str, EvidenceRef] = {}
    seen: dict[tuple[str, str], str] = {}
    for item in items:
        for evidence in item.evidence:
            key = (evidence["type"], evidence["ref"])
            if key in seen:
                continue
            citation_id = f"c{len(seen) + 1}"
            seen[key] = citation_id
            index[citation_id] = evidence
    return index


class BriefSource(Protocol):
    name: str

    def gather(self, team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]: ...
