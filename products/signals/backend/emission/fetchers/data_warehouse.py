from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Team

from products.signals.backend.contracts import HOGQL_FILTER_KEY, scope_ids_problem
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.source_filters import SavedSourceFilter, saved_filter_predicate

logger = structlog.get_logger(__name__)

FILTER_SOURCE_ALIAS = "signal_filter_source"
MALFORMED_COLUMN = "__signal_filter_malformed"
# A filtered fetch writes the number of rows it dropped for malformed filter fields to this context key.
MALFORMED_COUNT_KEY = "malformed_count"
# When the caller sets DRAIN_WINDOW_KEY, the fetch reads oldest first and reports where a capped batch ended,
# so the caller can resume from there instead of losing the rows past `max_records`.
DRAIN_WINDOW_KEY = "drain_window"
WINDOW_END_KEY = "window_end"
WINDOW_END_ID_KEY = "window_end_id"
WINDOW_CAPPED_KEY = "window_capped"
# With `last_synced_at`, reads rows after that exact (timestamp, cursor id) position.
RESUME_AFTER_ID_KEY = "resume_after_id"
WINDOW_POSITION_COLUMN = "__signal_window_position"
WINDOW_POSITION_ID_COLUMN = "__signal_window_position_id"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
    # toString() keeps the parse valid when the warehouse stored the column as a native timestamp.
    partition_expr = (
        f"parseDateTimeBestEffort(toString({config.partition_field}))"
        if config.partition_field_is_datetime_string
        else config.partition_field
    )
    cursor_id_expr = f"toString({config.cursor_id_field})" if config.cursor_id_field else None
    resume_after_id = context.get(RESUME_AFTER_ID_KEY)
    # Continuous sync — filter records since last sync
    if last_synced_at is not None and resume_after_id and cursor_id_expr:
        where_parts.append(
            f"({partition_expr} > {{last_synced_at}} OR "
            f"({partition_expr} = {{last_synced_at}} AND {cursor_id_expr} > {{resume_after_id}}))"
        )
        placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(last_synced_at))
        placeholders["resume_after_id"] = ast.Constant(value=resume_after_id)
    elif last_synced_at is not None:
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
    saved_filter = saved_filter_from_source_config(context.get("source_config"))
    alias_sql = f" AS {FILTER_SOURCE_ALIAS}" if saved_filter is not None else ""
    drain = bool(context.get(DRAIN_WINDOW_KEY))
    # Limiting can cause a data loss, as the missed records won't be picked in the next sync, but it's acceptable for the current use case
    order_sql = f"ORDER BY {config.order_by}" if config.order_by else ""
    if drain:
        # Milliseconds since the epoch in UTC, so the stored position does not depend on the result timezone.
        fields_sql = f"{fields_sql}, toUnixTimestamp64Milli(toDateTime64({partition_expr}, 3, 'UTC')) AS {WINDOW_POSITION_COLUMN}"
        order_sql = f"ORDER BY {partition_expr} ASC"
        if cursor_id_expr:
            fields_sql = f"{fields_sql}, {cursor_id_expr} AS {WINDOW_POSITION_ID_COLUMN}"
            order_sql = f"{order_sql}, {cursor_id_expr} ASC"
    query = f"""
        SELECT {fields_sql}
        FROM {escape_table_name(table_name)}{alias_sql}
        WHERE {where_sql}
        {order_sql}
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
        filter_context = None
        if saved_filter is not None:
            assert isinstance(parsed, ast.SelectQuery)
            filter_context = _apply_saved_filter(team, config, table_name, parsed, saved_filter)
        if filter_context is None:
            result = execute_hogql_query(
                query=parsed,
                team=team,
                query_type="EmitSignalsNewRecords",
                bypass_warehouse_access_control=True,
                ch_user=ClickHouseUser.SIGNALS,
                workload=Workload.OFFLINE,
            )
        else:
            result = execute_hogql_query(
                query=parsed,
                team=team,
                query_type="EmitSignalsNewRecords",
                context=filter_context,
                bypass_warehouse_access_control=True,
                ch_user=ClickHouseUser.SIGNALS,
                workload=Workload.OFFLINE,
            )
    except Exception as e:
        logger.exception(f"Error querying new records: {e}", **extra)
        # Raising to avoid creating permanent gaps in emitted signals, in hope the activity will fix itself on the restart
        raise
    if not result.results or not result.columns:
        return []
    records = [dict(zip(result.columns, row)) for row in result.results]
    if drain:
        positions = [record.pop(WINDOW_POSITION_COLUMN) for record in records]
        position_ids = [record.pop(WINDOW_POSITION_ID_COLUMN, None) for record in records]
        context[WINDOW_END_KEY] = _EPOCH + timedelta(milliseconds=int(positions[-1]))
        context[WINDOW_END_ID_KEY] = position_ids[-1]
        context[WINDOW_CAPPED_KEY] = len(records) >= config.max_records
    if filter_context is None:
        return records
    passing = [record for record in records if not record.pop(MALFORMED_COLUMN)]
    context[MALFORMED_COUNT_KEY] = len(records) - len(passing)
    if len(passing) < len(records):
        logger.warning(
            "Excluded records with malformed filter fields",
            malformed_count=len(records) - len(passing),
            signal_source_product=config.source_product,
            signal_source_type=config.source_type,
            signals_type="data-import-signals",
            **extra,
        )
    return passing


def saved_filter_from_source_config(source_config: Any) -> SavedSourceFilter | None:
    """The source's saved filter. A malformed stored value raises, so emission stops rather than reading everything."""
    if not isinstance(source_config, dict) or HOGQL_FILTER_KEY not in source_config:
        return None
    return SavedSourceFilter.from_config(source_config[HOGQL_FILTER_KEY])


def _apply_saved_filter(
    team: Team,
    config: SignalSourceTableConfig,
    table_name: str,
    parsed: ast.SelectQuery,
    saved_filter: SavedSourceFilter,
) -> HogQLContext | None:
    """AND the saved filter into the parsed query, before its LIMIT, and select a malformed-row marker.

    Returns a context that carries the database built here, so the executor does not build a second one,
    or None when the saved expression is blank and the query is unchanged.
    """
    database = Database.create_for(team=team, bypass_warehouse_access_control=True)
    columns = {
        name: field for name, field in database.get_table(table_name).fields.items() if isinstance(field, DatabaseField)
    }
    predicate = saved_filter_predicate(
        source_product=config.source_product,
        source_type=config.source_type,
        saved=saved_filter,
        columns=columns,
        source_alias=FILTER_SOURCE_ALIAS,
    )
    if predicate is None:
        return None
    filtered = ast.Or(exprs=[predicate.matches, predicate.malformed])
    parsed.where = ast.And(exprs=[parsed.where, filtered]) if parsed.where is not None else filtered
    parsed.select = [*parsed.select, ast.Alias(alias=MALFORMED_COLUMN, expr=predicate.malformed)]
    return HogQLContext(team_id=team.pk, database=database, bypass_warehouse_access_control=True)
