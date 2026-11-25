"""Delete MCP intent copies from a ClickHouse table and prove no replica still holds them.

Shared by the erasure providers that own ClickHouse copies, so every one deletes and verifies the
same way.
"""

from typing import Any

from django.conf import settings
from django.utils import timezone

from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster, Query
from posthog.clickhouse.workload import Workload
from posthog.models.deletion_targets import DeletionTarget, placement_for

from products.mcp_analytics.backend.facade.contracts import IntentErasurePending


def purge_and_verify(
    cluster: ClickhouseCluster, *, data_table: str, read_table: str, where: str, params: dict[str, Any]
) -> None:
    """Delete the rows of ``data_table`` that match ``where``, then raise unless no replica holds one.

    ``where`` is a trusted predicate over the table's columns, with values passed in ``params``.
    The delete runs on one host per shard and waits until every replica of each shard has applied
    it. The check then reads every replica of the table directly. It covers active parts: parts a
    mutation replaced are dropped by ClickHouse's own cleanup a few minutes later.
    """
    placement = placement_for(cluster, DeletionTarget(data_table=data_table, read_table=read_table, optional=True))
    if placement is None:
        # No host carries the table, and placement_for has already checked that its proxy reads nothing.
        return

    AlterTableMutationRunner(
        table=data_table,
        commands={f"DELETE WHERE {where}"},
        parameters=params,
        # Never adopt an earlier run's finished delete with the same text: it removed nothing written since.
        reuse_since=timezone.now(),
    ).run_on_shards(placement.cluster)

    # nosemgrep: clickhouse-fstring-param-audit (table and predicate come from this product's constants)
    survivors = Query(f"SELECT 1 FROM {settings.CLICKHOUSE_DATABASE}.{data_table} WHERE {where} LIMIT 1", params)
    # The workload argument filters hosts, so DEFAULT is what reaches every replica, online and offline.
    results = placement.cluster.map_hosts_by_role(
        survivors, placement.cluster.shard_role, workload=Workload.DEFAULT
    ).result()
    if not results:
        raise IntentErasurePending(f"No replica could verify the purge of {data_table}")
    if any(results.values()):
        raise IntentErasurePending(f"Intent copies survived the purge of {data_table}")
