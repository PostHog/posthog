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
from posthog.dataclasses import frozen

from products.replay_vision.backend.embeddings import (
    OBSERVATION_EMBEDDINGS_TABLE,
    OBSERVATION_SCOPE_PREWHERE,
    observation_scope_params,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.watch_rank import (
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
    team_id: int, scanner_ids: list[str], observation_ids: list[str], since: datetime
) -> dict[str, np.ndarray]:
    """Each observation's stored unit vector, read in chunks so a busy team never loads at once."""
    vectors: dict[str, np.ndarray] = {}
    for chunk in batched(observation_ids, _VECTOR_CHUNK, strict=False):
        with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_watch_rank_backfill"):
            rows = sync_execute(
                # nosemgrep: clickhouse-fstring-param-audit -- table name and scope are module constants
                f"""
                SELECT document_id, any(embedding)
                FROM {OBSERVATION_EMBEDDINGS_TABLE}
                PREWHERE {OBSERVATION_SCOPE_PREWHERE}
                  AND timestamp >= %(since)s
                WHERE document_id IN %(ids)s
                GROUP BY document_id
                """,
                {**observation_scope_params(team_id, scanner_ids), "since": since, "ids": list(chunk)},
                team_id=team_id,
                readonly=True,
                ch_user=ClickHouseUser.REPLAY_VISION,
                settings={"max_execution_time": _QUERY_TIMEOUT_S},
            )
        for document_id, embedding in rows:
            vectors[str(document_id)] = normalize(np.asarray(embedding, dtype=np.float32))
    return vectors


def _rank_scanner(
    rows: list[dict[str, Any]], vectors: dict[str, np.ndarray], anchors: dict[WatchCategory, np.ndarray]
) -> dict[str, dict[str, Any]]:
    """New ranks for the scanner's rows that lack a current one, walking oldest first."""
    embedded = [row for row in rows if str(row["id"]) in vectors]
    if not embedded:
        return {}
    ids = [str(row["id"]) for row in embedded]
    matrix = np.stack([vectors[observation_id] for observation_id in ids])
    ranks: dict[str, dict[str, Any] | None] = {}
    written: dict[str, dict[str, Any]] = {}
    for index, (observation_id, row) in enumerate(zip(ids, embedded)):
        rank = current_rank(row)
        if rank is None:
            category, contrast = classify(matrix[index], anchors)
            duplicate_of: str | None = None
            if index > 0:
                distances = 1.0 - matrix[:index] @ matrix[index]
                nearest = int(np.argmin(distances))
                if distances[nearest] <= DUPLICATE_MAX_DISTANCE:
                    duplicate_of = duplicate_root(ids[nearest], ranks.get(ids[nearest]))
            rank = WatchRank(category=category, contrast=contrast, duplicate_of=duplicate_of).to_json()
            written[observation_id] = rank
        ranks[observation_id] = rank
    return written


def backfill_team_watch_ranks(team_id: int, since: datetime, *, dry_run: bool = False) -> WatchRankBackfillResult:
    """Rank the team's succeeded observations since `since` that lack a rank from the current anchors."""
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
    vectors = _stored_vectors(team_id, list(by_scanner), [str(row["id"]) for row in rows], since)

    anchors = async_to_sync(anchor_vectors)(team_id)
    written: dict[str, dict[str, Any]] = {}
    for scanner_rows in by_scanner.values():
        written.update(_rank_scanner(scanner_rows, vectors, anchors))
    if not dry_run and written:
        # The ids come from the team-scoped query above, so the update needs no team filter of its own.
        ReplayObservation.objects.bulk_update(
            [ReplayObservation(id=observation_id, watch_rank=rank) for observation_id, rank in written.items()],
            ["watch_rank"],
            batch_size=_VECTOR_CHUNK,
        )
    without_embedding = sum(1 for row in rows if str(row["id"]) not in vectors)
    logger.info(
        "replay_vision.watch_rank_backfill.team_done",
        team_id=team_id,
        observations=len(rows),
        ranked=len(written),
        without_embedding=without_embedding,
        dry_run=dry_run,
    )
    return WatchRankBackfillResult(observations=len(rows), ranked=len(written), without_embedding=without_embedding)
