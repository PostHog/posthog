"""Erasure provider for the intent copies this layer stores.

The coordinator in ``intent_erasure`` calls ``purge_intent_storage`` while the project's writes are
frozen and its writers have drained. It does not re-check document embeddings itself, so this
provider is the only check that none of them survives.
"""

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.scoping import team_scope

from products.error_tracking.backend.facade.api import document_embedding_tables, document_embeddings_buffer_table
from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
)
from products.mcp_analytics.backend.facade.contracts import IntentErasure
from products.mcp_analytics.backend.intent_erasure_clickhouse import purge_and_verify
from products.mcp_analytics.backend.intent_topics.constants import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT
from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot, MCPIntentEmbeddingCache, MCPSession


def purge_intent_storage(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> None:
    """Delete every intent copy of the erasure's environments, and raise if any replica still holds one."""
    team_ids = {"team_ids": erasure.source_team_ids}

    purge_and_verify(
        cluster,
        data_table=MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
        read_table=MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
        where="team_id IN %(team_ids)s",
        params=team_ids,
    )

    # Other products embed into the same tables, so only this product's intent documents go.
    embeddings = {**team_ids, "product": EMBEDDING_PRODUCT, "document_type": EMBEDDING_DOCUMENT_TYPE}
    embedding_where = "team_id IN %(team_ids)s AND product = %(product)s AND document_type = %(document_type)s"
    tables = [(table.sharded_table, table.distributed_table) for table in document_embedding_tables()]
    buffer = document_embeddings_buffer_table()
    tables.append((buffer, buffer))
    for data_table, read_table in tables:
        purge_and_verify(
            cluster, data_table=data_table, read_table=read_table, where=embedding_where, params=embeddings
        )

    for team_id in erasure.source_team_ids:
        with team_scope(team_id, canonical=True):
            # A session row records ordinary MCP traffic; only the intent text copied into it is derived.
            MCPSession.objects.filter(team_id=team_id).exclude(intent__isnull=True).update(intent=None)
            MCPIntentClusterSnapshot.objects.filter(team_id=team_id).update(clusters={})
            MCPIntentEmbeddingCache.objects.filter(team_id=team_id).delete()
