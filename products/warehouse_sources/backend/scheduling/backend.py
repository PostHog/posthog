"""Decide which scheduler runs a schema.

The `warehouse-queue-scheduler` flag records intent per team. It is evaluated per team, with the
team as the distinct id and its organization and project as groups, so a release condition on a
schema property does not apply. The queue scheduler fires a flagged team's schemas only while the
`WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED` kill switch is on. A later migrate command removes the
Temporal Schedules of the schemas the queue fires.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import batched

from django.conf import settings

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

QUEUE_SCHEDULER_FLAG = "warehouse-queue-scheduler"
_TEAM_LOOKUP_BATCH_SIZE = 1000


def queue_scheduler_firing_enabled() -> bool:
    return bool(settings.WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED)


def team_uses_queue_scheduler(team_id: int, team_uuid: str, organization_id: str) -> bool:
    """Whether the flag routes this team to the queue scheduler.

    Evaluated locally, so a scheduler tick never waits on the flags service. A flag that cannot be
    evaluated locally, and any error, count as off: the team stays on Temporal.
    """
    try:
        return feature_enabled_or_false(
            QUEUE_SCHEDULER_FLAG,
            team_uuid,
            groups={"organization": organization_id, "project": str(team_id)},
            person_properties={"team_id": str(team_id)},
            group_properties={
                "organization": {"id": organization_id},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as e:
        logger.warning("queue_scheduler_flag_failed", team_id=team_id, exc_info=True)
        capture_exception(e)
        return False


def queue_scheduler_teams(team_ids: Iterable[int]) -> frozenset[int]:
    """The teams of `team_ids` that the flag routes to the queue scheduler.

    A team that no longer exists is not routed. A database error propagates, so the caller can
    count the whole answer as "no team fires".
    """
    routed: set[int] = set()
    for chunk in batched(sorted(set(team_ids)), _TEAM_LOOKUP_BATCH_SIZE, strict=False):
        teams = Team.objects.filter(id__in=chunk).values_list("id", "uuid", "organization_id")
        for team_id, team_uuid, organization_id in teams:
            if team_uses_queue_scheduler(team_id, str(team_uuid), str(organization_id)):
                routed.add(team_id)
    return frozenset(routed)
