"""Brings observations ranked before the consumer wrote everything it writes today up to date: category scores,
anchor similarities, feed groups and search themes, so the feed and the suggestions start from history."""

from collections import defaultdict
from datetime import datetime, timedelta
from itertools import batched

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import numpy as np
import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.watch_rank import (
    ANCHOR_VERSION,
    AnchorReading,
    WatchCategory,
    anchor_vectors,
    classify,
    save_anchor_similarities,
)
from products.replay_vision.backend.watch_rank_backfill import stored_vectors_between
from products.replay_vision.backend.watch_semantics import SemanticItem, assign_semantics_batch, merge_watch_ranks
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
    needs_scores: bool
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
            observation_id=OuterRef("id"), anchor_version=ANCHOR_VERSION
        )
    )
    pending = (
        ReplayObservation.objects.filter(
            team_id=team_id, status="succeeded", created_at__gte=since, watch_rank__anchor_version=ANCHOR_VERSION
        )
        .annotate(has_similarities=has_similarities)
        .filter(Q(watch_rank__group__isnull=True) | Q(watch_rank__scores__isnull=True) | Q(has_similarities=False))
    )
    if dry_run:
        return SemanticBackfillResult(observations=pending.count(), assigned=0, named=0)

    anchors = async_to_sync(anchor_vectors)(team_id)
    rows = (
        _Pending(
            observation_id=str(observation_id),
            scanner_id=str(scanner_id),
            created_at=created_at,
            needs_group=group is None,
            needs_scores=scores is None,
            needs_similarities=not has_row,
        )
        for observation_id, scanner_id, created_at, group, scores, has_row in pending.order_by("created_at", "id")
        .values_list("id", "scanner_id", "created_at", "watch_rank__group", "watch_rank__scores", "has_similarities")
        .iterator(chunk_size=_SLICE_ROWS)
    )
    observations = 0
    assigned = 0
    # One slice at a time, so memory stays at one slice of rows however large the team's window is.
    for slice_rows in batched(rows, _SLICE_ROWS, strict=False):
        observations += len(slice_rows)
        assigned += _backfill_slice(team_id, list(slice_rows), anchors)
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
        if row.observation_id in vectors and (row.needs_scores or row.needs_similarities)
    }
    save_anchor_similarities(
        team_id,
        {
            row.observation_id: readings[row.observation_id].similarities
            for row in slice_rows
            if row.needs_similarities and row.observation_id in readings
        },
    )
    merge_watch_ranks(
        team_id,
        {
            row.observation_id: {"scores": readings[row.observation_id].rank.scores}
            for row in slice_rows
            if row.needs_scores and row.observation_id in readings
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
