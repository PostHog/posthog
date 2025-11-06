from collections import defaultdict
from datetime import timedelta
from typing import Optional

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.settings import CLICKHOUSE_CLUSTER

from products.enterprise.backend.clickhouse.materialized_columns.columns import (
    MaterializedColumn,
    backfill_materialized_columns,
    get_materialized_columns,
    materialize,
)
from products.enterprise.backend.settings import (
    MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
    MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
    MATERIALIZE_COLUMNS_MAX_AT_ONCE,
    MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
)

Suggestion = tuple[TableWithProperties, TableColumn, PropertyName]

logger = structlog.get_logger(__name__)


def _analyze(since_hours_ago: int, min_query_time: int, team_id: Optional[int] = None) -> list[Suggestion]:
    "Finds columns that should be materialized"

    raw_queries = sync_execute(
        """
WITH
    {min_query_time} as slow_query_minimum,
    (
        159, -- TIMEOUT EXCEEDED
        160, -- TOO SLOW (estimated query execution time)
    ) as exception_codes,
    20 * 1000 * 1000 * 1000 as min_bytes_read,
    5000000 as min_read_rows
SELECT
    arrayJoin(
        extractAll(query, 'JSONExtract[a-zA-Z0-9]*?\\((?:[a-zA-Z0-9\\`_-]+\\.)?(.*?), .*?\\)')
    ) as column,
    arrayJoin(extractAll(query, 'JSONExtract[a-zA-Z0-9]*?\\(.*?, \\'([a-zA-Z0-9_\\-\\.\\$\\/\\ ]*?)\\'\\)')) as prop_to_materialize
    --,groupUniqArrayIf(JSONExtractInt(log_comment, 'team_id'), type > 2),
    --count(),
    --countIf(type > 2) as failures,
    --countIf(query_duration_ms > 3000) as slow_query,
    --formatReadableSize(avg(read_bytes)),
    --formatReadableSize(max(read_bytes))
FROM
    clusterAllReplicas({cluster}, system, query_log)
WHERE
    query_start_time > now() - toIntervalHour({since})
    and query LIKE '%JSONExtract%'
    and query not LIKE '%JSONExtractKeysAndValuesRaw(group_properties)%'
    and type > 1
    and is_initial_query
    and JSONExtractString(log_comment, 'access_method') != 'personal_api_key' -- API requests failing is less painful than queries in the interface
    and JSONExtractString(log_comment, 'kind') != 'celery'
    and JSONExtractInt(log_comment, 'team_id') != 0
    and query not like '%person_distinct_id2%' -- Old style person properties that are joined, no need to optimize those queries
    and column IN ('properties', 'person_properties', 'group0_properties', 'group1_properties', 'group2_properties', 'group3_properties', 'group4_properties')
    and read_bytes > min_bytes_read
    and (exception_code IN exception_codes OR query_duration_ms > slow_query_minimum)
    and read_rows > min_read_rows
    {team_id_filter}
GROUP BY
    1, 2
HAVING
    countIf(exception_code IN exception_codes) > 0 OR countIf(query_duration_ms > slow_query_minimum) > 9
ORDER BY
    countIf(exception_code IN exception_codes) DESC,
    countIf(query_duration_ms > slow_query_minimum) DESC
LIMIT 100 -- Make sure we don't add 100s of columns in one run
        """.format(
            since=since_hours_ago,
            min_query_time=min_query_time,
            team_id_filter=f"and JSONExtractInt(log_comment, 'team_id') = {team_id}" if team_id else "",
            cluster=CLICKHOUSE_CLUSTER,
        ),
    )

    return [("events", table_column, property_name) for (table_column, property_name) in raw_queries]


def materialize_properties_task(
    properties_to_materialize: Optional[list[Suggestion]] = None,
    time_to_analyze_hours: int = MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
    maximum: int = MATERIALIZE_COLUMNS_MAX_AT_ONCE,
    min_query_time: int = MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
    backfill_period_days: int = MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
    dry_run: bool = False,
    team_id_to_analyze: Optional[int] = None,
    is_nullable: bool = False,
) -> None:
    """
    Creates materialized columns for event and person properties based off of slow queries
    """

    if properties_to_materialize is None:
        properties_to_materialize = _analyze(time_to_analyze_hours, min_query_time, team_id_to_analyze)

    properties_by_table: dict[TableWithProperties, list[tuple[TableColumn, PropertyName]]] = defaultdict(list)
    for table, table_column, property_name in properties_to_materialize:
        properties_by_table[table].append((table_column, property_name))

    result: list[Suggestion] = []
    for table, properties in properties_by_table.items():
        existing_materialized_properties = get_materialized_columns(table).keys()
        for table_column, property_name in properties:
            if (property_name, table_column) not in existing_materialized_properties:
                result.append((table, table_column, property_name))

    if len(result) > 0:
        logger.info(f"Calculated columns that could be materialized. count={len(result)}")
    else:
        logger.info("Found no columns to materialize.")

    materialized_columns: dict[TableWithProperties, list[MaterializedColumn]] = defaultdict(list)
    for table, table_column, property_name in result[:maximum]:
        logger.info(f"Materializing column. table={table}, table_column={table_column} property_name={property_name}")
        if not dry_run:
            materialized_columns[table].append(
                materialize(table, property_name, table_column=table_column, is_nullable=is_nullable)
            )

    if backfill_period_days > 0 and not dry_run:
        logger.info(f"Starting backfill for new materialized columns. period_days={backfill_period_days}")
        for table, columns in materialized_columns.items():
            backfill_materialized_columns(table, columns, timedelta(days=backfill_period_days))
