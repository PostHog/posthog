from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import structlog

from posthog.schema import NativeMarketingSource

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.hogql_queries.constants import (
    MARKETING_ANALYTICS_SCHEMA,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
)
from products.marketing_analytics.backend.services.native_integrations import (
    DISPLAY_NAMES,
    EXTERNAL_SOURCE_TYPE_TO_NATIVE,
)
from products.warehouse_sources.backend.facade import (
    api as warehouse_api,
    contracts as warehouse_contracts,
)

logger = structlog.get_logger(__name__)

SyncStatus = Literal[
    "ok",
    "stale",
    "error",
    "never",
    "not_connected",
    "tables_failed",  # at least one required table has status=Failed
    "tables_disabled",  # at least one required table has should_sync=False
    "tables_missing",  # at least one required table is not present at all
]
OverallStatus = Literal["healthy", "degraded", "broken", "no_sources"]

# A connection is "stale" if its last completed sync is older than this.
STALE_THRESHOLD = timedelta(hours=24)

_REQUIRED_SCHEMA_COLUMNS: list[str] = [
    col.value for col, cfg in MARKETING_ANALYTICS_SCHEMA.items() if cfg.get("required")
]

# Hash anchor (#marketing-settings), not a path slash — the slash form 404s.
_MARKETING_SETTINGS_URL = "/settings/environment-marketing-analytics#marketing-settings"
_MARKETING_PAGE_URL = "/marketing"


def _source_schemas_url(source_id: str | None) -> str | None:
    """URL to the per-source Schemas tab (enable/disable tables, retry syncs, reconnect).
    Frontend prefixes the source UUID with `managed-` to disambiguate managed sources."""
    if not source_id:
        return None
    return f"/data-management/sources/managed-{source_id}/schemas"


@dataclass
class RequiredTableStatus:
    table_name: str
    present: bool
    should_sync: bool
    status: str | None  # ExternalDataSchema.Status value (Completed/Running/Failed/Paused/Cancelled) or None
    last_synced_at: datetime | None


@dataclass
class DataSourceHealthEntry:
    source_type: str
    is_native: bool
    display_name: str
    connected: bool
    last_sync_at: datetime | None
    last_sync_status: SyncStatus
    last_error: str | None
    rows_last_24h: int
    rows_last_7d: int
    sources_map_present: bool
    schema_columns_mapped: list[str]
    schema_columns_required_missing: list[str]
    required_tables: list[RequiredTableStatus]
    # Marketing analytics global settings (mappings, goals, attribution).
    settings_url: str
    # Per-source Schemas tab — used for table-level fixes (enable/disable required
    # tables, retry failed syncs, reconnect auth). `None` if the source isn't
    # connected (no UUID to link to).
    schemas_url: str | None
    diagnosis: str
    fix_suggestion: str | None


@dataclass
class DataSourceHealthResponse:
    integrations: list[DataSourceHealthEntry] = field(default_factory=list)
    has_any_data: bool = False
    overall_status: OverallStatus = "no_sources"
    issues_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


async def get_data_source_health(
    team: Team,
    *,
    source_type: str | None = None,
    sources_map: dict[str, dict] | None = None,
) -> DataSourceHealthResponse:
    """Check the platform → DW side of marketing integrations: connection state,
    sync recency, row counts, and schema-mapping coverage for every native source.

    This service does NOT look at PostHog events / UTM attribution — that is
    `attribution_health`. Cross-domain correlation (e.g. "syncing fine but no UTM
    events arrive") lives in the `marketing_diagnostic` aggregator.

    Native (Google Ads, Meta Ads, Bing Ads, LinkedIn Ads, Reddit Ads, Pinterest Ads,
    Snapchat Ads, TikTok Ads) is the v1 scope. BigQuery / self-managed sources will
    be added in a follow-up.

    `sources_map` lets the diagnostic aggregator pass an already-loaded
    `marketing_analytics_config.sources_map` instead of triggering another
    Postgres roundtrip. None → service loads it itself.
    """
    targets = EXTERNAL_SOURCE_TYPE_TO_NATIVE
    if source_type is not None:
        targets = {k: v for k, v in targets.items() if k == source_type}

    config_sources_map = sources_map if sources_map is not None else await _get_sources_map(team)
    health_by_type = await _get_health_by_type(team, targets)

    entries: list[DataSourceHealthEntry] = []
    for type_key, native in targets.items():
        entries.append(
            _build_entry(
                source_type=type_key,
                native=native,
                health=health_by_type.get(type_key),
                config_sources_map=config_sources_map,
            )
        )

    has_any_data = any(e.rows_last_7d > 0 for e in entries)
    overall_status = _compute_overall_status(entries)
    issues_summary = _build_issues_summary(entries)

    return DataSourceHealthResponse(
        integrations=entries,
        has_any_data=has_any_data,
        overall_status=overall_status,
        issues_summary=issues_summary,
    )


@database_sync_to_async
def _get_sources_map(team: Team) -> dict[str, dict]:
    config = getattr(team, "marketing_analytics_config", None)
    return config.sources_map if config is not None else {}


@database_sync_to_async
def _get_health_by_type(
    team: Team, targets: dict[str, NativeMarketingSource]
) -> dict[str, warehouse_contracts.SourceHealth]:
    """Health for the newest source of each native type (more than one of the same
    type is uncommon in practice). Sync status, last error, row counts, and required-
    table states all come from the warehouse facade in one set-based call."""
    required_by_type = {
        type_key: list(NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS.get(native, []))
        for type_key, native in targets.items()
    }
    healths = warehouse_api.list_source_health(
        team.pk,
        source_types=list(targets.keys()),
        stale_threshold=STALE_THRESHOLD,
        required_schema_names_by_type=required_by_type,
    )
    by_type: dict[str, warehouse_contracts.SourceHealth] = {}
    for health in healths:  # ordered (source_type, -created_at) → first seen per type is newest
        by_type.setdefault(health.source_type, health)
    return by_type


def _build_entry(
    *,
    source_type: str,
    native: NativeMarketingSource,
    health: warehouse_contracts.SourceHealth | None,
    config_sources_map: dict[str, dict],
) -> DataSourceHealthEntry:
    display_name = DISPLAY_NAMES[native]

    if health is None:
        return DataSourceHealthEntry(
            source_type=source_type,
            is_native=True,
            display_name=display_name,
            connected=False,
            last_sync_at=None,
            last_sync_status="not_connected",
            last_error=None,
            rows_last_24h=0,
            rows_last_7d=0,
            sources_map_present=False,
            schema_columns_mapped=[],
            # Native sources don't require column mapping — that's only for
            # self-managed (BigQuery, S3, etc.) sources where the user provides
            # custom tables. The mapped/missing columns concept doesn't apply
            # to native integrations at all.
            schema_columns_required_missing=[],
            required_tables=[
                RequiredTableStatus(table_name=name, present=False, should_sync=False, status=None, last_synced_at=None)
                for name in NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS.get(native, [])
            ],
            settings_url=_MARKETING_SETTINGS_URL,
            schemas_url=None,
            diagnosis=f"{display_name} is not connected.",
            fix_suggestion=f"Connect {display_name} from {_MARKETING_SETTINGS_URL}.",
        )

    required_tables = [
        RequiredTableStatus(
            table_name=s.schema_name,
            present=s.present,
            should_sync=s.should_sync,
            status=s.status,
            last_synced_at=s.last_synced_at,
        )
        for s in health.schemas
    ]

    source_id_str = str(health.source_id)
    field_mapping = config_sources_map.get(source_id_str, {})
    mapped_keys = list(field_mapping.keys())
    # Native sources don't use sources_map for column mapping. Only non-native
    # (BigQuery, S3, self-managed) sources track per-column mappings here.
    missing_required: list[str] = []

    diagnosis, fix_suggestion = _diagnose(
        display_name=display_name,
        last_sync_status=health.sync_status,
        last_completed_at=health.last_completed_sync_at,
        last_error_text=health.last_unresolved_error,
        sources_map_present=bool(field_mapping),
        missing_required=missing_required,
        rows_last_7d=health.rows_synced_last_7d,
        required_tables=required_tables,
        source_id=source_id_str,
    )

    return DataSourceHealthEntry(
        source_type=source_type,
        is_native=True,
        display_name=display_name,
        connected=True,
        last_sync_at=health.last_completed_sync_at,
        last_sync_status=health.sync_status,
        last_error=health.last_unresolved_error,
        rows_last_24h=health.rows_synced_last_24h,
        rows_last_7d=health.rows_synced_last_7d,
        sources_map_present=bool(field_mapping),
        schema_columns_mapped=mapped_keys,
        schema_columns_required_missing=missing_required,
        required_tables=required_tables,
        settings_url=_MARKETING_SETTINGS_URL,
        schemas_url=_source_schemas_url(source_id_str),
        diagnosis=diagnosis,
        fix_suggestion=fix_suggestion,
    )


def _diagnose(
    *,
    display_name: str,
    last_sync_status: SyncStatus,
    last_completed_at: datetime | None,
    last_error_text: str | None,
    sources_map_present: bool,
    missing_required: list[str],
    rows_last_7d: int,
    required_tables: list[RequiredTableStatus],
    source_id: str | None,
) -> tuple[str, str | None]:
    # Per-source Schemas tab — the place to enable/disable required tables,
    # retry failed syncs, and reconnect. Falls back to the global settings page
    # when we don't have a source UUID (shouldn't happen for connected sources).
    schemas_link = _source_schemas_url(source_id) or _MARKETING_SETTINGS_URL
    if last_sync_status == "tables_missing":
        names = ", ".join(t.table_name for t in required_tables if not t.present)
        return (
            f"{display_name} is missing required tables: {names}.",
            f"Open {schemas_link} and enable those tables for sync.",
        )
    if last_sync_status == "tables_failed":
        names = ", ".join(t.table_name for t in required_tables if t.status == "Failed")
        return (
            f"{display_name} required tables failed to sync: {names}.",
            f"Open {schemas_link}, inspect the failure and retry the sync.",
        )
    if last_sync_status == "tables_disabled":
        names = ", ".join(t.table_name for t in required_tables if t.present and not t.should_sync)
        return (
            f"{display_name} required tables are present but not selected for import: {names}.",
            f"Open {schemas_link} and enable sync for those tables.",
        )
    if last_sync_status == "error":
        return (
            f"{display_name} last sync failed: {(last_error_text or '')[:200]}",
            f"Open {schemas_link} and reconnect or retry the sync.",
        )
    if last_sync_status == "never":
        return (
            f"{display_name} is connected but has never finished a sync.",
            f"Trigger a manual sync at {schemas_link}, or wait for the next scheduled run.",
        )
    if last_sync_status == "stale":
        return (
            f"{display_name} last successful sync is older than 24h.",
            f"Check the schedule at {schemas_link} or trigger a manual run.",
        )
    if missing_required:
        # Only relevant for non-native sources (BigQuery, S3, self-managed).
        return (
            f"{display_name} is syncing but required schema columns are not mapped: {', '.join(missing_required)}.",
            f"Open {_MARKETING_SETTINGS_URL} and map those columns for {display_name}.",
        )
    if rows_last_7d == 0:
        return (
            f"{display_name} is healthy but has not synced any rows in the last 7 days.",
            "Verify that the connected account has active campaigns in the date range.",
        )
    return (f"{display_name} is healthy.", None)


def _compute_overall_status(entries: list[DataSourceHealthEntry]) -> OverallStatus:
    connected = [e for e in entries if e.connected]
    if not connected:
        return "no_sources"
    healthy = [e for e in connected if e.last_sync_status == "ok" and not e.schema_columns_required_missing]
    blocking_states = ("error", "tables_failed", "tables_missing", "tables_disabled")
    blocked = [e for e in connected if e.last_sync_status in blocking_states]
    if blocked and not healthy:
        return "broken"
    if blocked or any(e.schema_columns_required_missing for e in connected):
        return "degraded"
    if all(e.last_sync_status == "ok" for e in connected) and healthy:
        return "healthy"
    return "degraded"


def _build_issues_summary(entries: list[DataSourceHealthEntry]) -> list[str]:
    issues: list[str] = []
    for entry in entries:
        if entry.connected and entry.last_sync_status != "ok":
            issues.append(f"{entry.display_name}: {entry.diagnosis}")
        elif entry.connected and entry.schema_columns_required_missing:
            issues.append(f"{entry.display_name}: {entry.diagnosis}")
    return issues
