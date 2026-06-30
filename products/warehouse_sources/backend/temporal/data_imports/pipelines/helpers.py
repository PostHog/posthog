from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db.models import F

from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import run_revenue_view_sync
from products.warehouse_sources.backend.types import IncrementalFieldType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

initial_datetime = datetime(1970, 1, 1, 0, 0, 0, 0, tzinfo=ZoneInfo("UTC"))


@database_sync_to_async_pool
def aget_external_data_job(team_id, job_id):
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    return ExternalDataJob.objects.get(id=job_id, team_id=team_id)


@database_sync_to_async_pool
def aupdate_job_count(job_id: str, team_id: int, count: int):
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)


def incremental_type_to_initial_value(field_type: IncrementalFieldType) -> int | datetime | date | str:
    if (
        field_type == IncrementalFieldType.Integer
        or field_type == IncrementalFieldType.Numeric
        or field_type == IncrementalFieldType.XID
    ):
        return 0
    if field_type == IncrementalFieldType.DateTime or field_type == IncrementalFieldType.Timestamp:
        return initial_datetime
    if field_type == IncrementalFieldType.Date:
        return date(1970, 1, 1)
    if field_type == IncrementalFieldType.ObjectID:
        return "000000000000000000000000"

    raise ValueError(f"Unsupported incremental field type: {field_type}")


def incremental_type_to_operator(field_type: IncrementalFieldType) -> str:
    # Date cursors lose all rows that land on the boundary day after the previous sync's
    # cursor advance, because the cursor only carries day-granularity and `>` skips
    # everything equal to that day. `>=` re-fetches the boundary day so primary-key dedup
    # (or append acceptance) can close the gap. Every other field type carries enough
    # resolution that `>` is safe and avoids re-shipping the boundary row on every sync.
    # xmin's lower bound (the previous run's ceiling) is inclusive, so it also uses `>=`.
    if field_type == IncrementalFieldType.Date or field_type == IncrementalFieldType.XID:
        return ">="
    return ">"


def build_table_name(source: ExternalDataSource, schema_name: str):
    # Dots in `schema_name` would parse as `<table>.<column>` in HogQL, so any source that ever
    # produces a dotted schema name (today: Postgres multi-schema like `public.auth_group`) needs
    # them rewritten. No-op for pre-existing single-schema sources whose names never contained dots.
    safe_schema_name = schema_name.replace(".", "__")
    return f"{source.prefix or ''}{source.source_type}_{safe_schema_name}".lower()


def resolve_table_and_folder_names(schema_name: str, resolved_s3_folder_name: str | None) -> tuple[str, str]:
    """Return `(table_storage_name, folder_name)` for a schema row.

    These are intentionally different normalizations:
    - The S3 folder is the *snake_cased* identifier (`BalanceTransaction` -> `balance_transaction`).
    - `build_table_name` only lower-cases, so the HogQL table name must derive from the *raw* schema
      name (`BalanceTransaction` -> `stripe_balancetransaction`). Feeding it the folder would rename
      existing tables, e.g. `stripe_balancetransaction` -> `stripe_balance_transaction`.

    The exception is a row renamed during multi-schema migration: its folder is pinned to the
    original path, which differs from the row's own normalized name, so the table stays anchored
    there (e.g. `public.users` with folder `users` keeps `<prefix>_users`).
    """
    from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

    folder_name = NamingConvention.normalize_identifier(resolved_s3_folder_name or schema_name)
    is_folder_pinned = folder_name != NamingConvention.normalize_identifier(schema_name)
    table_storage_name = folder_name if is_folder_pinned else schema_name
    return table_storage_name, folder_name


def sync_revenue_analytics_views(schema: ExternalDataSchema, source: ExternalDataSource) -> None:
    """Re-sync revenue analytics materialized views after a data load completes.

    Called after validate_schema_and_update_table links a DataWarehouseTable to the
    schema. The sync is owned by the revenue_analytics product, which registers it via
    external_product_hooks (it depends on warehouse_sources, so we must not import it
    here). No-ops if revenue_analytics hasn't registered.
    """
    run_revenue_view_sync(schema, source)
