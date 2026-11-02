"""Rank a window of past observations from the embeddings search already stored.

The watch rank consumer ranks each new observation as its embedding lands. This ranks the rest: observations whose
results the consumer missed, and every observation again after the anchors change. It reads stored vectors from
ClickHouse rather than embedding again. Feed groups and search themes come from the semantics backfill, which runs
after this one.
"""

import time
import random
from collections import defaultdict
from datetime import datetime
from itertools import batched
from typing import Any

from django.db.models import Count, Exists, OuterRef

import numpy as np
import structlog
from asgiref.sync import async_to_sync

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseAtCapacity

from products.replay_vision.backend.embeddings import (
    OBSERVATION_EMBEDDINGS_TABLE,
    OBSERVATION_SCOPE_PREWHERE,
    TEAM_EMBEDDINGS_PREWHERE,
    observation_scope_params,
    team_embeddings_params,
)
from products.replay_vision.backend.models.replay_highlight_feed import HighlightWindow
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.observation_ranks import NewRank, record_ranks
from products.replay_vision.backend.watch_rank import (
    ANCHOR_VERSION,
    AnchorReading,
    WatchCategory,
    anchor_vectors,
    classify,
    current_ranks,
    normalize,
    save_anchor_similarities,
)

logger = structlog.get_logger(__name__)

_VECTOR_CHUNK = 500
# The longest highlight feed window, so a run covers everything the feed can show.
WATCH_RANK_BACKFILL_DAYS = max(HighlightWindow.values)
_QUERY_TIMEOUT_S = 60
_CAPACITY_RETRY_BASE_S = 15
_CAPACITY_RETRY_ATTEMPTS = 6


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
    """Each observation's stored unit vector, for one batch of a scanner's observations, waiting out a full cluster."""
    return _waiting_out_capacity(
        team_id,
        f"{OBSERVATION_SCOPE_PREWHERE} AND timestamp >= %(since)s",
        {**observation_scope_params(team_id, [scanner_id]), "since": since, "ids": observation_ids},
    )


def stored_vectors_between(
    team_id: int, observation_ids: list[str], since: datetime, until: datetime | None
) -> dict[str, np.ndarray]:
    """Each observation's stored unit vector, across all of a team's scanners, from embeddings stored since `since`
    and before `until` when given. One read covers a whole slice of a team's history, so ClickHouse scans each
    stretch of time once."""
    upper = "" if until is None else " AND timestamp < %(until)s"
    return _waiting_out_capacity(
        team_id,
        f"{TEAM_EMBEDDINGS_PREWHERE} AND timestamp >= %(since)s{upper}",
        {**team_embeddings_params(team_id), "since": since, "until": until, "ids": observation_ids},
    )


def _waiting_out_capacity(team_id: int, prewhere: str, params: dict[str, Any]) -> dict[str, np.ndarray]:
    for attempt in range(_CAPACITY_RETRY_ATTEMPTS - 1):
        try:
            return _read_stored_vectors(team_id, prewhere, params)
        except ClickHouseAtCapacity:
            delay = _CAPACITY_RETRY_BASE_S * 2**attempt
            wait = random.uniform(delay, 2 * delay)
            logger.info("replay_vision.watch_rank_backfill.capacity_wait", team_id=team_id, attempt=attempt, wait=wait)
            time.sleep(wait)
    return _read_stored_vectors(team_id, prewhere, params)


def _read_stored_vectors(team_id: int, prewhere: str, params: dict[str, Any]) -> dict[str, np.ndarray]:
    with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_watch_rank_backfill"):
        # nosemgrep: clickhouse-fstring-param-audit - table name and prewhere are built from module constants
        rows = sync_execute(
            f"""
            SELECT document_id, any(embedding)
            FROM {OBSERVATION_EMBEDDINGS_TABLE}
            PREWHERE {prewhere}
            WHERE document_id IN %(ids)s
            GROUP BY document_id
            """,
            params,
            team_id=team_id,
            readonly=True,
            ch_user=ClickHouseUser.REPLAY_VISION,
            settings={"max_execution_time": _QUERY_TIMEOUT_S},
            workload=Workload.OFFLINE,
        )
    return {str(document_id): normalize(np.asarray(embedding, dtype=np.float32)) for document_id, embedding in rows}


def _rank_scanner(
    rows: list[dict[str, Any]], vectors: dict[str, np.ndarray], anchors: dict[WatchCategory, np.ndarray]
) -> dict[str, AnchorReading]:
    """New ranks for the rows that lack a current one."""
    written: dict[str, AnchorReading] = {}
    for row in rows:
        observation_id = str(row["id"])
        vector = vectors.get(observation_id)
        if vector is None or row["ranked"]:
            continue
        written[observation_id] = classify(vector, anchors)
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
        .annotate(ranked=Exists(current_ranks(team_id).filter(observation_id=OuterRef("id"))))
        .order_by("created_at", "id")
        .values("id", "scanner_id", "ranked")
    ]
    by_scanner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scanner[str(row["scanner_id"])].append(row)
    anchors = async_to_sync(anchor_vectors)(team_id)
    ranked = 0
    embedded = 0
    for scanner_id, scanner_rows in by_scanner.items():
        for batch in batched(scanner_rows, _VECTOR_CHUNK, strict=False):
            vectors = _stored_vectors(team_id, scanner_id, [str(row["id"]) for row in batch], since)
            embedded += len(vectors)
            written = _rank_scanner(list(batch), vectors, anchors)
            ranked += len(written)
            if not dry_run and written:
                save_anchor_similarities(
                    team_id, {observation_id: reading.similarities for observation_id, reading in written.items()}
                )
                # A rank the consumer wrote meanwhile, with its group, stays: an existing rank row is never replaced.
                record_ranks(
                    team_id,
                    ANCHOR_VERSION,
                    {
                        observation_id: NewRank(contrast=reading.rank.contrast, category=reading.rank.category)
                        for observation_id, reading in written.items()
                    },
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
