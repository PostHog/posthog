"""Brings observations ranked before the consumer wrote everything it writes today up to date: anchor similarities,
feed groups and search themes, so the feed and the suggestions start from history."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import batched

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import numpy as np
import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.watch_rank import (
    ANCHOR_VERSION,
    AnchorReading,
    WatchCategory,
    anchor_vectors,
    classify,
    current_ranks,
    save_anchor_similarities,
)
from products.replay_vision.backend.watch_rank_backfill import stored_vectors_between
from products.replay_vision.backend.watch_semantics import SemanticItem, assign_semantics_batch
from products.replay_vision.backend.watch_themes import name_theme, naming_candidates

logger = structlog.get_logger(__name__)

# Rows per ClickHouse read, across all of a team's scanners, oldest first.
_SLICE_ROWS = 5_000
# An embedding lands a few minutes after its observation, so a slice reads a little past its newest row.
_EMBEDDING_LAG = timedelta(hours=2)
# Observations per centre lock, kept small so a live consumer message for the same scanner waits seconds at most.
_ASSIGN_CHUNK = 100


@frozen
class _Pending:
    observation_id: str
    scanner_id: str
    created_at: datetime
    needs_group: bool
    needs_similarities: bool


@frozen
class SemanticBackfillResult:
    observations: int
    assigned: int
    named: int


def backfill_team_semantics(team_id: int, since: datetime, *, dry_run: bool = False) -> SemanticBackfillResult:
    """Replay a team's ranked observations oldest first, as the consumer would have seen them, then name the themes
    the Search tab can suggest."""
    has_similarities = Exists(
        ReplayObservationAnchorSimilarity.objects.for_team(team_id).filter(
            observation_id=OuterRef("observation_id"), anchor_version=ANCHOR_VERSION
        )
    )
    pending = (
        current_ranks(team_id)
        .filter(created_at__gte=since)
        .annotate(has_similarities=has_similarities)
        .filter(Q(feed_group_id__isnull=True) | Q(has_similarities=False))
    )
    if dry_run:
        return SemanticBackfillResult(observations=pending.count(), assigned=0, named=0)

    anchors = async_to_sync(anchor_vectors)(team_id)
    observations = 0
    assigned = 0
    # One page per query and per slice, because a pooled connection buffers a whole result however it is iterated.
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        page = pending.order_by("created_at", "observation_id")
        if after:
            page = page.filter(Q(created_at__gt=after[0]) | Q(created_at=after[0], observation_id__gt=after[1]))
        values = list(
            page.values_list("observation_id", "scanner_id", "created_at", "feed_group_id", "has_similarities")[
                :_SLICE_ROWS
            ]
        )
        if not values:
            break
        slice_rows = [
            _Pending(
                observation_id=str(observation_id),
                scanner_id=str(scanner_id),
                created_at=created_at,
                needs_group=group is None,
                needs_similarities=not has_row,
            )
            for observation_id, scanner_id, created_at, group, has_row in values
        ]
        observations += len(slice_rows)
        assigned += _backfill_slice(team_id, slice_rows, anchors)
        if len(values) < _SLICE_ROWS:
            break
        after = (values[-1][2], values[-1][0])
    return SemanticBackfillResult(observations=observations, assigned=assigned, named=_name_suggestable_themes(team_id))


def _backfill_slice(team_id: int, slice_rows: list[_Pending], anchors: dict[WatchCategory, np.ndarray]) -> int:
    ids = [row.observation_id for row in slice_rows]
    since = slice_rows[0].created_at
    vectors = stored_vectors_between(team_id, ids, since, slice_rows[-1].created_at + _EMBEDDING_LAG)
    # A scan delayed by a backlog embeds long after its observation was created, so rows the bounded read missed get
    # one read with no upper bound.
    if late := [observation_id for observation_id in ids if observation_id not in vectors]:
        vectors |= stored_vectors_between(team_id, late, since, None)
        if missing := sum(observation_id not in vectors for observation_id in late):
            logger.info("replay_vision.watch_semantics_backfill.no_vector", team_id=team_id, observations=missing)
    readings: dict[str, AnchorReading] = {
        row.observation_id: classify(vectors[row.observation_id], anchors)
        for row in slice_rows
        if row.observation_id in vectors and row.needs_similarities
    }
    save_anchor_similarities(
        team_id,
        {
            row.observation_id: readings[row.observation_id].similarities
            for row in slice_rows
            if row.needs_similarities and row.observation_id in readings
        },
    )
    by_scanner: dict[str, list[SemanticItem]] = defaultdict(list)
    for row in slice_rows:
        if row.needs_group and row.observation_id in vectors:
            by_scanner[row.scanner_id].append(
                SemanticItem(observation_id=row.observation_id, vector=vectors[row.observation_id], now=row.created_at)
            )
    assigned = 0
    for scanner_id, items in by_scanner.items():
        for chunk in batched(items, _ASSIGN_CHUNK, strict=False):
            assigned += len(assign_semantics_batch(team_id=team_id, scanner_id=scanner_id, items=chunk))
    return assigned


def _name_suggestable_themes(team_id: int) -> int:
    now = timezone.now()
    named = 0
    for theme_id in list(naming_candidates(team_id, now).order_by("-member_count").values_list("id", flat=True)):
        try:
            named += async_to_sync(name_theme)(team_id, theme_id, now) is not None
        except Exception:
            logger.exception("replay_vision.watch_semantics_backfill.naming_failed", team_id=team_id)
    return named
