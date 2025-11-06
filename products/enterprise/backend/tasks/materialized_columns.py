from collections.abc import Iterator

from celery.utils.log import get_task_logger

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns
from posthog.settings import CLICKHOUSE_DATABASE

from products.enterprise.backend.clickhouse.materialized_columns.columns import MaterializedColumn

logger = get_task_logger(__name__)


def get_materialized_columns_with_default_expression() -> Iterator[tuple[str, MaterializedColumn]]:
    table_names: list[TablesWithMaterializedColumns] = ["events", "person"]
    for table_name in table_names:
        for column in MaterializedColumn.get_all(table_name):
            if is_default_expression(table_name, column.name):
                yield table_name, column


def any_ongoing_mutations() -> bool:
    running_mutations_count = sync_execute("SELECT count(*) FROM system.mutations WHERE is_done = 0")[0][0]
    return running_mutations_count > 0


def is_default_expression(table: str, column_name: ColumnName) -> bool:
    updated_table = "sharded_events" if table == "events" else table
    column_query = sync_execute(
        "SELECT default_kind FROM system.columns WHERE table = %(table)s AND name = %(name)s AND database = %(database)s",
        {"table": updated_table, "name": column_name, "database": CLICKHOUSE_DATABASE},
    )
    return len(column_query) > 0 and column_query[0][0] == "DEFAULT"
