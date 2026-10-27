"""Builds feed groups and search themes from observations ranked before the consumer assigned them, so the feed and
the suggestions start from history instead of an empty slate."""

from datetime import datetime

from django.db.models import F
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner_semantics import ReplayScannerSearchTheme
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION, ISSUE_CATEGORIES
from products.replay_vision.backend.watch_rank_backfill import _VECTOR_CHUNK, _stored_vectors
from products.replay_vision.backend.watch_semantics import assign_semantics
from products.replay_vision.backend.watch_themes import THEME_ACTIVE_WINDOW, name_theme

logger = structlog.get_logger(__name__)


@frozen
class SemanticBackfillResult:
    observations: int
    assigned: int
    named: int


def backfill_team_semantics(team_id: int, since: datetime, *, dry_run: bool = False) -> SemanticBackfillResult:
    """Replay a team's ranked issue observations oldest first, as the consumer would have seen them, then name
    every active theme that reached its naming size."""
    rows = (
        ReplayObservation.objects.filter(
            team_id=team_id,
            status="succeeded",
            created_at__gte=since,
            watch_rank__anchor_version=ANCHOR_VERSION,
            watch_rank__group__isnull=True,
        )
        .alias(category=KeyTextTransform("category", "watch_rank"))
        .filter(category__in=ISSUE_CATEGORIES)
        .order_by("scanner_id", "created_at")
        .values_list("id", "scanner_id", "created_at")
    )
    by_scanner: dict[str, list[tuple[str, datetime]]] = {}
    for observation_id, scanner_id, created_at in rows.iterator(chunk_size=2_000):
        by_scanner.setdefault(str(scanner_id), []).append((str(observation_id), created_at))
    observations = sum(len(scanner_rows) for scanner_rows in by_scanner.values())
    if dry_run:
        return SemanticBackfillResult(observations=observations, assigned=0, named=0)

    assigned = 0
    for scanner_id, scanner_rows in by_scanner.items():
        for start in range(0, len(scanner_rows), _VECTOR_CHUNK):
            chunk = scanner_rows[start : start + _VECTOR_CHUNK]
            vectors = _stored_vectors(team_id, scanner_id, [observation_id for observation_id, _ in chunk], since)
            for observation_id, created_at in chunk:
                vector = vectors.get(observation_id)
                if vector is None:
                    continue
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
