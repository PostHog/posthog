"""Deciding which destinations a run delivers to.

Resolution happens once, when the run's job is created, and the resulting ids travel with
every batch. A destination added or removed mid-run therefore cannot change where an
in-flight run's remaining batches land, and cannot change what the run bills.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    resolve_destinations,
)
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_schema_flag_enabled

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

WAREHOUSE_MULTI_DESTINATION_FLAG = "warehouse-multi-destination"

# Turns on the destinations-only run mode for a schema whose destination set has no PostHog warehouse.
DESTINATIONS_ONLY_RUNS_FLAG = "warehouse-destinations-only-runs"

# The `ExternalDataJob.schema_snapshot` key that marks a destinations-only run.
DESTINATIONS_ONLY_SNAPSHOT_KEY = "destinations_only"

NO_ACTIVE_DESTINATIONS_MESSAGE = (
    "Every destination this table syncs to is paused, so this sync did not run. "
    "Fix the destination, then edit it to turn it back on."
)


class NoActiveDestinationsError(Exception):
    """Every link of the schema is off, so the run has nowhere to deliver."""


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
    Raises `NoActiveDestinationsError` when the schema has links but every one of them is off.
    """
    destinations = resolve_destinations(schema)
    if not destinations:
        raise NoActiveDestinationsError(NO_ACTIVE_DESTINATIONS_MESSAGE)

    return sorted(str(destination.id) for destination in destinations)


@frozen
class RunDestinations:
    """A run's destination set, split into the PostHog warehouse and the external destinations."""

    external_ids: tuple[str, ...]
    writes_warehouse: bool


def run_destinations(team_id: int, destination_ids: Sequence[str]) -> RunDestinations:
    """Split the run's destination set with one query.

    `writes_warehouse` gives the same answer as the loader's `warehouse_is_a_destination`. An
    empty set is the warehouse alone, and a deleted warehouse row does not count.
    """
    if not destination_ids:
        return RunDestinations(external_ids=(), writes_warehouse=True)

    destinations = list(ExternalDataDestination.objects.for_team(team_id).filter(id__in=list(destination_ids)))
    return RunDestinations(
        external_ids=tuple(
            sorted(
                str(destination.id)
                for destination in destinations
                if destination.type != ExternalDataDestination.Type.POSTHOG_WAREHOUSE
            )
        ),
        writes_warehouse=any(
            destination.is_posthog_warehouse and not destination.deleted for destination in destinations
        ),
    )


def is_destinations_only_run(schema: ExternalDataSchema, destination_ids: Sequence[str]) -> bool:
    """Whether a new run of this schema delivers to external destinations and never writes the warehouse.

    Decided once, when the run's job is created, and recorded on the job's schema snapshot. A
    destinations-only run skips all the work that needs a Delta table: the Delta write and its
    maintenance, the repartition, the table registration and the post-import steps that read the
    table. The flag is read only when the set has no warehouse, so every other run pays nothing.

    A CDC schema never qualifies: its history lane writes a `_cdc` table to the warehouse.
    """
    if schema.is_cdc or not destination_ids:
        return False
    if run_destinations(schema.team_id, destination_ids).writes_warehouse:
        return False
    return is_schema_flag_enabled(schema, DESTINATIONS_ONLY_RUNS_FLAG)


def is_destinations_only_snapshot(schema_snapshot: Mapping[str, Any] | None) -> bool:
    """Whether a job's schema snapshot marks a destinations-only run."""
    return schema_snapshot is not None and schema_snapshot.get(DESTINATIONS_ONLY_SNAPSHOT_KEY) is True


def external_destination_ids_for(team_id: int, destination_ids: Sequence[str]) -> list[str]:
    """The subset of `destination_ids` a destination writer delivers, so without the warehouse.

    Resolved once per run and carried on each batch, because the consumer reads it per batch
    while deciding what may share a write, and a query there would run for every batch in the
    fleet.
    """
    return list(run_destinations(team_id, destination_ids).external_ids)
