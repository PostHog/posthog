import json
import hashlib
from collections.abc import Sequence
from dataclasses import asdict
from datetime import timedelta
from enum import StrEnum
from math import ceil
from typing import Any

from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.schema_enums import DataWarehouseSavedQueryOrigin

from ..facade.enums import WarehouseSuggestionKind

TERABYTE = 10**12
TEMPORAL_QUERY_KIND = "temporal"
DAGSTER_QUERY_KIND = "dagster"
RULES_VERSION_LENGTH = 12


class Surface(StrEnum):
    MCP = "mcp"
    POSTHOG_AI = "posthog_ai"
    DESKTOP = "desktop"
    ENDPOINTS = "endpoints"
    DASHBOARD = "dashboard"
    INSIGHT = "insight"
    SQL_EDITOR = "sql_editor"
    NOTEBOOK = "notebook"
    API = "api"
    APP = "app"
    UNKNOWN = "unknown"


class TagField(StrEnum):
    KIND = "lc_kind"
    PRODUCT = "lc_product"
    FEATURE = "lc_feature"
    ACCESS_METHOD = "lc_access_method"
    SOURCE = "source"
    SCENE = "scene"


@frozen
class SurfaceRule:
    surface: Surface
    field: TagField
    values: frozenset[str] | None


@frozen
class TrafficRules:
    background_features: frozenset[str]
    background_kinds: frozenset[str]
    requires_user_id: bool


@frozen
class SurfaceRules:
    rules: tuple[SurfaceRule, ...]


@frozen
class SubjectRules:
    excluded_view_origins: frozenset[str]


@frozen
class EligibilityRules:
    min_view_reads: int


@frozen
class CertifyRules:
    top_share: float
    min_users: int
    min_users_floor: int
    min_user_share: float
    min_days: int
    min_surfaces: int

    def users_needed(self, team_readers: int) -> int:
        return max(self.min_users_floor, min(self.min_users, ceil(team_readers * self.min_user_share)))


@frozen
class DeprecateRules:
    min_days_with_data: int
    seconds_floor: float
    bytes_floor: float
    counts_background_reads: bool


@frozen
class MaterializeRules:
    min_days: int
    min_requests: int
    min_users_or_surfaces: int
    min_alone_reads: int
    min_seconds_saved: float
    min_bytes_saved: float
    min_saved_share: float
    require_incremental_eligibility: bool


@frozen
class RefreshRules:
    max_interval: timedelta
    min_read_day_share_below_max_interval: float


@frozen
class LifecycleRules:
    reproposal_score_multiple: float
    expire_after_days: int
    max_surfaced_per_day: int
    max_open: int
    max_open_per_kind: int
    first_week_runs: int
    kind_order: tuple[WarehouseSuggestionKind, ...]
    first_week_kind_order: tuple[WarehouseSuggestionKind, ...]


@frozen
class Rules:
    window_days: int
    traffic: TrafficRules
    surfaces: SurfaceRules
    subjects: SubjectRules
    eligibility: EligibilityRules
    certify: CertifyRules
    deprecate: DeprecateRules
    materialize: MaterializeRules
    refresh: RefreshRules
    lifecycle: LifecycleRules


RULES = Rules(
    window_days=30,
    traffic=TrafficRules(
        background_features=frozenset(
            {
                Feature.CACHE_WARMUP,
                Feature.ALERTING,
                Feature.DATA_QUALITY_CHECK,
                Feature.MANAGEMENT_COMMAND,
                Feature.SCHEMA_INTROSPECTION,
                Feature.BILLING_ETL,
            }
        ),
        background_kinds=frozenset({TEMPORAL_QUERY_KIND, DAGSTER_QUERY_KIND}),
        requires_user_id=True,
    ),
    surfaces=SurfaceRules(
        rules=(
            SurfaceRule(
                surface=Surface.MCP, field=TagField.SOURCE, values=frozenset({EventSource.MCP, EventSource.CLI})
            ),
            SurfaceRule(surface=Surface.POSTHOG_AI, field=TagField.SOURCE, values=frozenset({EventSource.POSTHOG_AI})),
            SurfaceRule(surface=Surface.DESKTOP, field=TagField.SOURCE, values=frozenset({EventSource.DESKTOP})),
            SurfaceRule(
                surface=Surface.ENDPOINTS, field=TagField.FEATURE, values=frozenset({Feature.ENDPOINT_EXECUTION})
            ),
            SurfaceRule(surface=Surface.ENDPOINTS, field=TagField.PRODUCT, values=frozenset({Product.ENDPOINTS})),
            SurfaceRule(surface=Surface.DASHBOARD, field=TagField.SCENE, values=frozenset({"Dashboard"})),
            SurfaceRule(surface=Surface.INSIGHT, field=TagField.FEATURE, values=frozenset({Feature.INSIGHT})),
            SurfaceRule(surface=Surface.INSIGHT, field=TagField.SCENE, values=frozenset({"Insight", "SavedInsights"})),
            SurfaceRule(surface=Surface.SQL_EDITOR, field=TagField.PRODUCT, values=frozenset({Product.SQL_EDITOR})),
            SurfaceRule(surface=Surface.SQL_EDITOR, field=TagField.SCENE, values=frozenset({"SQLEditor"})),
            SurfaceRule(surface=Surface.NOTEBOOK, field=TagField.PRODUCT, values=frozenset({Product.NOTEBOOKS})),
            SurfaceRule(surface=Surface.NOTEBOOK, field=TagField.SCENE, values=frozenset({"Notebook"})),
            SurfaceRule(
                surface=Surface.API,
                field=TagField.ACCESS_METHOD,
                values=frozenset(
                    {AccessMethod.PERSONAL_API_KEY, AccessMethod.OAUTH, AccessMethod.PROJECT_SECRET_API_KEY}
                ),
            ),
            SurfaceRule(surface=Surface.APP, field=TagField.SCENE, values=None),
        )
    ),
    subjects=SubjectRules(
        excluded_view_origins=frozenset(
            {DataWarehouseSavedQueryOrigin.ENDPOINT, DataWarehouseSavedQueryOrigin.MANAGED_VIEWSET}
        )
    ),
    eligibility=EligibilityRules(min_view_reads=50),
    certify=CertifyRules(
        top_share=0.10, min_users=5, min_users_floor=2, min_user_share=0.5, min_days=20, min_surfaces=2
    ),
    deprecate=DeprecateRules(
        min_days_with_data=30, seconds_floor=600.0, bytes_floor=float(TERABYTE), counts_background_reads=True
    ),
    materialize=MaterializeRules(
        min_days=10,
        min_requests=50,
        min_users_or_surfaces=2,
        min_alone_reads=3,
        min_seconds_saved=600.0,
        min_bytes_saved=float(TERABYTE),
        min_saved_share=0.5,
        require_incremental_eligibility=True,
    ),
    refresh=RefreshRules(max_interval=timedelta(hours=24), min_read_day_share_below_max_interval=0.5),
    lifecycle=LifecycleRules(
        reproposal_score_multiple=3.0,
        expire_after_days=7,
        max_surfaced_per_day=5,
        max_open=15,
        max_open_per_kind=3,
        first_week_runs=2,
        kind_order=(
            WarehouseSuggestionKind.MATERIALIZE,
            WarehouseSuggestionKind.DEPRECATE,
            WarehouseSuggestionKind.CERTIFY,
        ),
        first_week_kind_order=(
            WarehouseSuggestionKind.CERTIFY,
            WarehouseSuggestionKind.DEPRECATE,
            WarehouseSuggestionKind.MATERIALIZE,
        ),
    ),
)


def kind_position(kind_order: Sequence[str], kind: str) -> int:
    return kind_order.index(kind) if kind in kind_order else len(kind_order)


def rules_version(rules: Rules) -> str:
    serialized = json.dumps(asdict(rules), sort_keys=True, default=_json_value)
    return hashlib.sha256(serialized.encode()).hexdigest()[:RULES_VERSION_LENGTH]


def _json_value(value: Any) -> Any:
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    raise TypeError(f"Cannot serialize {type(value).__name__} in rules")
