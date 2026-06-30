from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from django.db.models import Sum
from django.utils import timezone

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
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource

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
    sources_by_type = await _get_sources_by_type(team, list(targets.keys()))

    entries: list[DataSourceHealthEntry] = []
    for type_key, native in targets.items():
        source = sources_by_type.get(type_key)
        entries.append(
            await _build_entry(
                source_type=type_key,
                native=native,
                source=source,
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
def _get_sources_by_type(team: Team, source_types: list[str]) -> dict[str, ExternalDataSource]:
    """Index live sources by source_type. We pick the most recently created if
    the team has more than one of the same type — this is uncommon in practice."""
    qs = ExternalDataSource.objects.filter(team=team, source_type__in=source_types, deleted=False).order_by(
        "source_type", "-created_at"
    )
    by_type: dict[str, ExternalDataSource] = {}
    for src in qs:
        by_type.setdefault(src.source_type, src)
    return by_type


async def _build_entry(
    *,
    source_type: str,
    native: NativeMarketingSource,
    source: ExternalDataSource | None,
    config_sources_map: dict[str, dict],
) -> DataSourceHealthEntry:
    display_name = DISPLAY_NAMES[native]

    if source is None:
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

    last_completed_at, last_error_text = await _get_last_job_state(source)
    rows_24h, rows_7d = await _get_rows_synced(source)
    required_tables = await _get_required_tables_status(source, native)

    source_id_str = str(source.id)
    field_mapping = config_sources_map.get(source_id_str, {})
    mapped_keys = list(field_mapping.keys())
    # Native sources don't use sources_map for column mapping. Only non-native
    # (BigQuery, S3, self-managed) sources track per-column mappings here.
    missing_required: list[str] = []

    last_sync_status = _resolve_sync_status(
        last_completed_at=last_completed_at,
        last_error_text=last_error_text,
        required_tables=required_tables,
    )

    diagnosis, fix_suggestion = _diagnose(
        display_name=display_name,
        last_sync_status=last_sync_status,
        last_completed_at=last_completed_at,
        last_error_text=last_error_text,
        sources_map_present=bool(field_mapping),
        missing_required=missing_required,
        rows_last_7d=rows_7d,
        required_tables=required_tables,
        source_id=source_id_str,
    )

    return DataSourceHealthEntry(
        source_type=source_type,
        is_native=True,
        display_name=display_name,
        connected=True,
        last_sync_at=last_completed_at,
        last_sync_status=last_sync_status,
        last_error=last_error_text,
        rows_last_24h=rows_24h,
        rows_last_7d=rows_7d,
        sources_map_present=bool(field_mapping),
        schema_columns_mapped=mapped_keys,
        schema_columns_required_missing=missing_required,
        required_tables=required_tables,
        settings_url=_MARKETING_SETTINGS_URL,
        schemas_url=_source_schemas_url(source_id_str),
        diagnosis=diagnosis,
        fix_suggestion=fix_suggestion,
    )


@database_sync_to_async
def _get_required_tables_status(source: ExternalDataSource, native: NativeMarketingSource) -> list[RequiredTableStatus]:
    required_names = NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS.get(native, [])
    if not required_names:
        return []

    schemas_by_name: dict[str, ExternalDataSchema] = {
        s.name: s for s in ExternalDataSchema.objects.filter(source=source, deleted=False)
    }
    out: list[RequiredTableStatus] = []
    for name in required_names:
        schema = schemas_by_name.get(name)
        if schema is None:
            out.append(
                RequiredTableStatus(table_name=name, present=False, should_sync=False, status=None, last_synced_at=None)
            )
        else:
            out.append(
                RequiredTableStatus(
                    table_name=name,
                    present=True,
                    should_sync=schema.should_sync,
                    status=schema.status,
                    last_synced_at=getattr(schema, "last_synced_at", None),
                )
            )
    return out


@database_sync_to_async
def _get_last_job_state(source: ExternalDataSource) -> tuple[datetime | None, str | None]:
    """Return (last_completed_finished_at, last_unresolved_error_text) for a source.

    `last_unresolved_error_text` is the latest FAILED job's error message *only
    if* its created_at is newer than the most recent COMPLETED job — otherwise
    the failure has been resolved by a subsequent successful sync.
    """
    last_completed = (
        ExternalDataJob.objects.filter(pipeline=source, status=ExternalDataJob.Status.COMPLETED)
        .order_by("-finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )
    last_failed = (
        ExternalDataJob.objects.filter(pipeline=source, status=ExternalDataJob.Status.FAILED)
        .exclude(latest_error__isnull=True)
        .order_by("-created_at")
        .values("created_at", "latest_error")
        .first()
    )

    error_text: str | None = None
    if last_failed is not None:
        if last_completed is None or last_failed["created_at"] > last_completed:
            error_text = last_failed["latest_error"]

    return last_completed, error_text


@database_sync_to_async
def _get_rows_synced(source: ExternalDataSource) -> tuple[int, int]:
    now = timezone.now()
    in_24h = (
        ExternalDataJob.objects.filter(
            pipeline=source,
            status=ExternalDataJob.Status.COMPLETED,
            finished_at__gte=now - timedelta(hours=24),
        ).aggregate(total=Sum("rows_synced"))["total"]
        or 0
    )
    in_7d = (
        ExternalDataJob.objects.filter(
            pipeline=source,
            status=ExternalDataJob.Status.COMPLETED,
            finished_at__gte=now - timedelta(days=7),
        ).aggregate(total=Sum("rows_synced"))["total"]
        or 0
    )
    return int(in_24h), int(in_7d)


def _resolve_sync_status(
    *,
    last_completed_at: datetime | None,
    last_error_text: str | None,
    required_tables: list[RequiredTableStatus],
) -> SyncStatus:
    """Resolve the source-level sync status. Per-required-table state takes
    priority over the source-level job state, because the Marketing analytics
    dashboard surfaces those schema-level issues directly to users (banner)."""
    missing = [t for t in required_tables if not t.present]
    if missing:
        return "tables_missing"
    failed = [t for t in required_tables if t.status == "Failed"]
    if failed:
        return "tables_failed"
    disabled = [t for t in required_tables if t.present and not t.should_sync]
    if disabled:
        return "tables_disabled"
    if last_error_text is not None:
        return "error"
    if last_completed_at is None:
        return "never"
    if timezone.now() - last_completed_at > STALE_THRESHOLD:
        return "stale"
    return "ok"


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
