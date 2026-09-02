"""
Capability surface for managed_warehouse.

Provisioning state, per-team backfill state, schema naming, Duckgres session setup,
and direct-connection lifecycle commands cross this boundary as contracts or narrow
commands. Django models remain implementation details of the product.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from products.managed_warehouse.backend import common, storage
from products.managed_warehouse.backend.common import (
    DUCKGRES_BUCKET_REGION,
    EARLIEST_BACKFILL_DATE,
    NO_HISTORY_SENTINEL,
)
from products.managed_warehouse.backend.facade.contracts import (
    DuckgresQueryServerConfig,
    DuckgresStoredBucketConfig,
    DuckgresStoredServerConfig,
    DuckLakeCatalogConnectionConfig,
    ManagedWarehouseBackfillState,
    ManagedWarehouseProvisionStatus,
)

if TYPE_CHECKING:
    import psycopg

    from products.managed_warehouse.backend.models import DuckgresServer
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

__all__ = [
    "DUCKGRES_BUCKET_REGION",
    "EARLIEST_BACKFILL_DATE",
    "NO_HISTORY_SENTINEL",
    "default_bucket_region",
    "deprovision_for_org_deletion",
    "duckgres_data_imports_schema",
    "duckgres_data_imports_table_name",
    "duckgres_data_modeling_schema",
    "get_catalog_connection_config",
    "get_control_plane_bucket",
    "get_duckgres_query_server_config",
    "get_org_id_for_team",
    "get_team_deletion_block_reason",
    "get_stored_bucket_config",
    "get_stored_warehouse_config",
    "get_team_backfill_state",
    "get_warehouse_provision_status",
    "has_provisioned_warehouse",
    "is_dev_mode",
    "organization_is_pending_deletion",
    "persist_duckgres_server_for_org",
    "reconcile_stored_bucket_config",
    "resolve_team_earliest_event_date",
    "setup_duckgres_session",
    "update_team_earliest_event_date",
    "validate_schema_name",
]


def _to_stored_server_config(server: DuckgresServer) -> DuckgresStoredServerConfig:
    catalog = None
    if server.catalog_host:
        catalog = DuckLakeCatalogConnectionConfig(
            host=server.catalog_host,
            port=server.catalog_port,
            database=server.catalog_database,
            username=server.catalog_username,
            password=server.catalog_password,
        )
    bucket = None
    if server.bucket:
        bucket = DuckgresStoredBucketConfig(bucket=server.bucket, region=server.bucket_region)
    return DuckgresStoredServerConfig(
        organization_id=server.organization_id,
        query_server=DuckgresQueryServerConfig(
            host=server.host,
            port=server.port,
            flight_port=server.flight_port,
            database=server.database,
            username=server.username,
            password=server.password,
        ),
        catalog=catalog,
        bucket=bucket,
    )


def is_dev_mode() -> bool:
    """Whether Duckgres runs in the env-var-configured local mode."""
    return common.is_dev_mode()


def default_bucket_region() -> str:
    return common.default_bucket_region()


def get_org_id_for_team(team_id: int) -> str:
    return common._get_org_id_for_team(team_id)


def organization_is_pending_deletion(organization_id: str | UUID) -> bool:
    from posthog.models.organization import Organization  # noqa: PLC0415

    return Organization.objects.filter(id=organization_id, is_pending_deletion=True).exists()


def get_stored_warehouse_config(organization_id: str) -> DuckgresStoredServerConfig | None:
    server = common.get_duckgres_server_for_organization(organization_id)
    return _to_stored_server_config(server) if server is not None else None


def get_warehouse_provision_status(organization_id: str) -> ManagedWarehouseProvisionStatus:
    return ManagedWarehouseProvisionStatus(provisioned=has_provisioned_warehouse(organization_id))


def has_provisioned_warehouse(organization_id: str | UUID) -> bool:
    from products.managed_warehouse.backend.models import DuckgresServer  # noqa: PLC0415

    return DuckgresServer.objects.filter(organization_id=organization_id).exists()


def get_duckgres_query_server_config(organization_id: str) -> DuckgresQueryServerConfig:
    config = common.get_duckgres_config_for_org(organization_id)
    return DuckgresQueryServerConfig(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        flight_port=int(config["DUCKGRES_FLIGHT_PORT"]),
        database=config["DUCKGRES_DATABASE"],
        username=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
    )


def get_catalog_connection_config(organization_id: str) -> DuckLakeCatalogConnectionConfig | None:
    stored = get_stored_warehouse_config(organization_id)
    return stored.catalog if stored is not None else None


def get_stored_bucket_config(organization_id: str) -> DuckgresStoredBucketConfig | None:
    stored = get_stored_warehouse_config(organization_id)
    return stored.bucket if stored is not None else None


def persist_duckgres_server_for_org(
    organization_id: str | UUID,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    bucket: str | None = None,
    bucket_region: str | None = None,
) -> DuckgresStoredServerConfig:
    return _to_stored_server_config(
        common.upsert_duckgres_server_for_org(
            organization_id,
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            bucket=bucket,
            bucket_region=bucket_region,
        )
    )


def reconcile_stored_bucket_config(organization_id: str | UUID, *, bucket: str, bucket_region: str) -> bool:
    from products.managed_warehouse.backend.models import DuckgresServer  # noqa: PLC0415

    return bool(
        DuckgresServer.objects.filter(organization_id=organization_id)
        .exclude(bucket=bucket, bucket_region=bucket_region)
        .update(bucket=bucket, bucket_region=bucket_region)
    )


def get_control_plane_bucket(organization_id: str | UUID) -> str | None:
    from products.managed_warehouse.backend.presentation.views import cp_bucket_for  # noqa: PLC0415

    return cp_bucket_for(organization_id)


def update_team_earliest_event_date(
    organization_id: str | UUID, team_id: int, earliest_event_date: date | None
) -> bool:
    from products.managed_warehouse.backend.presentation.views import push_team_earliest_event_date  # noqa: PLC0415

    return push_team_earliest_event_date(organization_id, team_id, earliest_event_date)


def get_team_deletion_block_reason(team_id: int, organization_id: str | UUID) -> str | None:
    from products.managed_warehouse.backend.presentation.views import block_team_deletion  # noqa: PLC0415

    return block_team_deletion(team_id, organization_id)


def deprovision_for_org_deletion(organization_id: str | UUID) -> None:
    from products.managed_warehouse.backend.presentation.views import (  # noqa: PLC0415
        deprovision_for_org_deletion as deprovision,
    )

    deprovision(organization_id)


def duckgres_data_imports_schema(team_id: int) -> str:
    return common.duckgres_data_imports_schema(team_id)


def duckgres_data_imports_table_name(schema: ExternalDataSchema) -> str:
    return common.duckgres_data_imports_table_name(schema)


def duckgres_data_modeling_schema(team_id: int) -> str:
    return common.duckgres_data_modeling_schema(team_id)


def validate_schema_name(name: str | None) -> str | None:
    return common.validate_schema_name(name)


def get_team_backfill_state(team_id: int) -> ManagedWarehouseBackfillState:
    return common.get_team_backfill_state(team_id)


def resolve_team_earliest_event_date(team_id: int) -> date:
    return common.resolve_team_earliest_event_date(team_id)


def setup_duckgres_session(
    conn: psycopg.Connection,
    extensions: tuple[str, ...] = ("ducklake", "httpfs", "delta"),
) -> None:
    storage.setup_duckgres_session(conn, extensions)


# --- billing usage reads (the duckgres usage mirror) ---------------------------
# The daily usage report reads the mirror the duckgres poller maintains
# (backend/temporal/duckgres_usage/). Plain aggregated rows cross the boundary,
# never the model classes.

ENDPOINTS_QUERY_SOURCE = "endpoints"


class DuckgresUsageMirrorStale(RuntimeError):
    pass


def _require_duckgres_usage_fresh_through(end: date) -> None:
    """Block a completed-day report until a fully trusted pull covers it."""
    from products.managed_warehouse.backend.models import DuckgresUsageCursor  # noqa: PLC0415
    from products.managed_warehouse.backend.temporal.duckgres_usage.client import is_configured  # noqa: PLC0415

    if end >= datetime.now(UTC).date():
        return

    required = datetime.combine(end, time.max, tzinfo=UTC)
    cursor = DuckgresUsageCursor.objects.values_list("last_complete_watermark").first()
    if cursor is None and not is_configured():
        return
    complete = cursor[0] if cursor is not None else None
    if complete is None or complete < required:
        raise DuckgresUsageMirrorStale(
            f"duckgres usage mirror is complete through {complete!s}, but report requires {required.isoformat()}"
        )


def _fold_rows_onto_report_teams(rows: list[dict]) -> list[dict]:
    """Resolve teams deleted after persistence without changing the mirror."""
    from posthog.models import Team  # noqa: PLC0415
    from posthog.tasks.usage_report import billable_teams_queryset  # noqa: PLC0415

    team_ids = {row["team_id"] for row in rows}
    live_team_orgs = {
        team_id: str(org_id)
        for team_id, org_id in Team.objects.filter(id__in=team_ids).values_list("id", "organization_id")
    }
    affected_org_ids = {str(row["organization_id"]) for row in rows if row["team_id"] not in live_team_orgs}
    replacements: dict[str, int] = {}
    for org_id, team_id in (
        billable_teams_queryset()
        .filter(organization_id__in=affected_org_ids)
        .order_by("organization_id", "id")
        .values_list("organization_id", "id")
    ):
        replacements.setdefault(str(org_id), team_id)

    totals: defaultdict[int, int] = defaultdict(int)
    unresolved: list[dict] = []
    for row in rows:
        org_id = str(row["organization_id"])
        team_id = row["team_id"]
        live_org_id = live_team_orgs.get(team_id)
        if live_org_id is not None:
            report_team_id = team_id if live_org_id == org_id else None
        else:
            report_team_id = replacements.get(org_id)
        if report_team_id is None:
            unresolved.append(row)
            continue
        totals[report_team_id] += row["total"]

    if unresolved:
        logger.warning(
            "duckgres_usage_report_rows_unattributed",
            row_count=len(unresolved),
            organization_ids=sorted({str(row["organization_id"]) for row in unresolved}),
            team_ids=sorted({row["team_id"] for row in unresolved}),
        )
    return [{"team_id": team_id, "total": total} for team_id, total in totals.items()]


def duckgres_compute_rows_for_period(begin: date, end: date, *, endpoints: bool) -> list[dict]:
    """Duckgres compute usage folded to the billable scalar, per team.

    The billable unit is cpu_seconds + memory_seconds / 8 (the RFC's 1:8 rate
    ratio: $0.025/GiB-hr = $0.20/8), floored so fractions under-charge. Endpoint
    queries (query_source="endpoints") are a separate product.
    """
    from django.db.models import Sum  # noqa: PLC0415

    from products.managed_warehouse.backend.models import DuckgresDailyUsage  # noqa: PLC0415

    _require_duckgres_usage_fresh_through(end)
    queryset = DuckgresDailyUsage.objects.filter(date__gte=begin, date__lte=end)
    if endpoints:
        queryset = queryset.filter(query_source=ENDPOINTS_QUERY_SOURCE)
    else:
        queryset = queryset.exclude(query_source=ENDPOINTS_QUERY_SOURCE)
    rows = [
        {
            "organization_id": row["organization_id"],
            "team_id": row["team_id"],
            "total": (row["total_cpu_seconds"] * 8 + row["total_memory_seconds"]) // 8,
        }
        for row in queryset.values("organization_id", "team_id").annotate(
            total_cpu_seconds=Sum("cpu_seconds"), total_memory_seconds=Sum("memory_seconds")
        )
    ]
    return _fold_rows_onto_report_teams(rows)


def duckgres_storage_gb_hour_rows_for_period(begin: date, end: date) -> list[dict]:
    """Duckgres storage usage folded to billable decimal-GB hours, per team.

    The unit conversion is the whole point of this function, and it mixes binary
    and decimal on purpose:

    - duckgres meters in **GiB-seconds** (GiB = 2^30 bytes — a binary unit),
      served as an exact decimal (integer byte-seconds / 2^30, up to 30
      fractional digits).
    - billing PRICES storage in **decimal GB** (GB = 10^9 bytes; $/GB-month,
      100 GB free tier). Snowflake/BigQuery/etc. all price decimal GB, and our
      calculator + free tier are decimal.

    So the GiB->GB conversion is pinned here and only here. Getting the binary
    vs decimal base wrong is a silent ~7.4% billing error, so keep it explicit.
    """
    from fractions import Fraction  # noqa: PLC0415

    from django.db.models import Sum  # noqa: PLC0415

    from products.managed_warehouse.backend.models import DuckgresDailyStorageUsage  # noqa: PLC0415

    _require_duckgres_usage_fresh_through(end)
    out = []
    for row in (
        DuckgresDailyStorageUsage.objects.filter(date__gte=begin, date__lte=end)
        .values("organization_id", "team_id")
        .annotate(total_gib_seconds=Sum("gib_seconds"))
    ):
        # GiB-seconds -> billable decimal-GB-hours, in three exact steps:
        #
        #   1. GiB-seconds  x 2^30   ->  byte-seconds   recover duckgres's integer byte-seconds.
        #                                               Fraction (not Decimal) so it's exact: Decimal's
        #                                               28-digit context would round the 30-digit tail.
        #   2. byte-seconds / 10^9   ->  GB-seconds     10^9 bytes = 1 *decimal* GB, the priced unit.
        #   3. GB-seconds   / 3600   ->  GB-hours       3600 s = 1 hour.
        #
        # Steps 2 and 3 are a single floor-division by (10^9 * 3600) so any fraction
        # under-charges. Worked example (the closed-day case in the tests):
        #   360000 GiB-s  x 2^30            = 386_547_056_640_000 byte-s
        #                 // (10^9 * 3600)  = 107.37...  ->  107 GB-hours
        byte_seconds = int(Fraction(row["total_gib_seconds"]) * (2**30))
        gb_hours = byte_seconds // (10**9 * 3600)
        out.append({"organization_id": row["organization_id"], "team_id": row["team_id"], "total": gb_hours})
    return _fold_rows_onto_report_teams(out)
