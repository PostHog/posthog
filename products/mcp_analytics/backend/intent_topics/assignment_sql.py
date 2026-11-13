"""ClickHouse SQL that assigns every embedded intent in a window to its nearest topic.

Runs inside ClickHouse so no vector leaves the database: one scan of the day's rows, a cosine
distance to each topic centroid, the nearest wins. The 2D map position is a PCA projection with a
basis fitted on the weekly sample. Centroids and the basis travel as query parameters.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

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


# Each centroid is its own constant in the SQL. A single `arrayMap` over a constant array of centroids makes
# ClickHouse copy every embedding once per centroid and materialize the whole centroid array per row, which
# runs out of memory at a few hundred topics. Duplicate embedding rows for one intent are not removed here:
# they carry the same vector, so they get the same topic, and the assignments table keeps one row per intent.
_ASSIGNMENT_INSERT_SQL = """
INSERT INTO {target_table}
    (team_id, intent_hash, run_id, topic_id, distance, x, y, is_outlier, intent_text, calls_in_run, timestamp)
SELECT
    %(team_id)s AS team_id,
    document_id AS intent_hash,
    %(run_id)s AS run_id,
    arrayElement(%(topic_ids)s, best) AS topic_id,
    toFloat32(arrayElement(dists, best)) AS distance,
    toFloat32(dotProduct(embedding, %(pca_pc1)s) - %(pca_offset_1)s) AS x,
    toFloat32(dotProduct(embedding, %(pca_pc2)s) - %(pca_offset_2)s) AS y,
    if(arrayElement(dists, best) > arrayElement(%(thresholds)s, best), 1, 0) AS is_outlier,
    substringUTF8(content, 1, %(max_text_length)s) AS intent_text,
    toUInt32(JSONExtractUInt(metadata, 'calls')) AS calls_in_run,
    now64(3) AS timestamp
FROM (
    SELECT
        document_id,
        content,
        metadata,
        embedding,
        [{distance_terms}] AS dists,
        indexOf(dists, arrayMin(dists)) AS best
    FROM {embedding_table}
    WHERE team_id = %(team_id)s
      AND product = %(product)s
      AND document_type = %(document_type)s
      AND timestamp >= %(window_start)s
      AND timestamp < %(window_end)s
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
        distance_terms=", ".join(f"cosineDistance(embedding, %(centroid_{i})s)" for i in range(len(topics))),
    )
    mean = np.asarray(pca.mean, dtype=np.float64)
    pc1 = np.asarray(pca.pc1, dtype=np.float64)
    pc2 = np.asarray(pca.pc2, dtype=np.float64)
    params: dict[str, Any] = {
        "team_id": team_id,
        "run_id": run_id,
        "product": EMBEDDING_PRODUCT,
        "document_type": EMBEDDING_DOCUMENT_TYPE,
        "window_start": window_start,
        "window_end": window_end,
        "topic_ids": [topic.topic_id for topic in topics],
        "thresholds": [float(topic.outlier_distance) for topic in topics],
        # (v - mean) . pc == v . pc - mean . pc, so the mean term is a constant per axis.
        "pca_pc1": pc1.tolist(),
        "pca_pc2": pc2.tolist(),
        "pca_offset_1": float(mean @ pc1),
        "pca_offset_2": float(mean @ pc2),
        "max_text_length": max_text_length,
        **{f"centroid_{i}": [float(v) for v in topic.centroid] for i, topic in enumerate(topics)},
    }
    return sql, params
