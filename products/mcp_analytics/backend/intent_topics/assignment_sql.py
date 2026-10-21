"""ClickHouse SQL that assigns every embedded intent in a window to its nearest topic.

Runs inside ClickHouse so no vector leaves the database: one scan of the day's rows, a cosine
distance to each topic centroid, the nearest wins. The 2D map position is a PCA projection with a
basis fitted on the weekly sample. Centroids and the basis travel as query parameters.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    MAX_ASSIGNMENT_TEXT_LENGTH,
)


@dataclass(frozen=True)
class TopicVector:
    topic_id: str
    centroid: list[float]
    outlier_distance: float


@dataclass(frozen=True)
class PcaBasis:
    mean: list[float]
    pc1: list[float]
    pc2: list[float]


def embedding_table_name() -> str:
    return next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()


_ASSIGNMENT_INSERT_SQL = """
INSERT INTO {target_table}
    (team_id, intent_hash, run_id, topic_id, distance, x, y, is_outlier, intent_text, calls_in_run, tool, timestamp)
SELECT
    %(team_id)s AS team_id,
    document_id AS intent_hash,
    %(run_id)s AS run_id,
    arrayElement(%(topic_ids)s, best) AS topic_id,
    toFloat32(arrayElement(dists, best)) AS distance,
    toFloat32(arraySum(arrayMap((v, m, p) -> (v - m) * p, embedding, %(pca_mean)s, %(pca_pc1)s))) AS x,
    toFloat32(arraySum(arrayMap((v, m, p) -> (v - m) * p, embedding, %(pca_mean)s, %(pca_pc2)s))) AS y,
    if(arrayElement(dists, best) > arrayElement(%(thresholds)s, best), 1, 0) AS is_outlier,
    substringUTF8(content, 1, %(max_text_length)s) AS intent_text,
    toUInt32(JSONExtractUInt(metadata, 'calls')) AS calls_in_run,
    JSONExtractString(metadata, 'tool') AS tool,
    now64(3) AS timestamp
FROM (
    SELECT
        document_id,
        content,
        metadata,
        embedding,
        arrayMap(c -> cosineDistance(embedding, c), %(centroids)s) AS dists,
        indexOf(dists, arrayMin(dists)) AS best
    FROM {embedding_table}
    WHERE team_id = %(team_id)s
      AND product = %(product)s
      AND document_type = %(document_type)s
      AND timestamp >= %(window_start)s
      AND timestamp < %(window_end)s
    ORDER BY document_id, inserted_at DESC
    LIMIT 1 BY document_id
)
"""


def build_assignment_insert(
    *,
    team_id: int,
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    topics: list[TopicVector],
    pca: PcaBasis,
    max_text_length: int = MAX_ASSIGNMENT_TEXT_LENGTH,
) -> tuple[str, dict[str, Any]]:
    if not topics:
        raise ValueError("At least one topic is required to assign intents")
    sql = _ASSIGNMENT_INSERT_SQL.format(
        target_table=MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE,
        embedding_table=embedding_table_name(),
    )
    params: dict[str, Any] = {
        "team_id": team_id,
        "run_id": run_id,
        "product": EMBEDDING_PRODUCT,
        "document_type": EMBEDDING_DOCUMENT_TYPE,
        "window_start": window_start,
        "window_end": window_end,
        "topic_ids": [topic.topic_id for topic in topics],
        "centroids": [[float(v) for v in topic.centroid] for topic in topics],
        "thresholds": [float(topic.outlier_distance) for topic in topics],
        "pca_mean": [float(v) for v in pca.mean],
        "pca_pc1": [float(v) for v in pca.pc1],
        "pca_pc2": [float(v) for v in pca.pc2],
        "max_text_length": max_text_length,
    }
    return sql, params
