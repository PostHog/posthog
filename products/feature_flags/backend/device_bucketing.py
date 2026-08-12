"""Resolving the ``$device_id`` that device-bucketed flags hash on.

A device-bucketed flag hashes on ``$device_id`` instead of ``distinct_id``, so that its
value stays stable across the anonymous-to-identified transition (see
https://posthog.com/docs/feature-flags/device-bucketing). SDKs send ``$device_id`` on
every ``/flags`` call, so live evaluation works.

PostHog's own debug surfaces don't send one: the person profile flags tab and a flag's
test evaluation tab both know only a distinct id. The evaluation engine skips a
person-aggregated device-bucketed condition when no device id is supplied and reports
``out_of_rollout_bound``, which reads as "this person isn't in the rollout" when the truth
is that we never told the engine which device to hash. At 100% rollout that is actively
misleading, because being out of the rollout bound is impossible there.

``$device_id`` is not a person property, because one person can have many device ids, so
it has to be read back off the person's events.
"""

from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team

from .models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

DEVICE_ID_PROPERTY = "$device_id"

# Bounded because an unbounded events scan on a UI request is expensive, and a device id
# older than this is unlikely to be the one the person buckets on now.
DEVICE_ID_LOOKBACK_DAYS = 90


def has_device_bucketed_flags(project_id: int, flag_keys: list[str] | None = None) -> bool:
    """Whether any flag in scope buckets by device, so callers can skip the events query
    entirely on the projects that have none."""
    queryset = FeatureFlag.objects.filter(
        team__project_id=project_id,
        bucketing_identifier="device_id",
        active=True,
        deleted=False,
    )
    if flag_keys:
        queryset = queryset.filter(key__in=flag_keys)
    return queryset.exists()


def resolve_device_id(team: Team, distinct_id: str, before: datetime | None = None) -> str | None:
    """The most recent ``$device_id`` seen on this distinct id's events, or None.

    Resolution is per distinct id rather than per person. ``$device_id`` is stable across
    the identify boundary for a given browser, so the anonymous and identified distinct ids
    of one person normally carry the same device id and the two are equivalent, but scoping
    to the distinct id keeps the answer specific to the identity being evaluated and keeps
    the query on an indexed column.

    Two cases legitimately return None: a person on several devices still resolves to only
    their most recent one, and a distinct id with no client-side events (a server-only
    identity, say) has no device id to find. Treat None as "device bucketing can't be
    resolved for this identity" rather than as an error.

    ``before`` bounds the lookup for point-in-time evaluation, so a historical
    reconstruction hashes on the device the person used then rather than the one they use now.
    """
    until = before or timezone.now()
    since = until - timedelta(days=DEVICE_ID_LOOKBACK_DAYS)

    # properties[...] rather than properties.$device_id so the property name stays a bound
    # constant, and so the printer can use a materialized column where one exists.
    query = """
        SELECT properties[{device_id_property}] AS device_id
        FROM events
        WHERE distinct_id = {distinct_id}
          AND timestamp >= {since}
          AND timestamp <= {until}
          AND properties[{device_id_property}] IS NOT NULL
          AND properties[{device_id_property}] != ''
        ORDER BY timestamp DESC
        LIMIT 1
    """

    try:
        response = execute_hogql_query(
            query,
            placeholders={
                "device_id_property": ast.Constant(value=DEVICE_ID_PROPERTY),
                "distinct_id": ast.Constant(value=distinct_id),
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
            },
            team=team,
        )
    except Exception:
        # A debug surface that degrades to "no device id" beats one that 500s, so the
        # caller still renders, just without device bucketing resolved.
        logger.exception(
            "Failed to resolve $device_id for device-bucketed flag evaluation",
            team_id=team.pk,
        )
        return None

    if not response.results:
        return None

    return response.results[0][0] or None
