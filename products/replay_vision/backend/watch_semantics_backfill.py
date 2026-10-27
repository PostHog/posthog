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
    rows = (
        ReplayObservation.objects.filter(
            team_id=team_id, status="succeeded", created_at__gte=since, watch_rank__anchor_version=ANCHOR_VERSION
        )
        .alias(has_similarities=has_similarities)
        .filter(Q(watch_rank__group__isnull=True) | Q(watch_rank__scores__isnull=True) | Q(has_similarities=False))
        .order_by("scanner_id", "created_at")
        .values_list("id", "scanner_id", "created_at")
    )
    by_scanner: dict[str, list[tuple[str, datetime]]] = {}
    for observation_id, scanner_id, created_at in rows.iterator(chunk_size=2_000):
        by_scanner.setdefault(str(scanner_id), []).append((str(observation_id), created_at))
    observations = sum(len(scanner_rows) for scanner_rows in by_scanner.values())
    if dry_run:
        return SemanticBackfillResult(observations=observations, assigned=0, named=0)

    anchors = async_to_sync(anchor_vectors)(team_id)
    assigned = 0
    for scanner_id, scanner_rows in by_scanner.items():
        for start in range(0, len(scanner_rows), _VECTOR_CHUNK):
            chunk = scanner_rows[start : start + _VECTOR_CHUNK]
            vectors = _stored_vectors(team_id, scanner_id, [observation_id for observation_id, _ in chunk], since)
            readings = {observation_id: classify(vector, anchors) for observation_id, vector in vectors.items()}
            save_anchor_similarities(
                team_id, {observation_id: reading.similarities for observation_id, reading in readings.items()}
            )
            for observation_id, created_at in chunk:
                vector = vectors.get(observation_id)
                if vector is None:
                    continue
                merge_watch_rank(team_id, observation_id, {"scores": readings[observation_id].rank.scores})
                assignment = assign_semantics(
                    team_id=team_id,
                    scanner_id=scanner_id,
                    observation_id=observation_id,
                    vector=vector.tolist(),
                    now=created_at,
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
