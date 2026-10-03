"""Deciding which destinations a run delivers to.

Resolution happens once, when the run's job is created, and the resulting ids travel with
every batch. A destination added or removed mid-run therefore cannot change where an
in-flight run's remaining batches land, and cannot change what the run bills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.warehouse_sources.backend.models.external_data_destination import resolve_destinations

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

WAREHOUSE_MULTI_DESTINATION_FLAG = "warehouse-multi-destination"


def is_multi_destination_enabled(team_id: int, source_type: str) -> bool:
    """Whether this team's syncs of this source type deliver to configured destinations.

    Evaluated in an activity and carried into the workflow as recorded history, the same way
    the v3 rollout flag is — a workflow must never read a flag directly.
    """
    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_MULTI_DESTINATION_FLAG,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id), "source_type": source_type},
                    "project": {"id": str(team.id), "source_type": source_type},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


def destination_ids_for_run(schema: ExternalDataSchema) -> list[str]:
    """The destination ids this run delivers to, in a stable order.

    Empty when the schema resolves to the PostHog warehouse alone, which keeps a run that
    nobody configured destinations for byte-for-byte on the path it took before.
    """
    destinations = resolve_destinations(schema)
    if len(destinations) == 1 and destinations[0].is_posthog_warehouse:
        return []

    return sorted(str(destination.id) for destination in destinations)
