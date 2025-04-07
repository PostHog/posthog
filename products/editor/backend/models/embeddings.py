from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme


def CODEBASE_EMBEDDINGS_TABLE_NAME():
    return "codebase_embeddings"


CODEBASE_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    user_id Int64,
    codebase_id String,
    artifact_id String,
    vector Array(Float32),
    properties VARCHAR CODEC(ZSTD(3)),
    version UInt32,
    is_deleted UInt8,
) ENGINE = {engine}
"""


def CODEBASE_EMBEDDINGS_TABLE_ENGINE():
    return ReplacingMergeTree(
        CODEBASE_EMBEDDINGS_TABLE_NAME(), replication_scheme=ReplicationScheme.REPLICATED, ver="version, is_deleted"
    )


def CODEBASE_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return (
        CODEBASE_EMBEDDINGS_TABLE_BASE_SQL
        + """
    -- artifact_id for uniqueness
    ORDER BY (team_id, user_id, codebase_id, artifact_id)
    """
    ).format(
        table_name=CODEBASE_EMBEDDINGS_TABLE_NAME(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=CODEBASE_EMBEDDINGS_TABLE_ENGINE(),
    )


def DROP_CODEBASE_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return f"DROP TABLE IF EXISTS {CODEBASE_EMBEDDINGS_TABLE_NAME()} {ON_CLUSTER_CLAUSE(on_cluster)}"


def TRUNCATE_CODEBASE_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return f"TRUNCATE TABLE IF EXISTS {CODEBASE_EMBEDDINGS_TABLE_NAME()} {ON_CLUSTER_CLAUSE(on_cluster)}"
