from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import structlog

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.emission.fetchers.data_warehouse import escape_table_name
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.models import SignalEmissionRecord

logger = structlog.get_logger(__name__)

# The ledger drops groups that already produced a signal. If the query read only `max_records` groups,
# the noisiest recurring groups would fill the page on every sync and starve new groups ranked below
# them. The fetcher reads pages of groups until it holds `max_records` new ones, up to a page limit.
GROUP_PAGE_FACTOR = 4
MAX_GROUP_PAGES = 10

# The fetcher reads a fixed trailing window of event time and ignores `last_synced_at`.
# That value is the start time of the previous sync job, so a cursor on it would skip rows that a
# page-capped sync left for the next one, and rows that the source indexed late.
# The ledger plus the weekly fingerprint make a second read of the same rows safe.
# The window covers a page-capped sync that resumes on the next run and late-indexed rows.
GROUPED_WINDOW_DAYS = 2


def week_period(value: Any) -> str:
    """ISO year and week of a timestamp, or an empty string when it cannot be read.

    Fingerprints carry the period so a group that stays noisy, or returns after a fix, can emit once
    per ISO week instead of once ever.
    """
    text = "" if value is None else str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def already_emitted_source_ids(team: Team, config: SignalSourceTableConfig, source_ids: Sequence[str]) -> set[str]:
    """The `source_ids` that already produced a signal for this team and source.

    The ledger is the idempotence key for a fetcher that reads the same rows on more than one sync.
    """
    return set(
        SignalEmissionRecord.objects.filter(
            team=team,
            source_product=config.source_product,
            source_type=config.source_type,
            source_id__in=source_ids,
        ).values_list("source_id", flat=True)
    )


def grouped_window_clause(config: SignalSourceTableConfig, window_days: int = GROUPED_WINDOW_DAYS) -> str:
    """The WHERE clause that keeps rows of the trailing `window_days` days of event time."""
    partition_expr = (
        f"parseDateTimeBestEffort({config.partition_field})"
        if config.partition_field_is_datetime_string
        else config.partition_field
    )
    return f"{partition_expr} > now() - interval {window_days} day"


class GroupedWarehouseRecordFetcher:
    """A record fetcher that collapses a warehouse table into one record per group.

    A group has no single `scope_field` value, so the fetcher rejects a config that sets one.
    """

    def __init__(
        self,
        *,
        select_sql: str,
        group_by_sql: str,
        order_by_sql: str,
        source_id_for: Callable[[dict[str, Any]], str],
        window_days: int,
    ) -> None:
        self._select_sql = select_sql
        self._group_by_sql = group_by_sql
        self._order_by_sql = order_by_sql
        self._source_id_for = source_id_for
        self._window_days = window_days

    def __call__(self, team: Team, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
        if config.scope_field is not None:
            raise ValueError("The grouped warehouse fetcher does not support scope_field")
        table_name: str = context["table_name"]
        extra: dict[str, Any] = context.get("extra", {})
        window_sql = grouped_window_clause(config, self._window_days)
        where_sql = f"{window_sql} AND {config.where_clause}" if config.where_clause else window_sql
        page_size = config.max_records * GROUP_PAGE_FACTOR
        # The group columns break ties, so a group cannot appear on two pages or on none.
        order_sql = f"{self._order_by_sql}, {self._group_by_sql}"
        logger.info(
            "Querying grouped records for signal emission",
            table_name=table_name,
            where_clause=config.where_clause,
            window_days=self._window_days,
            max_records=config.max_records,
            page_size=page_size,
            signals_type="data-import-signals",
            **extra,
        )
        new_records: list[dict[str, Any]] = []
        for page in range(MAX_GROUP_PAGES):
            query = f"""
                SELECT {self._select_sql}
                FROM {escape_table_name(table_name)}
                WHERE {where_sql}
                GROUP BY {self._group_by_sql}
                ORDER BY {order_sql}
                LIMIT {page_size} OFFSET {page * page_size}
            """
            try:
                result = execute_hogql_query(
                    query=parse_select(query),
                    team=team,
                    query_type="EmitSignalsNewRecords",
                    bypass_warehouse_access_control=True,
                )
            except Exception as e:
                logger.exception(f"Error querying grouped records: {e}", **extra)
                # Raise so the activity retries instead of leaving a permanent gap in emitted signals.
                raise
            if not result.results or not result.columns:
                break
            records = [dict(zip(result.columns, row)) for row in result.results]
            source_ids = [self._source_id_for(record) for record in records]
            already_emitted = already_emitted_source_ids(team, config, source_ids)
            new_records.extend(
                record for record, source_id in zip(records, source_ids) if source_id not in already_emitted
            )
            if len(new_records) >= config.max_records or len(records) < page_size:
                break
        return new_records[: config.max_records]


def grouped_warehouse_record_fetcher(
    *,
    select_sql: str,
    group_by_sql: str,
    order_by_sql: str,
    source_id_for: Callable[[dict[str, Any]], str],
    window_days: int = GROUPED_WINDOW_DAYS,
) -> GroupedWarehouseRecordFetcher:
    """Build a fetcher that collapses the recent rows of a warehouse table into one record per group.

    High-volume sources (error spans, error logs) store one row per occurrence, so the generic
    fetcher would emit one signal per occurrence. This fetcher reads the rows of the trailing
    `window_days` days of event time, walks the groups from the noisiest down, drops the groups whose
    `source_id` is already in `SignalEmissionRecord`, and stops once it holds `max_records` new
    groups. Pair it with `record_processed_outputs=True` on the config so the pipeline writes that
    ledger.

    The fetcher ignores `last_synced_at`. Re-reading rows is safe because the ledger and the weekly
    fingerprint (see `week_period`) deduplicate groups, so a row that a capped sync skipped or that
    the source indexed late still gets picked up on a later sync.

    `select_sql` aliases must match `config.fields`, because the pipeline builds records from them.
    Ordering comes from `order_by_sql`, not from `config.order_by`.
    The config must not set `scope_field`, because a group has no single scope value.
    """
    return GroupedWarehouseRecordFetcher(
        select_sql=select_sql,
        group_by_sql=group_by_sql,
        order_by_sql=order_by_sql,
        source_id_for=source_id_for,
        window_days=window_days,
    )
