"""Brings observations ranked before the consumer wrote everything it writes today up to date: category scores,
anchor similarities, feed groups and search themes, so the feed and the suggestions start from history."""

from datetime import datetime

from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.models.replay_scanner_semantics import ReplayScannerSearchTheme
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION, anchor_vectors, classify, save_anchor_similarities
from products.replay_vision.backend.watch_rank_backfill import _VECTOR_CHUNK, _stored_vectors
from products.replay_vision.backend.watch_semantics import assign_semantics, merge_watch_rank
from products.replay_vision.backend.watch_themes import THEME_ACTIVE_WINDOW, name_theme

logger = structlog.get_logger(__name__)


@frozen
class _Pending:
    observation_id: str
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
    """Replay a team's ranked observations oldest first, as the consumer would have seen them, then name every
    active theme that reached its naming size."""
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
    scanner_ids = [str(scanner_id) for scanner_id in pending.values_list("scanner_id", flat=True).distinct()]
    if dry_run:
        return SemanticBackfillResult(observations=pending.count(), assigned=0, named=0)

    anchors = async_to_sync(anchor_vectors)(team_id)
    observations = 0
    assigned = 0
    # One scanner at a time, so memory stays at one scanner's pending rows however large the team's window is.
    for scanner_id in scanner_ids:
        scanner_rows = [
            _Pending(
                observation_id=str(observation_id),
                created_at=created_at,
                needs_group=not (rank or {}).get("group"),
                needs_scores=(rank or {}).get("scores") is None,
                needs_similarities=not has_row,
            )
            for observation_id, created_at, rank, has_row in pending.filter(scanner_id=scanner_id)
            .order_by("created_at")
            .values_list("id", "created_at", "watch_rank", "has_similarities")
            .iterator(chunk_size=2_000)
        ]
        observations += len(scanner_rows)
        for start in range(0, len(scanner_rows), _VECTOR_CHUNK):
            chunk = scanner_rows[start : start + _VECTOR_CHUNK]
            vectors = _stored_vectors(team_id, scanner_id, [row.observation_id for row in chunk], since)
            readings = {
                row.observation_id: classify(vectors[row.observation_id], anchors)
                for row in chunk
                if row.observation_id in vectors and (row.needs_scores or row.needs_similarities)
            }
            save_anchor_similarities(
                team_id,
                {
                    row.observation_id: readings[row.observation_id].similarities
                    for row in chunk
                    if row.needs_similarities and row.observation_id in readings
                },
            )
            for row in chunk:
                vector = vectors.get(row.observation_id)
                if vector is None:
                    continue
                if row.needs_scores:
                    merge_watch_rank(team_id, row.observation_id, {"scores": readings[row.observation_id].rank.scores})
                if row.needs_group:
                    assignment = assign_semantics(
                        team_id=team_id,
                        scanner_id=scanner_id,
                        observation_id=row.observation_id,
                        vector=vector.tolist(),
                        now=row.created_at,
                    )
                    assigned += assignment is not None

    named = 0
    now = timezone.now()
    due = (
        ReplayScannerSearchTheme.objects.for_team(team_id)
        .filter(member_count__gte=F("rename_at_member_count"), last_member_at__gte=now - THEME_ACTIVE_WINDOW)
        .order_by("-member_count")
        .values_list("id", flat=True)
    )
    for theme_id in list(due):
        try:
            named += async_to_sync(name_theme)(team_id, theme_id, now) is not None
        except Exception:
            logger.exception("replay_vision.watch_semantics_backfill.naming_failed", team_id=team_id)
    return SemanticBackfillResult(observations=observations, assigned=assigned, named=named)
