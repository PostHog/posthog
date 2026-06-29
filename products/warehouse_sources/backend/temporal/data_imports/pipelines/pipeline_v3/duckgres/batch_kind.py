"""Canonical definition of "what kind of batch is this?" for the duckgres sink.

Two kinds exist: LIVE batches produced by the v3 sync pipeline, and synthetic
DUCKGRES_BACKFILL batches enqueued by the backfill planner. The discriminator
travels in batch metadata (the queue schema predates the distinction; a typed
``kind`` column on sourcebatch is the planned follow-up migration). Every
consumer of the distinction — queue SQL, processor dispatch, planner enqueue —
derives it from THIS module so the convention has exactly one definition per
language (one Python predicate, one SQL fragment).
"""

from __future__ import annotations

from typing import Any

BACKFILL_METADATA_KEY = "duckgres_backfill"

# SQL twin of is_backfill_metadata, for queries aliasing sourcebatch as ``b``.
LIVE_BATCH_SQL_PREDICATE = f"(b.metadata->>'{BACKFILL_METADATA_KEY}') IS NULL"
BACKFILL_BATCH_SQL_PREDICATE = f"(b.metadata->>'{BACKFILL_METADATA_KEY}') IS NOT NULL"


def is_backfill_metadata(metadata: dict[str, Any] | None) -> bool:
    return bool(metadata and metadata.get(BACKFILL_METADATA_KEY))


def build_backfill_metadata(*, chunk_paths: list[str], chunk_count: int) -> dict[str, Any]:
    """The only shape backfill batch metadata is ever written in."""
    return {
        BACKFILL_METADATA_KEY: True,
        "chunk_paths": chunk_paths,
        "chunk_count": chunk_count,
    }


def backfill_chunk_paths(metadata: dict[str, Any]) -> list[str]:
    paths = metadata.get("chunk_paths")
    if not isinstance(paths, list) or not paths:
        raise ValueError("backfill batch has no chunk_paths metadata")
    return [str(p) for p in paths]


def backfill_chunk_count(metadata: dict[str, Any]) -> int:
    return int(metadata.get("chunk_count") or 0)
