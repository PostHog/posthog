"""Deciding which destinations a run delivers to.

Resolution happens once, when the run's job is created, and the resulting ids travel with
every batch. A destination added or removed mid-run therefore cannot change where an
in-flight run's remaining batches land, and cannot change what the run bills.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    resolve_destinations,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

WAREHOUSE_MULTI_DESTINATION_FLAG = "warehouse-multi-destination"


def is_multi_destination_enabled(team_id: int, source_type: str) -> bool:
    """Whether this team's syncs of this source type deliver to configured destinations.

    Evaluated in an activity and carried into the workflow as recorded history — a workflow must
    never read a flag directly.
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
    """Every destination id this run writes to, the PostHog warehouse included, in a stable order.

    The warehouse is a destination like any other, so a run that writes there says so rather
    than recording nothing. Readers that still receive an empty list — a job that predates
    destinations, a CDC companion lane, a run of a team the flag is off for — keep reading it
    as the warehouse alone, which is what `warehouse_is_a_destination` does.

    This list is the run's whole destination set. Anything that needs the external subset asks
    `external_destination_ids_for` for it rather than reading "non-empty" as "has external
    destinations": the warehouse is delivered through delta, not through a destination writer.
    """
    return sorted(str(destination.id) for destination in resolve_destinations(schema))


def external_destination_ids_for(team_id: int, destination_ids: Sequence[str]) -> list[str]:
    """The subset of `destination_ids` a destination writer delivers, so without the warehouse.

    Resolved once per run and carried on each batch, because the consumer reads it per batch
    while deciding what may share a write, and a query there would run for every batch in the
    fleet.
    """
    if not destination_ids:
        return []

    return sorted(
        str(destination.id)
        for destination in ExternalDataDestination.objects.for_team(team_id).filter(id__in=list(destination_ids))
        if destination.type != ExternalDataDestination.Type.POSTHOG_WAREHOUSE
    )
