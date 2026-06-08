from typing import Any

from pydantic import BaseModel, Field

from posthog.schema import PulseScanConfig

# PulseScanConfig is the single source of truth in the query schema
# (frontend/src/queries/schema/schema-general.ts → generated into posthog/schema.py), so the TS type and the
# pydantic model are one definition. Imported here for the activity-input defaults below.
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.sync import database_sync_to_async


@database_sync_to_async
def run_trends_query_sync(team: Team, query_json: dict) -> Any:
    """Execute an opaque TrendsQuery against ClickHouse and return the result dict.

    Shared by detection (headline metric) and narrative (breakdown attribution).
    """
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415

    response = process_query_dict(
        team=team,
        query_json=query_json,
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    )
    return response.model_dump() if hasattr(response, "model_dump") else response


class MetricDescriptor(BaseModel):
    """Opaque descriptor of a metric Pulse can re-evaluate.

    `source` traces where the candidate came from (for debugging).
    `query` is a TrendsQuery-shaped dict, executable against the existing query runner.
    """

    source: str  # "dashboard_tile" | "recent_insight" | "saved_insight" | "top_event" | "scout_anomaly"
    source_id: str | int | None = None
    label: str
    query: dict[str, Any]
    url: str | None = None  # deep-link to the source (e.g. /insights/<short_id>), surfaced as "View insight"


class CandidateMetric(BaseModel):
    descriptor: MetricDescriptor


class Finding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float
    # Recent completed-week values (oldest→newest, current week last) for the card's trend sparkline.
    series: list[float] | None = None


class EnrichedFinding(BaseModel):
    descriptor: MetricDescriptor
    current_value: float
    baseline_value: float
    change_pct: float
    impact: float
    robust_z: float
    attribution_breakdown: dict[str, Any] | None = None
    # Supporting evidence, e.g. {"session_ids": [...]} for example replays. None when none found.
    evidence: dict[str, Any] | None = None
    narrative: str


class FetchFindingsInputs(BaseModel):
    team_id: int
    period_start: str
    period_end: str
    config: PulseScanConfig = Field(default_factory=PulseScanConfig)


class EnrichFindingsInputs(BaseModel):
    team_id: int
    user_id: int | None = None
    findings: list[Finding]
    max_findings: int = 5
    # Period bounds (ISO) used to scope the replay-evidence window. Empty disables evidence collection.
    period_start: str = ""
    period_end: str = ""


class DeliverDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    findings: list[EnrichedFinding]


class SynthesizeDigestInputs(BaseModel):
    team_id: int
    digest_id: str
    user_id: int | None = None
    findings: list[EnrichedFinding]
    period_start: str = ""
    period_end: str = ""
