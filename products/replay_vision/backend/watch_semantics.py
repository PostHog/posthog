"""Places each ranked observation in a feed group and, when it qualifies, a search theme.

Every ranked row gets a group, not only issues, so a viewer who counts different anchors as issues finds those rows
already grouped.

The embedding consumer and the semantics backfill both call `assign_semantics`. It locks the scanner's semantic
centre for the whole assignment, so two observations of one scanner never race on its clusters, and writes both ids
to the observation's rank in one update, so a redelivered message finds them already there.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import F, Func, JSONField, Value

import numpy as np

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import PromptValence, ReplayScanner, ScannerType
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
    ReplayScannerSemanticCenter,
)
from products.replay_vision.backend.semantic_space import (
    SEMANTIC_DIMENSIONS,
    pack,
    scanner_space,
    semantic_vector,
    unpack,
)
from products.replay_vision.backend.watch_feed_groups import feed_group_cache
from products.replay_vision.backend.watch_rank import current_rank
from products.replay_vision.backend.watch_themes import ThemeAssignment, assign_theme, belongs_in_theme

# Clusters with no member for this long are deleted, since the feed's longest window no longer reaches them.
SEMANTIC_RETENTION = timedelta(days=90)
# Pruning runs on one in this many assignments of a scanner, which keeps it rare and still bounds the tables.
_PRUNE_EVERY = 500


@frozen
class SemanticAssignment:
    group_id: uuid.UUID
    theme: ThemeAssignment | None


def assign_semantics(
    *, team_id: int, scanner_id: str, observation_id: str, vector: list[float], now: datetime
) -> SemanticAssignment | None:
    """None when the observation has no current rank, already has its clusters, or is gone."""
    scanner = (
        ReplayScanner.objects.filter(team_id=team_id, id=scanner_id)
        .values("scanner_type", "prompt_valence", "scanner_config")
        .first()
    )
    if scanner is None:
        return None
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
            row = (
                ReplayObservation.objects.filter(team_id=team_id, id=observation_id)
                .values("watch_rank", "scanner_result", "scanner_snapshot")
                .first()
            )
            if row is None:
                return None
            rank = current_rank({"watch_rank": row["watch_rank"]})
            if rank is None or rank.get("group"):
                return None

            v = semantic_vector(vector)
            center_sum = unpack(center.vector_sum)
            space = scanner_space(center_sum, center.member_count, v)
            group_id = feed_group_cache.assign(
                team_id=team_id, scanner_id=scanner_id, space=space, version=center.member_count, now=now
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
                    category=rank["category"],
                    scanner_type=scanner["scanner_type"],
                    valence=scanner["prompt_valence"],
                    output=output,
                )
            ):
                theme = assign_theme(team_id=team_id, scanner_id=scanner_id, space=space, now=now)

            center.vector_sum = pack(center_sum + v)
            center.member_count += 1
            center.save(update_fields=["vector_sum", "member_count"])
            if center.member_count % _PRUNE_EVERY == 0:
                _prune(team_id, scanner_id, now)

            merge_watch_rank(
                team_id, observation_id, {"group": str(group_id)} | ({"theme": str(theme.theme_id)} if theme else {})
            )
    except Exception:
        feed_group_cache.forget(scanner_id)
        raise
    return SemanticAssignment(group_id=group_id, theme=theme)


def merge_watch_rank(team_id: int, observation_id: str, keys: dict[str, Any]) -> None:
    """Add keys to an observation's rank without rewriting what another writer put there."""
    ReplayObservation.objects.filter(team_id=team_id, id=observation_id).update(
        watch_rank=Func(
            F("watch_rank"),
            Value(keys, output_field=JSONField()),
            template="%(expressions)s",
            arg_joiner=" || ",
            output_field=JSONField(),
        )
    )


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
