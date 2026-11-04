"""Test helpers shared by the intent topics tests."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np

from posthog.clickhouse.client import sync_execute

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DIMENSION,
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RENDERING,
)


def recent_hour(days_ago: int = 1) -> datetime:
    """A whole hour inside every intent topics table's TTL; ClickHouse expires rows with its own clock."""
    return datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=days_ago)


_EMBEDDING_TABLE = next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()


def unit_vector(seed_axis: int, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    vector = np.zeros(dimension, dtype=np.float64)
    vector[seed_axis % dimension] = 1.0
    return vector.tolist()


def insert_intent_embedding(
    team_id: int,
    intent_hash: str,
    text: str,
    *,
    at: datetime | None = None,
    embedding: list[float] | None = None,
    calls: int = 1,
    tool: str = "query-trends",
) -> None:
    at = at or datetime.now(tz=UTC)
    sync_execute(
        f"""
        INSERT INTO {_EMBEDDING_TABLE} (
            team_id, product, document_type, rendering, document_id, timestamp, inserted_at,
            content, metadata, embedding, _timestamp, _offset, _partition
        ) VALUES
        """,
        [
            (
                team_id,
                EMBEDDING_PRODUCT,
                EMBEDDING_DOCUMENT_TYPE,
                EMBEDDING_RENDERING,
                intent_hash,
                at,
                at,
                text,
                json.dumps({"calls": calls, "tool": tool}),
                embedding or unit_vector(0),
                at,
                0,
                0,
            )
        ],
    )
