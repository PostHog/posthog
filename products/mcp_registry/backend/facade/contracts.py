"""Contract types for the MCP registry product.

Stable, framework-free frozen dataclasses that define what this product exposes to
the rest of the codebase, and what its own presentation layer serializes. No Django,
no DRF imports — a `components`/`why` payload is a plain dict of JSON scalars, not an
ORM JSONField instance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

JSONScalar = str | int | float | bool | None


@dataclass(frozen=True)
class RegistryTool:
    name: str
    description: str
    input_schema: dict[str, JSONScalar]
    source: str
    last_seen_at: datetime


@dataclass(frozen=True)
class MeasuredStats:
    window_days: int
    calls: int
    sessions: int
    errors: int
    error_rate_pct: float
    intent_coverage_pct: float
    distinct_tools: int
    harness_count: int
    tool_stats: list[dict[str, JSONScalar]]
    link_method: str
    link_candidates: list[str]
    computed_at: datetime


@dataclass(frozen=True)
class ScoreInfo:
    version: str
    score: float
    components: dict[str, JSONScalar]
    computed_at: datetime | None


@dataclass(frozen=True)
class RankingRunInfo:
    id: UUID
    server_count: int
    computed_at: datetime | None


@dataclass(frozen=True)
class RegistryServerSummary:
    id: UUID
    registry_name: str
    display_name: str
    description: str
    canonical_url: str
    liveness: str
    auth_method: str
    listed_in_registry: bool
    is_measured: bool
    rank_score: float | None


@dataclass(frozen=True)
class RegistryServerDetail(RegistryServerSummary):
    remotes: list[dict[str, JSONScalar]] = field(default_factory=list)
    packages: list[dict[str, JSONScalar]] = field(default_factory=list)
    repository_url: str = ""
    website_url: str = ""
    last_probed_at: datetime | None = None
    tools: list[RegistryTool] = field(default_factory=list)
    measured_stats: list[MeasuredStats] = field(default_factory=list)
    scores: list[ScoreInfo] = field(default_factory=list)
    connect_instructions: dict[str, JSONScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoverCandidate:
    rank: int
    id: UUID
    registry_name: str
    title: str
    description: str
    score: float
    why: dict[str, JSONScalar]
    liveness: str
    auth_method: str
    measured: dict[str, JSONScalar] | None
    matched_tools: list[dict[str, JSONScalar]]
    connect: dict[str, JSONScalar]


@dataclass(frozen=True)
class MeasuredProject:
    team_id: int
    servers: int
    calls: int


@dataclass(frozen=True)
class RankingVersionInfo:
    version: str
    description: str
    is_default: bool
    latest_run: RankingRunInfo | None


@dataclass(frozen=True)
class CompareRow:
    rank: int
    id: UUID
    registry_name: str
    display_name: str
    score: float
    is_measured: bool
