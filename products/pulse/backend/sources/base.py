from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.pulse.backend.models import BriefConfig, ResourceLink, ResourceType


# Kept in sync with models.ResourceType (same members) — a cited evidence ref becomes a ResourceLink.
class EvidenceType(StrEnum):
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    ANNOTATION = "annotation"
    EXPERIMENT = "experiment"
    ALERT = "alert"
    SUBSCRIPTION = "subscription"
    EVENT = "event"
    SIGNAL_REPORT = "signal_report"


class SourceItemKind(StrEnum):
    MOVEMENT = "movement"
    # Background that may explain movements (annotations, deploy markers); never an opportunity on its own.
    CONTEXT = "context"
    HEALTH = "health"
    # Pre-analyzed findings from PostHog's scout agents (signals inbox); weighed as evidence.
    SIGNAL = "signal"


@dataclass(frozen=True)
class EvidenceRef:
    """A cited PostHog resource. Owns its type-dispatch logic — its citation key, the ResourceLink
    resource_type and FK field it maps to — so callers never branch on `type` themselves."""

    type: EvidenceType
    ref: str
    label: str
    url: str = ""  # deep link into the app; "" when the ref has no navigable target

    def __post_init__(self) -> None:
        # The value crossing the Temporal boundary arrives as the enum's string (activity returns
        # asdict(item); synthesize rebuilds via SourceItem(**item)). Coerce it back so `type` is
        # always a real EvidenceType. `raw` is Any so the coercion isn't seen as dead code.
        raw: Any = self.type
        if not isinstance(raw, EvidenceType):
            object.__setattr__(self, "type", EvidenceType(raw))

    @property
    def key(self) -> tuple[EvidenceType, str]:
        """Stable identity of the cited resource — dedup and citation-id lookups key on this."""
        return (self.type, self.ref)

    @property
    def is_insight(self) -> bool:
        return self.type == EvidenceType.INSIGHT

    @property
    def citation(self) -> dict[str, str]:
        """Structured citation the frontend renders directly — no client-side parsing of the ref."""
        return {"type": self.type.value, "ref": self.ref, "label": self.label, "url": self.url}

    @property
    def metric_ref(self) -> dict[str, str] | None:
        """This ref's contribution to an opportunity's metric_ref, when it is the backing insight."""
        return {"insight_short_id": self.ref} if self.is_insight else None

    @property
    def resource_type(self) -> ResourceType:
        """The ResourceLink resource_type; a type with no Django model is stored as an event."""
        return ResourceType(self.type) if self.type in ResourceType.values else ResourceType.EVENT

    @property
    def fk_field(self) -> str | None:
        """Name of the ResourceLink FK to populate for this ref, or None for events (no model)."""
        return ResourceLink.fk_field_for(self.resource_type)


@dataclass(frozen=True)
class SourceItem:
    source: str
    kind: SourceItemKind
    title: str
    description: str
    # `metrics`, not `numbers`: these are the source's computed metric values (pct_change,
    # totals, ...) that the LLM may reference and that become the opportunity baseline snapshot.
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    fingerprint_hint: str = ""

    def __post_init__(self) -> None:
        # Same Temporal-boundary coercion as EvidenceRef: rebuild the enum and nested EvidenceRefs
        # from the strings/dicts that come back via asdict(item) -> SourceItem(**item). The `raw`
        # locals are Any so the type checker doesn't treat the coercion as unreachable.
        raw_kind: Any = self.kind
        if not isinstance(raw_kind, SourceItemKind):
            object.__setattr__(self, "kind", SourceItemKind(raw_kind))
        raw_evidence: list[Any] = list(self.evidence)
        if raw_evidence and not isinstance(raw_evidence[0], EvidenceRef):
            object.__setattr__(self, "evidence", [EvidenceRef(**e) for e in raw_evidence])


def build_evidence_index(items: list[SourceItem]) -> dict[str, EvidenceRef]:
    """Assign stable citation ids (c1..cN) to the distinct evidence refs across all items.

    Deduped by ref key in item then evidence order, so the same physical resource cited by two
    items shares one id. Both synthesize (rendering ids for the LLM) and persist (resolving the
    ids the LLM cited back to structured refs) call this on the same items, so the ids match
    deterministically without passing the index across the Temporal boundary.
    """
    index: dict[str, EvidenceRef] = {}
    seen: dict[tuple[EvidenceType, str], str] = {}
    for item in items:
        for evidence in item.evidence:
            if evidence.key in seen:
                continue
            citation_id = f"c{len(seen) + 1}"
            seen[evidence.key] = citation_id
            index[citation_id] = evidence
    return index


class BriefSource(Protocol):
    name: str

    def gather(
        self, team: Team, config: BriefConfig | None, lookback_days: int, user_access_control: UserAccessControl
    ) -> list[SourceItem]: ...
