from datetime import datetime
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.emission.registry import SignalSourceTableConfig

logger = structlog.get_logger(__name__)

# Column added to each page query to carry the row's partition value back as the keyset cursor.
# Stripped before records reach the emitter, so it never leaks into a signal.
_CURSOR_ALIAS = "_signal_partition_cursor"
# Runaway guard for the pagination loop. Each page holds up to `config.max_records` rows, so this
# bounds one sync to a very large but finite backlog. Reaching it is logged as an error, never
# silent — the untouched rows stay above the watermark and the next sync resumes from there.
_MAX_PAGES = 1000


def data_warehouse_record_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch records from a data warehouse table via HogQL.

    Pages through every record newer than the watermark with keyset pagination on the partition
    field, so a sync that finds more than one page of new records picks up the rest on the next
    page instead of dropping it. `config.max_records` is the page size.
    """
    table_name: str = context["table_name"]
    last_synced_at: str | None = context.get("last_synced_at")
    extra: dict[str, Any] = context.get("extra", {})
    partition_expr = (
        f"parseDateTimeBestEffort({config.partition_field})"
        if config.partition_field_is_datetime_string
        else config.partition_field
    )
    base_where: list[str] = []
    base_placeholders: dict[str, Any] = {}
    # Continuous sync — filter records since last sync. First ever sync — look back a limited window.
    if last_synced_at is not None:
        base_where.append(f"{partition_expr} > {{last_synced_at}}")
        base_placeholders["last_synced_at"] = ast.Constant(value=datetime.fromisoformat(last_synced_at))
    else:
        base_where.append(f"{partition_expr} > now() - interval {config.first_sync_lookback_days} day")
    if config.where_clause:
        base_where.append(config.where_clause)
    # None of the data comes externally (neither limits of table name), so it's safe to use f-string interpolation.
    fields_sql = ", ".join(config.fields)
    logger.info(
        "Querying new records for signal emission",
        sync_type="continuous" if last_synced_at is not None else "first",
        last_synced_at=last_synced_at,
        lookback_days=config.first_sync_lookback_days if last_synced_at is None else None,
        table_name=table_name,
        where_clause=" AND ".join(base_where),
        page_size=config.max_records,
        signals_type="data-import-signals",
        **extra,
    )

    records: list[dict[str, Any]] = []
    cursor: Any = None
    for _ in range(_MAX_PAGES):
        where_parts = list(base_where)
        placeholders = dict(base_placeholders)
        if cursor is not None:
            where_parts.append(f"{partition_expr} > {{signal_cursor}}")
            placeholders["signal_cursor"] = ast.Constant(value=cursor)
        query = f"""
            SELECT {fields_sql}, {partition_expr} AS {_CURSOR_ALIAS}
            FROM {table_name}
            WHERE {" AND ".join(where_parts)}
            ORDER BY {partition_expr} ASC
            LIMIT {config.max_records}
        """
        parsed = parse_select(query, placeholders=placeholders)
        try:
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
            break
        page_rows = [dict(zip(result.columns, row)) for row in result.results]
        cursor_values = [row[_CURSOR_ALIAS] for row in page_rows]
        full_page = len(page_rows) == config.max_records
        page_max = cursor_values[-1]
        # A full page may end mid-group, splitting rows that share a partition value across pages.
        # Drop the last group and refetch it whole next page so none is lost — but only when the page
        # holds more than one value, or there is no way to advance the cursor.
        if full_page and cursor_values[0] != page_max:
            page_rows = [row for row, value in zip(page_rows, cursor_values) if value != page_max]
            cursor = page_rows[-1][_CURSOR_ALIAS]
        else:
            if full_page:
                logger.warning(
                    "Signal emission page holds a single partition value; a group larger than the "
                    "page size cannot be split, so its overflow is deferred to the next sync",
                    table_name=table_name,
                    partition_value=str(page_max),
                    page_size=config.max_records,
                    signals_type="data-import-signals",
                    **extra,
                )
            cursor = page_max
        for row in page_rows:
            del row[_CURSOR_ALIAS]
        records.extend(page_rows)
        if not full_page:
            break
    else:
        logger.error(
            "Signal emission pagination hit its page guard; remaining records resume on the next sync",
            table_name=table_name,
            max_pages=_MAX_PAGES,
            records_fetched=len(records),
            signals_type="data-import-signals",
            **extra,
        )

    return records
