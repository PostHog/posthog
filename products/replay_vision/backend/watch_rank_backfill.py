"""Rank a window of past observations from the embeddings search already stored.

The scan workflow ranks each new observation as it lands. This fills in the observations from before
that shipped, so a team can move to the embedding ranker without waiting a week for ranks to build
up. It reads stored vectors from ClickHouse rather than embedding again, and finds near-duplicates in
memory per scanner, oldest first, the same way the scan workflow would have found them.
"""

from collections import defaultdict
from datetime import datetime
from itertools import batched
from typing import Any

from django.db.models import Count

import numpy as np
import structlog
from asgiref.sync import async_to_sync

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.replay_vision.backend.embeddings import (
    OBSERVATION_EMBEDDINGS_TABLE,
    OBSERVATION_SCOPE_PREWHERE,
    observation_scope_params,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.watch_rank import (
    DUPLICATE_CANDIDATE_ROWS,
    DUPLICATE_MAX_DISTANCE,
    WatchCategory,
    WatchRank,
    anchor_vectors,
    classify,
    current_rank,
    duplicate_root,
    normalize,
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


def _stored_vectors(
    team_id: int, scanner_id: str, observation_ids: list[str], since: datetime
) -> dict[str, np.ndarray]:
    """Each observation's stored unit vector, for one batch of a scanner's observations."""
    with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_watch_rank_backfill"):
        # nosemgrep: clickhouse-fstring-param-audit - table name and scope are module constants
        rows = sync_execute(
            f"""
            SELECT document_id, any(embedding)
            FROM {OBSERVATION_EMBEDDINGS_TABLE}
            PREWHERE {OBSERVATION_SCOPE_PREWHERE}
              AND timestamp >= %(since)s
            WHERE document_id IN %(ids)s
            GROUP BY document_id
            """,
            {**observation_scope_params(team_id, [scanner_id]), "since": since, "ids": observation_ids},
            team_id=team_id,
            readonly=True,
            ch_user=ClickHouseUser.REPLAY_VISION,
            settings={"max_execution_time": _QUERY_TIMEOUT_S},
            workload=Workload.OFFLINE,
        )
    return {str(document_id): normalize(np.asarray(embedding, dtype=np.float32)) for document_id, embedding in rows}


@frozen
class _Neighbour:
    observation_id: str
    rank: dict[str, Any] | None
    distance: float


class _RecentVectors:
    """A scanner's newest vectors and ranks, capped like the live duplicate lookup so memory and work stay bounded."""

    def __init__(self, capacity: int = DUPLICATE_CANDIDATE_ROWS) -> None:
        self._capacity = capacity
        self._matrix: np.ndarray | None = None
        self._ids: list[str] = []
        self._ranks: list[dict[str, Any] | None] = []
        self._next = 0

    def nearest(self, vector: np.ndarray) -> _Neighbour | None:
        if self._matrix is None or not self._ids:
            return None
        distances = 1.0 - self._matrix[: len(self._ids)] @ vector
        index = int(np.argmin(distances))
        return _Neighbour(observation_id=self._ids[index], rank=self._ranks[index], distance=float(distances[index]))

    def add(self, observation_id: str, vector: np.ndarray, rank: dict[str, Any] | None) -> None:
        if self._matrix is None:
            self._matrix = np.empty((self._capacity, vector.shape[0]), dtype=np.float32)
        self._matrix[self._next] = vector
        if len(self._ids) < self._capacity:
            self._ids.append(observation_id)
            self._ranks.append(rank)
        else:
            self._ids[self._next] = observation_id
            self._ranks[self._next] = rank
        self._next = (self._next + 1) % self._capacity


def _rank_scanner(
    rows: list[dict[str, Any]],
    vectors: dict[str, np.ndarray],
    anchors: dict[WatchCategory, np.ndarray],
    recent: _RecentVectors | None = None,
) -> dict[str, dict[str, Any]]:
    """New ranks for the rows that lack a current one, walking oldest first.

    Pass the same `recent` across a scanner's batches, so a copy finds a match from an earlier batch.
    """
    recent = recent if recent is not None else _RecentVectors()
    written: dict[str, dict[str, Any]] = {}
    for row in rows:
        observation_id = str(row["id"])
        vector = vectors.get(observation_id)
        if vector is None:
            continue
        rank = current_rank(row)
        if rank is None:
            category, contrast = classify(vector, anchors)
            duplicate_of: str | None = None
            nearest = recent.nearest(vector)
            if nearest is not None and nearest.distance <= DUPLICATE_MAX_DISTANCE:
                duplicate_of = duplicate_root(observation_id, nearest.observation_id, nearest.rank)
            rank = WatchRank(category=category, contrast=contrast, duplicate_of=duplicate_of).to_json()
            written[observation_id] = rank
        recent.add(observation_id, vector, rank)
    return written


def backfill_team_watch_ranks(team_id: int, since: datetime, *, dry_run: bool = False) -> WatchRankBackfillResult:
    """Rank the team's succeeded observations since `since` that lack a rank from the current anchors.

    Works one scanner and one batch at a time, and saves each batch before the next, so a large team
    never holds its whole window in memory and an interrupted run keeps what it finished.
    """
    rows: list[dict[str, Any]] = [
        dict(row)
        for row in ReplayObservation.objects.filter(
            team_id=team_id, status=ObservationStatus.SUCCEEDED, created_at__gte=since
        )
        .order_by("created_at", "id")
        .values("id", "scanner_id", "watch_rank")
    ]
    by_scanner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scanner[str(row["scanner_id"])].append(row)
    anchors = async_to_sync(anchor_vectors)(team_id)
    ranked = 0
    embedded = 0
    for scanner_id, scanner_rows in by_scanner.items():
        recent = _RecentVectors()
        for batch in batched(scanner_rows, _VECTOR_CHUNK, strict=False):
            vectors = _stored_vectors(team_id, scanner_id, [str(row["id"]) for row in batch], since)
            embedded += len(vectors)
            written = _rank_scanner(list(batch), vectors, anchors, recent)
            ranked += len(written)
            if not dry_run and written:
                # The ids come from the team-scoped query above, so the update needs no team filter of its own.
                ReplayObservation.objects.bulk_update(
                    [ReplayObservation(id=observation_id, watch_rank=rank) for observation_id, rank in written.items()],
                    ["watch_rank"],
                )
    without_embedding = len(rows) - embedded
    logger.info(
        "replay_vision.watch_rank_backfill.team_done",
        team_id=team_id,
        observations=len(rows),
        ranked=ranked,
        without_embedding=without_embedding,
        dry_run=dry_run,
    )
    return WatchRankBackfillResult(observations=len(rows), ranked=ranked, without_embedding=without_embedding)
