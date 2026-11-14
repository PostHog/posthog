"""ClickHouse SQL that assigns every embedded intent in a window to its nearest topic.

Runs inside ClickHouse so no vector leaves the database: a bounded page of live intents, a cosine
distance to each topic centroid, the nearest wins. The 2D map position is a PCA projection with a
basis fitted on the weekly sample. Centroids and the basis travel as query parameters.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np

from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE
from products.mcp_analytics.backend.intent_topics.constants import MAX_ASSIGNMENT_TEXT_LENGTH
from products.mcp_analytics.backend.intent_topics.corpus import IntentQuery, IntentSource, live_intent_embeddings_query


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


# Each centroid is its own constant in the SQL. A single `arrayMap` over a constant array of centroids makes
# ClickHouse copy every embedding once per centroid and materialize the whole centroid array per row, which
# runs out of memory at a few hundred topics.
_ASSIGNMENT_INSERT_SQL = """
INSERT INTO {target_table}
    (team_id, intent_hash, run_id, topic_id, distance, x, y, is_outlier, intent_text, calls_in_run, tool, timestamp)
SELECT
    %(team_id)s AS team_id,
    intent_hash,
    %(run_id)s AS run_id,
    arrayElement(%(topic_ids)s, best) AS topic_id,
    toFloat32(arrayElement(dists, best)) AS distance,
    toFloat32(dotProduct(embedding, %(pca_pc1)s) - %(pca_offset_1)s) AS x,
    toFloat32(dotProduct(embedding, %(pca_pc2)s) - %(pca_offset_2)s) AS y,
    if(arrayElement(dists, best) > arrayElement(%(thresholds)s, best), 1, 0) AS is_outlier,
    substringUTF8(content, 1, %(max_text_length)s) AS intent_text,
    toUInt32(JSONExtractUInt(metadata, 'calls')) AS calls_in_run,
    JSONExtractString(metadata, 'tool') AS tool,
    now64(3) AS timestamp
FROM (
    SELECT
        intent_hash,
        text,
        calls,
        source_min_timestamp,
        embedding,
        [{distance_terms}] AS dists,
        indexOf(dists, arrayMin(dists)) AS best
    FROM ({live_intents})
)
"""


def build_assignment_insert(
    *,
    team: Team,
    run_id: str,
    sources: Sequence[IntentSource],
    as_of: datetime,
    topics: list[TopicVector],
    pca: PcaBasis,
    max_text_length: int = MAX_ASSIGNMENT_TEXT_LENGTH,
) -> IntentQuery:
    if not topics:
        raise ValueError("At least one topic is required to assign intents")
    source = live_intent_embeddings_query(team, sources, as_of=as_of)
    sql = _ASSIGNMENT_INSERT_SQL.format(
        target_table=MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE,
        live_intents=source.sql,
        distance_terms=", ".join(f"cosineDistance(embedding, %(centroid_{i})s)" for i in range(len(topics))),
    )
    mean = np.asarray(pca.mean, dtype=np.float64)
    pc1 = np.asarray(pca.pc1, dtype=np.float64)
    pc2 = np.asarray(pca.pc2, dtype=np.float64)
    params: dict[str, object] = {
        **source.parameters,
        "team_id": team.pk,
        "run_id": run_id,
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
    return replace(source, sql=sql, parameters=params)
