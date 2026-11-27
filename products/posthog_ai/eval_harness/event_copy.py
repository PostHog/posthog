from django.conf import settings

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models.event.sql import COPY_EVENT_COLUMNS, COPY_EVENTS_BETWEEN_TEAMS

# Only include values derived from the event fields we copy. A team-specific expression must run on the target.
_REUSABLE_EVENT_COLUMNS = (
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
    "$window_id",
    "$session_id",
    "$session_id_uuid",
    "elements_chain_href",
    "elements_chain_texts",
    "elements_chain_ids",
    "elements_chain_elements",
    "properties_group_custom",
    "properties_group_ai",
    "properties_group_ai_large",
    "properties_group_feature_flags",
    "person_properties_map_custom",
)


def copy_eval_events(source_team_id: int, target_team_id: int) -> None:
    ((can_copy_materialized,),) = sync_execute(
        """
        SELECT uniqExact(shard_num) = 1 AND countIf(is_local) > 0 AND (
            SELECT count() FROM system.columns
            WHERE database = currentDatabase() AND table = 'sharded_events'
              AND default_kind = 'MATERIALIZED' AND name IN %(columns)s
        ) = %(column_count)s
        FROM system.clusters WHERE cluster = %(cluster)s
        """,
        {
            "cluster": settings.CLICKHOUSE_CLUSTER,
            "columns": _REUSABLE_EVENT_COLUMNS,
            "column_count": len(_REUSABLE_EVENT_COLUMNS),
        },
        workload=Workload.OFFLINE,
    )
    query = COPY_EVENTS_BETWEEN_TEAMS
    if can_copy_materialized:
        # The Distributed sink rejects explicit materialized values. A local insert still feeds the session views.
        query = (
            COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
                table_name="sharded_events",
                columns_except_team_id=", ".join((COPY_EVENT_COLUMNS, *_REUSABLE_EVENT_COLUMNS)),
            )
            + " SETTINGS insert_allow_materialized_columns = 1, max_block_size = 16384, min_insert_block_size_rows = 16384, min_insert_block_size_bytes = 33554432"
        )
    sync_execute(query, {"source_team_id": source_team_id, "target_team_id": target_team_id}, workload=Workload.OFFLINE)
