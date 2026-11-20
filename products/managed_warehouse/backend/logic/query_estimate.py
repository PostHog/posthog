from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import ValidationError

from posthog.schema import HogQLQuery

from posthog.hogql.constants import LimitContext
from posthog.hogql.direct_sql.trino_adapter import bounded_trino_cursor, ensure_read_only_raw_trino_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneNotConfiguredError,
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    QueryCostEstimate,
    QueryCostTable,
    QueryCostWarning,
    WarehouseNotFoundError,
)
from products.managed_warehouse.backend.logic.console_pricing import COMPUTE_USD_PER_TIB, GIB, TIB
from products.managed_warehouse.backend.logic.console_queries import get_storage_overview
from products.managed_warehouse.backend.logic.console_usage import get_max_scan_bytes_per_query
from products.managed_warehouse.backend.query_execution import prepare_managed_trino_sql, validate_managed_trino_query
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.warehouse_sources.backend.facade.source_management import trino_error_to_message

if TYPE_CHECKING:
    from posthog.models import Team, User

LOGGER = structlog.get_logger(__name__)
_STORAGE_UNAVAILABLE = (
    ControlPlaneNotConfiguredError,
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    WarehouseNotFoundError,
)
ESTIMATE_TRINO_SOURCE = "posthog-console"
ESTIMATE_TIMEOUT_SECONDS = 15
ESTIMATE_FAILED_MESSAGE = "Couldn't estimate this query."
LARGE_TABLE_BYTES = 10 * GIB


def _read_input_tables(plan: dict[str, Any]) -> list[tuple[str, str, str, bool]]:
    """Read ``(catalog, schema, table, has_filter)`` from the JSON of ``EXPLAIN (TYPE IO, FORMAT JSON)``.

    Trino's ``IoPlan`` lists ``inputTableColumnInfos``. Each entry has ``table`` (``catalog`` and
    ``schemaTable.schema``/``schemaTable.table``) and a ``constraint``. The constraint has ``none`` (true when no
    row can match) and ``columnConstraints`` (one entry per constrained column).
    """
    tables: dict[tuple[str, str, str], bool] = {}
    for info in plan.get("inputTableColumnInfos", []):
        table = info["table"]
        key = (str(table["catalog"]), str(table["schemaTable"]["schema"]), str(table["schemaTable"]["table"]))
        constraint = info.get("constraint") or {}
        has_filter = bool(constraint.get("none")) or bool(constraint.get("columnConstraints"))
        tables[key] = tables.get(key, True) and has_filter
    return [(*key, has_filter) for key, has_filter in tables.items()]


def _explain_io(team: Team, user: User, sql: str, values: dict[str, Any] | None) -> dict[str, Any]:
    statement, parameters = convert_pyformat_placeholders(sql, values) if values is not None else (sql, [])
    explain = f"EXPLAIN (TYPE IO, FORMAT JSON) {statement}"
    try:
        with connect_managed_warehouse_trino(
            str(team.organization_id),
            principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}",
            source=ESTIMATE_TRINO_SOURCE,
        ) as connection:
            with bounded_trino_cursor(connection, ESTIMATE_TIMEOUT_SECONDS, team_id=team.pk) as (cursor, watchdog):
                try:
                    cursor.execute(explain, parameters) if parameters else cursor.execute(explain)
                    rows = cursor.fetchall()
                except Exception:
                    watchdog.check()
                    raise
                watchdog.check()
    except ExposedHogQLError:
        raise
    except Exception as error:
        # Connection errors keep their own type, so the caller can tell "not ready" from "bad query".
        if type(error).__module__.startswith("products.managed_warehouse"):
            raise
        raise ExposedHogQLError(trino_error_to_message(error)) from error
    try:
        plan = json.loads(rows[0][0])
        _read_input_tables(plan)
    except (IndexError, KeyError, ValueError, TypeError, AttributeError) as error:
        raise ExposedHogQLError(ESTIMATE_FAILED_MESSAGE) from error
    return plan


def _table_sizes(organization_id: str) -> dict[tuple[str, str], int]:
    try:
        return {(t.schema, t.table): t.data_bytes for t in get_storage_overview(organization_id).tables}
    except _STORAGE_UNAVAILABLE as error:
        # The plan is still useful without sizes, so the estimate reports the tables with unknown sizes.
        LOGGER.warning("managed_warehouse_estimate_storage_unavailable", error_type=type(error).__name__)
        return {}


def estimate_managed_trino_query(
    team: Team,
    user: User,
    *,
    query: str,
    send_raw_query: bool,
    variables: Mapping[str, Any] | None = None,
    filters: Mapping[str, Any] | None = None,
) -> QueryCostEstimate:
    try:
        hogql_query = HogQLQuery.model_validate(
            {
                "query": query,
                "executionTarget": "managed_trino",
                "sendRawQuery": send_raw_query,
                "variables": variables,
                "filters": filters,
            }
        )
    except ValidationError as error:
        raise ExposedHogQLError("The variables or filters of this query are not valid.") from error
    validate_managed_trino_query(hogql_query, team, user)
    prepared = prepare_managed_trino_sql(
        hogql_query,
        team=team,
        user=user,
        user_access_control=UserAccessControl(user=user, team=team),
        limit_context=LimitContext.QUERY,
    )
    sql = ensure_read_only_raw_trino_statement(prepared.sql)
    input_tables = _read_input_tables(_explain_io(team, user, sql, prepared.values))

    organization_id = str(team.organization_id)
    sizes = _table_sizes(organization_id)
    tables = tuple(
        QueryCostTable(
            catalog=catalog,
            schema=schema,
            table=table,
            size_bytes=sizes.get((schema, table)),
            has_filter=has_filter,
        )
        for catalog, schema, table, has_filter in input_tables
    )
    complete = all(t.size_bytes is not None for t in tables)
    # With no sized table at all, a zero would read as "free", so the bound stays unknown.
    sized = [t.size_bytes for t in tables if t.size_bytes is not None]
    upper_bound = sum(sized) if sized or complete else None
    cap = get_max_scan_bytes_per_query(organization_id)
    exceeds_cap = cap is not None and upper_bound is not None and upper_bound > cap
    warnings: list[QueryCostWarning] = []
    if any(not t.has_filter and (t.size_bytes or 0) >= LARGE_TABLE_BYTES for t in tables):
        warnings.append("no_filter_on_large_table")
    if exceeds_cap:
        warnings.append("exceeds_cap")
    if not complete:
        warnings.append("size_unknown")
    return QueryCostEstimate(
        tables=tables,
        upper_bound_bytes=upper_bound,
        estimated_cost_usd=(None if upper_bound is None else Decimal(upper_bound) / Decimal(TIB) * COMPUTE_USD_PER_TIB),
        cap_bytes=cap,
        exceeds_cap=exceeds_cap,
        complete=complete,
        warnings=tuple(warnings),
    )
