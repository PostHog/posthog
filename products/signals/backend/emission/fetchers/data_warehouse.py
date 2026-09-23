from datetime import datetime
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.contracts import scope_ids_problem
from products.signals.backend.emission.registry import SignalSourceTableConfig

logger = structlog.get_logger(__name__)


def escape_table_name(table_name: str) -> str:
    """Quote each segment of a warehouse table name for use in a HogQL FROM clause.

    Some sources put customer text in the table key. A GitHub source keys its table on the
    repository name, so a hyphen or another character that is not valid in a bare identifier
    reaches HogQL and breaks the parse. The HogQL database registers the table under the same
    dot-split chain, so keep the dots and escape only the segments between them.
    """
    return ".".join(escape_hogql_identifier(part) for part in table_name.split("."))


def scope_ids_from_source_config(config: SignalSourceTableConfig, source_config: Any) -> list[str]:
    """The source's allowlist, stripped, or an empty list. A malformed value in the API-writable
    config blob is ignored as a whole: emission reads everything rather than applying part of a
    list or breaking."""
    if config.scope_config_key is None or not isinstance(source_config, dict):
        return []
    raw = source_config.get(config.scope_config_key)
    if raw is None:
        return []
    problem = scope_ids_problem(raw)
    if problem is not None:
        logger.warning(
            "Ignoring malformed scope allowlist in source config",
            scope_config_key=config.scope_config_key,
            problem=problem,
            source_product=config.source_product,
            source_type=config.source_type,
            signals_type="data-import-signals",
        )
        return []
    # Exact `IN` match: a stray space would match no record.
    return [scope_id.strip() for scope_id in raw]


def data_warehouse_record_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch records from a data warehouse table via HogQL."""
    table_name: str = context["table_name"]
    last_synced_at: str | None = context.get("last_synced_at")
    extra: dict[str, Any] = context.get("extra", {})
    scope_ids = scope_ids_from_source_config(config, context.get("source_config"))
    where_parts: list[str] = []
    placeholders: dict[str, Any] = {}
    partition_expr = (
        f"parseDateTimeBestEffort({config.partition_field})"
        if config.partition_field_is_datetime_string
        else config.partition_field
    )
    # Continuous sync — filter records since last sync
    if last_synced_at is not None:
        where_parts.append(f"{partition_expr} > {{last_synced_at}}")
        placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(last_synced_at))
    # First ever sync — look back a limited window
    else:
        where_parts.append(f"{partition_expr} > now() - interval {config.first_sync_lookback_days} day")
    if config.where_clause:
        where_parts.append(config.where_clause)
    # Filtered in the query rather than in Python so the LIMIT below counts only allowlisted records.
    if scope_ids:
        where_parts.append(f"{config.scope_field} IN {{scope_ids}}")
        placeholders["scope_ids"] = ast.Tuple(exprs=[ast.Constant(value=scope_id) for scope_id in scope_ids])
    where_sql = " AND ".join(where_parts)
    fields_sql = ", ".join(config.fields)
    # Limiting can cause a data loss, as the missed records won't be picked in the next sync, but it's acceptable for the current use case
    query = f"""
        SELECT {fields_sql}
        FROM {escape_table_name(table_name)}
        WHERE {where_sql}
        LIMIT {config.max_records}
    """
    logger.info(
        "Querying new records for signal emission",
        sync_type="continuous" if last_synced_at is not None else "first",
        last_synced_at=last_synced_at,
        lookback_days=config.first_sync_lookback_days if last_synced_at is None else None,
        table_name=table_name,
        where_clause=where_sql,
        scope_ids_count=len(scope_ids),
        max_records=config.max_records,
        signals_type="data-import-signals",
        **extra,
    )
    try:
        # Parsing is inside the try so a query we cannot even parse is logged and re-raised like a
        # query that fails at execution, instead of dying before the first log line.
        parsed = parse_select(query, placeholders=placeholders) if placeholders else parse_select(query)
        # Internal data-import signal fetcher (no user); bypass warehouse HogQL access control so it
        # can read the source warehouse table.
        result = execute_hogql_query(
            query=parsed, team=team, query_type="EmitSignalsNewRecords", bypass_warehouse_access_control=True
        )
    except Exception as e:
        logger.exception(f"Error querying new records: {e}", **extra)
        # Raising to avoid creating permanent gaps in emitted signals, in hope the activity will fix itself on the restart
        raise
    if not result.results or not result.columns:
        return []
    return [dict(zip(result.columns, row)) for row in result.results]
