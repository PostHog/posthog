"""Decide which scheduler runs a schema.

The flag records intent per team. The queue scheduler fires a flagged team's schemas only
while the `WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED` kill switch is on. A later migrate
command removes the Temporal Schedules of the schemas the queue fires.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import InterfaceError, OperationalError

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_schema_flag_enabled

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)

QUEUE_SCHEDULER_FLAG = "warehouse-queue-scheduler"
DEFAULT_CACHE_TTL_SECONDS = 60.0
# Expired entries are only dropped once the cache is this large, so the dict stays bounded.
_PRUNE_THRESHOLD = 1024

# schema id -> (expiry on the monotonic clock, flag value)
_cache: dict[str, tuple[float, bool]] = {}


def uses_queue_scheduler(schema: ExternalDataSchema, *, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    """Return True when the flag routes this schema to the queue scheduler.

    Any failure returns False, so the schema stays on Temporal.
    """
    key = str(schema.id)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        enabled = is_schema_flag_enabled(schema, QUEUE_SCHEDULER_FLAG)
    except Exception:
        logger.warning("queue_scheduler_flag_failed", schema_id=key, exc_info=True)
        return False

    if len(_cache) >= _PRUNE_THRESHOLD:
        for expired in [k for k, (expiry, _) in _cache.items() if expiry <= now]:
            del _cache[expired]
    _cache[key] = (now + ttl_seconds, enabled)
    return enabled


def clear_queue_scheduler_cache() -> None:
    _cache.clear()


def queue_scheduler_firing_enabled() -> bool:
    return bool(settings.WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED)


class TeamQueueOwnership:
    """The teams that the flag routes to the queue scheduler, with one cached answer per team.

    The scheduler asks once per tick for every team with a due schema, so a team costs one
    flag evaluation per TTL, not one per schema. An evaluation that fails counts as not
    routed and is not cached, so the team stays on Temporal and the next tick asks again.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        # team id -> (expiry on the clock, flag value)
        self._cache: dict[int, tuple[float, bool]] = {}

    def owned_teams(self, team_ids: Iterable[int]) -> frozenset[int]:
        now = self._clock()
        requested = set(team_ids)
        answers: dict[int, bool] = {}
        uncached: list[int] = []
        for team_id in requested:
            cached = self._cache.get(team_id)
            if cached is not None and cached[0] > now:
                answers[team_id] = cached[1]
            else:
                uncached.append(team_id)

        for team_id, enabled in _evaluate_team_flags(sorted(uncached)).items():
            if enabled is None:
                continue
            self._cache[team_id] = (now + self._ttl_seconds, enabled)
            answers[team_id] = enabled

        return frozenset(team_id for team_id, enabled in answers.items() if enabled)


def _evaluate_team_flags(team_ids: list[int]) -> dict[int, bool | None]:
    """The flag value per team. None means the evaluation failed."""
    if not team_ids:
        return {}
    try:
        teams = {
            team_id: (team_uuid, organization_id)
            for team_id, team_uuid, organization_id in Team.objects.filter(id__in=team_ids).values_list(
                "id", "uuid", "organization_id"
            )
        }
    except (OperationalError, InterfaceError) as e:
        logger.warning("queue_scheduler_team_lookup_failed", team_count=len(team_ids), exc_info=True)
        capture_exception(e)
        return dict.fromkeys(team_ids)

    results: dict[int, bool | None] = {}
    for team_id in team_ids:
        if team_id not in teams:
            results[team_id] = False
            continue
        team_uuid, organization_id = teams[team_id]
        try:
            results[team_id] = bool(
                posthoganalytics.feature_enabled(
                    QUEUE_SCHEDULER_FLAG,
                    str(team_uuid),
                    groups={"organization": str(organization_id), "project": str(team_id)},
                    person_properties={"team_id": str(team_id)},
                    group_properties={
                        "organization": {"id": str(organization_id)},
                        "project": {"id": str(team_id)},
                    },
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception as e:
            logger.warning("queue_scheduler_flag_failed", team_id=team_id, exc_info=True)
            capture_exception(e)
            results[team_id] = None
    return results
