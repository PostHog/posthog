from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.emission.fetchers.data_warehouse import build_cursor_clause, escape_table_name
from products.signals.backend.emission.registry import RecordFetcher, SignalSourceTableConfig
from products.signals.backend.models import SignalEmissionRecord

logger = structlog.get_logger(__name__)

# The ledger drops groups that already produced a signal. If the query read only `max_records` groups,
# the noisiest recurring groups would fill the page on every sync and starve new groups ranked below
# them. The fetcher reads pages of groups until it holds `max_records` new ones, up to a page limit.
GROUP_PAGE_FACTOR = 4
MAX_GROUP_PAGES = 10


def week_period(value: Any) -> str:
    """ISO year and week of a timestamp, or an empty string when it cannot be read.

    Fingerprints carry the period so a group that stays noisy, or returns after a fix, can emit once
    per week instead of once ever.
    """
    text = "" if value is None else str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def grouped_warehouse_record_fetcher(
    *,
    select_sql: str,
    group_by_sql: str,
    order_by_sql: str,
    source_id_for: Callable[[dict[str, Any]], str],
) -> RecordFetcher:
    """Build a fetcher that collapses the new rows of a warehouse table into one record per group.

    High-volume sources (error spans, error logs) store one row per occurrence, so the generic
    fetcher would emit one signal per occurrence. This fetcher walks the groups from the noisiest
    down, drops the groups whose `source_id` is already in `SignalEmissionRecord`, and stops once it
    holds `max_records` new groups. Pair it with `record_processed_outputs=True` on the config so the
    pipeline writes that ledger.

    `select_sql` aliases must match `config.fields`, because the pipeline builds records from them.
    """

    def fetcher(team: Team, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
        table_name: str = context["table_name"]
        last_synced_at: str | None = context.get("last_synced_at")
        extra: dict[str, Any] = context.get("extra", {})
        cursor_clause, placeholders = build_cursor_clause(config, last_synced_at)
        where_sql = f"{cursor_clause} AND {config.where_clause}" if config.where_clause else cursor_clause
        page_size = config.max_records * GROUP_PAGE_FACTOR
        # The group columns break ties, so a group cannot appear on two pages or on none.
        order_sql = f"{order_by_sql}, {group_by_sql}"
        logger.info(
            "Querying grouped records for signal emission",
            sync_type="continuous" if last_synced_at is not None else "first",
            last_synced_at=last_synced_at,
            table_name=table_name,
            max_records=config.max_records,
            page_size=page_size,
            signals_type="data-import-signals",
            **extra,
        )
        new_records: list[dict[str, Any]] = []
        for page in range(MAX_GROUP_PAGES):
            query = f"""
                SELECT {select_sql}
                FROM {escape_table_name(table_name)}
                WHERE {where_sql}
                GROUP BY {group_by_sql}
                ORDER BY {order_sql}
                LIMIT {page_size} OFFSET {page * page_size}
            """
            try:
                parsed = parse_select(query, placeholders=placeholders) if placeholders else parse_select(query)
                result = execute_hogql_query(
                    query=parsed, team=team, query_type="EmitSignalsNewRecords", bypass_warehouse_access_control=True
                )
            except Exception as e:
                logger.exception(f"Error querying grouped records: {e}", **extra)
                # Raise so the activity retries instead of leaving a permanent gap in emitted signals.
                raise
            if not result.results or not result.columns:
                break
            records = [dict(zip(result.columns, row)) for row in result.results]
            source_ids = [source_id_for(record) for record in records]
            already_emitted = set(
                SignalEmissionRecord.objects.filter(
                    team=team,
                    source_product=config.source_product,
                    source_type=config.source_type,
                    source_id__in=source_ids,
                ).values_list("source_id", flat=True)
            )
            new_records.extend(
                record for record, source_id in zip(records, source_ids) if source_id not in already_emitted
            )
            if len(new_records) >= config.max_records or len(records) < page_size:
                break
        return new_records[: config.max_records]

    return fetcher
