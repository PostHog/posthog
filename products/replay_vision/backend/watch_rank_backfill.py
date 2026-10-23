"""Rank a window of past observations from the embeddings search already stored.

The scan workflow ranks each new observation as it lands. This fills in the observations from before
that shipped, so a team can move to the embedding ranker without waiting a week for ranks to build
up. It reads stored vectors from ClickHouse rather than embedding again, and finds near-duplicates in
memory per scanner, oldest first, the same way the scan workflow would have found them.
"""

from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count

import numpy as np
import structlog
from asgiref.sync import async_to_sync

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.replay_vision.backend.embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.watch_rank import (
    _EMBEDDINGS_TABLE,
    ANCHOR_VERSION,
    DUPLICATE_MAX_DISTANCE,
    WatchCategory,
    WatchRank,
    anchor_vectors,
    classify,
    duplicate_root,
)

logger = structlog.get_logger(__name__)

_VECTOR_CHUNK = 500
_QUERY_TIMEOUT_S = 60


@frozen
class WatchRankBackfillResult:
    observations: int
    ranked: int
    without_embedding: int


def teams_with_observations(since: datetime) -> list[int]:
    """Teams with succeeded observations since `since`, busiest first."""
    return list(
        ReplayObservation.objects.filter(status=ObservationStatus.SUCCEEDED, created_at__gte=since)
        .values("team_id")
        .annotate(n=Count("id"))
        .order_by("-n")
        .values_list("team_id", flat=True)
    )


def _chunks(ids: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def _stored_vectors(
    team_id: int, scanner_id: str, observation_ids: list[str], since: datetime
) -> dict[str, np.ndarray]:
    """Each observation's stored unit vector, read in chunks so a busy scanner never loads at once."""
    vectors: dict[str, np.ndarray] = {}
    for chunk in _chunks(observation_ids, _VECTOR_CHUNK):
        with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_watch_rank_backfill"):
            rows = sync_execute(
                # nosemgrep: clickhouse-fstring-param-audit -- table name is a module constant
                f"""
                SELECT document_id, any(embedding)
                FROM {_EMBEDDINGS_TABLE}
                PREWHERE team_id = %(team_id)s
                  AND product = %(product)s
                  AND document_type = %(document_type)s
                  AND JSONExtractString(metadata, 'scanner_id') = %(scanner_id)s
                  AND timestamp >= %(since)s
                WHERE document_id IN %(ids)s
                GROUP BY document_id
                """,
                {
                    "team_id": team_id,
                    "product": EMBEDDING_PRODUCT,
                    "document_type": EMBEDDING_DOCUMENT_TYPE,
                    "scanner_id": scanner_id,
                    "since": since,
                    "ids": chunk,
                },
                team_id=team_id,
                readonly=True,
                ch_user=ClickHouseUser.REPLAY_VISION,
                settings={"max_execution_time": _QUERY_TIMEOUT_S},
            )
        for document_id, embedding in rows:
            vector = np.asarray(embedding, dtype=np.float32)
            vectors[str(document_id)] = vector / np.linalg.norm(vector)
    return vectors


def _rank_scanner(
    rows: list[dict[str, Any]], vectors: dict[str, np.ndarray], anchors: dict[WatchCategory, np.ndarray]
) -> dict[str, dict[str, Any]]:
    """New ranks for the scanner's rows that lack a current one, walking oldest first."""
    ranks: dict[str, dict[str, Any] | None] = {}
    seen_ids: list[str] = []
    seen_vectors: list[np.ndarray] = []
    written: dict[str, dict[str, Any]] = {}
    for row in rows:
        observation_id = str(row["id"])
        vector = vectors.get(observation_id)
        if vector is None:
            continue
        current = row["watch_rank"]
        if isinstance(current, dict) and current.get("anchor_version") == ANCHOR_VERSION:
            rank: dict[str, Any] | None = current
        else:
            category, contrast = classify(vector.tolist(), anchors)
            duplicate_of: str | None = None
            if seen_vectors:
                distances = 1.0 - np.stack(seen_vectors) @ vector
                nearest = int(np.argmin(distances))
                if distances[nearest] <= DUPLICATE_MAX_DISTANCE:
                    duplicate_of = duplicate_root(seen_ids[nearest], ranks.get(seen_ids[nearest]))
            rank = WatchRank(category=category, contrast=contrast, duplicate_of=duplicate_of).to_json()
            written[observation_id] = rank
        ranks[observation_id] = rank
        seen_ids.append(observation_id)
        seen_vectors.append(vector)
    return written


def backfill_team_watch_ranks(team: Team, since: datetime, *, dry_run: bool = False) -> WatchRankBackfillResult:
    """Rank the team's succeeded observations since `since` that lack a rank from the current anchors."""
    rows: list[dict[str, Any]] = [
        dict(row)
        for row in ReplayObservation.objects.filter(
            team_id=team.id, status=ObservationStatus.SUCCEEDED, created_at__gte=since
        )
        .order_by("created_at", "id")
        .values("id", "scanner_id", "watch_rank")
    ]
    by_scanner: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scanner[row["scanner_id"]].append(row)

    anchors = async_to_sync(anchor_vectors)(team)
    ranked = 0
    without_embedding = 0
    for scanner_id, scanner_rows in by_scanner.items():
        vectors = _stored_vectors(team.id, str(scanner_id), [str(row["id"]) for row in scanner_rows], since)
        without_embedding += sum(1 for row in scanner_rows if str(row["id"]) not in vectors)
        written = _rank_scanner(scanner_rows, vectors, anchors)
        ranked += len(written)
        if not dry_run and written:
            # The ids come from the team-scoped query above, so the update needs no team filter of its own.
            ReplayObservation.objects.bulk_update(
                [ReplayObservation(id=observation_id, watch_rank=rank) for observation_id, rank in written.items()],
                ["watch_rank"],
                batch_size=_VECTOR_CHUNK,
            )
    logger.info(
        "replay_vision.watch_rank_backfill.team_done",
        team_id=team.id,
        observations=len(rows),
        ranked=ranked,
        without_embedding=without_embedding,
        dry_run=dry_run,
    )
    return WatchRankBackfillResult(observations=len(rows), ranked=ranked, without_embedding=without_embedding)
