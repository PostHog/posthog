"""DimensionScore and ProductScore data types."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..isolation import IsolationStatus


@dataclass
class DimensionScore:
    name: str
    score: int  # 0-100
    detail: str  # human-readable explanation
    applicable: bool = True  # False = dimension doesn't apply to this product
    # Agent-actionable steps to raise the score. Only populated when score < 100.
    # Each entry is a single sentence the agent can act on directly.
    next_steps: list[str] = field(default_factory=list)
    # Skill slash commands to invoke (e.g. "/isolating-product-facade-contracts")
    # before attempting the work.
    skills: list[str] = field(default_factory=list)
    # Structured findings the scorer surfaced — list of (label, items) sections.
    # Items are pre-formatted strings (e.g. "presentation/views.py:42",
    # "products.foo.backend.models"). Rendered uniformly between to-fix and skills.
    evidence: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class ProductScore:
    product: str
    display_name: str = ""
    owners: list[str] = field(default_factory=list)
    dimensions: list[DimensionScore] = field(default_factory=list)
    # External-vs-internal seal synthesis. None for products with no backend.
    isolation: IsolationStatus | None = None

    @property
    def overall(self) -> int | None:
        applicable = [d for d in self.dimensions if d.applicable]
        if not applicable:
            return None
        return round(sum(d.score for d in applicable) / len(applicable))

    @property
    def dimension_map(self) -> dict[str, DimensionScore]:
        return {d.name: d for d in self.dimensions}
