"""Places each ranked observation in a feed group and, when it qualifies, a search theme.

Every ranked row gets a group, not only issues, so a viewer who counts different anchors as issues finds those rows
already grouped.

The embedding consumer assigns one observation per message, and the semantics backfill assigns a scanner's rows in
chunks, both through `assign_semantics_batch`. It locks the scanner's semantic centre for the whole chunk, so two
writers never race on its clusters, and writes both ids to each observation's rank row in the same transaction, so a
redelivered message finds them already there.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction

import numpy as np

from posthog.dataclasses import frozen

from products.replay_vision.backend.highlight_feed_groups import feed_group_cache
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import PromptValence, ScannerType
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
    ReplayScannerSemanticCenter,
)
from products.replay_vision.backend.observation_ranks import CATEGORY_NAMES, set_rank_clusters
from products.replay_vision.backend.scanner_access import scanners_for_reading_observations
from products.replay_vision.backend.semantic_space import (
    SEMANTIC_DIMENSIONS,
    ClusterWrites,
    pack,
    scanner_space,
    semantic_vector,
    unpack,
)
from products.replay_vision.backend.watch_rank import current_ranks
from products.replay_vision.backend.watch_themes import ThemeAssignment, ThemeBatch, belongs_in_theme

# Clusters with no member for this long are deleted, since the feed's longest window no longer reaches them.
SEMANTIC_RETENTION = timedelta(days=90)
# Pruning runs on one in this many assignments of a scanner, which keeps it rare and still bounds the tables.
_PRUNE_EVERY = 500


@frozen
class SemanticAssignment:
    group_id: uuid.UUID
    theme: ThemeAssignment | None


@frozen
class SemanticItem:
    observation_id: str
    vector: list[float] | np.ndarray
    now: datetime


def assign_semantics(
    *, team_id: int, scanner_id: str, observation_id: str, vector: list[float], now: datetime
) -> SemanticAssignment | None:
    """None when the observation has no current rank, already has its clusters, or is gone."""
    assigned = assign_semantics_batch(
        team_id=team_id,
        scanner_id=scanner_id,
        items=[SemanticItem(observation_id=observation_id, vector=vector, now=now)],
    )
    return assigned.get(observation_id)


def assign_semantics_batch(
    *, team_id: int, scanner_id: str, items: Sequence[SemanticItem]
) -> dict[str, SemanticAssignment]:
    """Assign one scanner's observations oldest first under a single centre lock, with one write per table, keyed by
    observation id. An observation with no current rank, with its clusters already, or gone is left out."""
    scanner = (
        # Inline scans group and theme like configured scanners, so a question asked often enough becomes a theme.
        scanners_for_reading_observations(team_id)
        .filter(id=scanner_id)
        .values("scanner_type", "prompt_valence", "scanner_config")
        .first()
    )
    if scanner is None or not items:
        return {}
    assigned: dict[str, SemanticAssignment] = {}
    try:
        with transaction.atomic():
            center, _ = (
                ReplayScannerSemanticCenter.objects.for_team(team_id)
                .select_for_update()
                .get_or_create(
                    scanner_id=scanner_id,
                    defaults={"team_id": team_id, "vector_sum": pack(np.zeros(SEMANTIC_DIMENSIONS, dtype=np.float32))},
                )
            )
            keys = [_as_uuid(item.observation_id) for item in items]
            ids = [key for key in keys if key]
            rows = {
                row["id"]: row
                for row in ReplayObservation.objects.filter(team_id=team_id, id__in=ids).values(
                    "id", "scanner_result", "scanner_snapshot"
                )
            }
            ranks = dict(
                current_ranks(team_id)
                .filter(observation_id__in=ids, feed_group_id__isnull=True)
                .values_list("observation_id", "category")
            )
            center_sum = unpack(center.vector_sum).copy()
            member_count = center.member_count
            group_writes = ClusterWrites(ReplayScannerFeedGroup, team_id, scanner_id)
            themes: ThemeBatch | None = None
            for item, key in zip(items, keys):
                row = rows.get(key) if key else None
                # Only a ranked row without a group yet takes one, so a redelivered message changes nothing.
                category = CATEGORY_NAMES.get(ranks.get(key, 0)) if key else None
                if row is None or category is None:
                    continue
                v = semantic_vector(item.vector)
                space = scanner_space(center_sum, member_count, v)
                group_id = feed_group_cache.assign(
                    team_id=team_id,
                    scanner_id=scanner_id,
                    space=space,
                    version=member_count,
                    now=item.now,
                    writes=group_writes,
                )
                theme = None
                output = (row["scanner_result"] or {}).get("model_output") or {}
                # A theme name surfaces as a suggestion to anyone who can read the scanner, so an observation scanned
                # under experiment targeting, which only that experiment's viewers may read, never joins one.
                if (
                    not _experiment_scoped(row["scanner_snapshot"])
                    and not _valence_unknown_for_row(
                        scanner["scanner_type"],
                        scanner["prompt_valence"],
                        scanner["scanner_config"],
                        row["scanner_snapshot"],
                    )
                    and belongs_in_theme(
                        category=category,
                        scanner_type=scanner["scanner_type"],
                        valence=scanner["prompt_valence"],
                        output=output,
                    )
                ):
                    themes = themes or ThemeBatch(team_id, scanner_id, item.now)
                    theme = themes.assign(space, item.now)
                center_sum += v
                member_count += 1
                assigned[item.observation_id] = SemanticAssignment(group_id=group_id, theme=theme)

            if not assigned:
                return {}
            group_writes.save()
            if themes:
                themes.save()
            pruning_due = member_count // _PRUNE_EVERY > center.member_count // _PRUNE_EVERY
            center.vector_sum = pack(center_sum)
            center.member_count = member_count
            center.save(update_fields=["vector_sum", "member_count"])
            if pruning_due:
                _prune(team_id, scanner_id, items[-1].now)
            set_rank_clusters(
                team_id,
                {
                    observation_id: (assignment.group_id, assignment.theme.theme_id if assignment.theme else None)
                    for observation_id, assignment in assigned.items()
                },
            )
    except Exception:
        feed_group_cache.forget(scanner_id)
        raise
    return assigned


def _as_uuid(observation_id: str) -> uuid.UUID | None:
    # A message's document id is an unchecked string, so its spelling may differ from the UUID Postgres returns.
    try:
        return uuid.UUID(observation_id)
    except ValueError:
        return None


def _valence_unknown_for_row(
    scanner_type: str, valence: str, scanner_config: dict[str, Any] | None, snapshot: dict[str, Any] | None
) -> bool:
    """A monitor's current valence describes its current prompt, so a row scanned under another prompt may answer a
    question of the opposite sense and stays out of themes."""
    if scanner_type != ScannerType.MONITOR or valence not in (PromptValence.GOOD, PromptValence.BAD):
        return False
    scanned_prompt = ((snapshot or {}).get("scanner_config") or {}).get("prompt")
    return scanned_prompt != (scanner_config or {}).get("prompt")


def _experiment_scoped(snapshot: dict[str, Any] | None) -> bool:
    snapshot = snapshot or {}
    targeting = snapshot.get("experiment_targeting") or {}
    config = snapshot.get("scanner_config") or {}
    return bool(targeting.get("experiment_id") or config.get("experiment_id"))


def _prune(team_id: int, scanner_id: str, now: datetime) -> None:
    cutoff = now - SEMANTIC_RETENTION
    ReplayScannerFeedGroup.objects.for_team(team_id).filter(scanner_id=scanner_id, last_member_at__lt=cutoff).delete()
    ReplayScannerSearchTheme.objects.for_team(team_id).filter(scanner_id=scanner_id, last_member_at__lt=cutoff).delete()
