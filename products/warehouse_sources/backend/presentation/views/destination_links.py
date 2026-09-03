"""Setting which destinations a source or one of its tables syncs to.

Kept out of the source and schema viewsets so the destination set is edited through one
shared, tested path rather than two near-copies.
"""

from typing import Any

from django.db import transaction

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.warehouse_sources.backend.facade.models import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
)

EMPTY_SET_MESSAGE = (
    "Pick at least one destination. To stop syncing this data, turn off syncing instead of removing every destination."
)

# The delivery loop writes a batch to every selected destination in turn, so an unbounded set
# would let one source or table tie up a consumer for as long as it takes to reach every one of
# them. A source realistically syncs to a small number of downstream warehouses.
MAX_DESTINATIONS_PER_LINK = 10
TOO_MANY_DESTINATIONS_MESSAGE = f"Pick at most {MAX_DESTINATIONS_PER_LINK} destinations."


class SourceDestinationsSerializer(serializers.Serializer):
    """Response shape for a source's destination set."""

    destination_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Destinations every table on this source syncs to."
    )


class SchemaDestinationsSerializer(serializers.Serializer):
    """Response shape for a table's destination override."""

    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_null=True,
        help_text="The table's own destinations, or null when it follows its source.",
    )
    inherits_from_source = serializers.BooleanField(
        help_text="Whether this table follows its source rather than having its own destinations."
    )
    effective_destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Where the table actually syncs, after inheritance is resolved.",
    )


class DestinationLinkSerializer(serializers.Serializer):
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        allow_null=True,
        help_text=(
            "Destinations to sync to. On a table, null clears the override so the table follows its source again."
        ),
    )


def _resolve_destinations(team_id: int, destination_ids: list) -> list[ExternalDataDestination]:
    if len(destination_ids) > MAX_DESTINATIONS_PER_LINK:
        raise ValidationError({"destination_ids": TOO_MANY_DESTINATIONS_MESSAGE})

    destinations = list(
        ExternalDataDestination.objects.for_team(team_id).filter(id__in=destination_ids).exclude(deleted=True)
    )
    missing = {str(i) for i in destination_ids} - {str(d.id) for d in destinations}
    if missing:
        raise ValidationError({"destination_ids": f"Unknown destinations: {', '.join(sorted(missing))}"})
    return destinations


def set_source_destinations(*, team_id: int, source_id: Any, destination_ids: list | None) -> list[str]:
    """Replace a source's destination set. Returns the ids now attached."""
    if not destination_ids:
        raise ValidationError({"destination_ids": EMPTY_SET_MESSAGE})

    destinations = _resolve_destinations(team_id, destination_ids)

    # Atomic because the delete and the creates are one edit: a failure between them would leave
    # the source with a partial set, and every table without an override would sync to it.
    with transaction.atomic():
        ExternalDataSourceDestination.objects.for_team(team_id).filter(source_id=source_id).delete()
        for destination in destinations:
            ExternalDataSourceDestination.objects.for_team(team_id).create(
                team_id=team_id, source_id=source_id, destination=destination
            )
    return [str(d.id) for d in destinations]


def set_schema_destinations(*, team_id: int, schema_id: Any, destination_ids: list | None) -> list[str] | None:
    """Replace a table's destination override, or clear it so the table follows its source.

    Null clears the override. An empty list is rejected rather than treated as "sync nowhere":
    with no rows left there is nothing to distinguish it from having no override, so the table
    would quietly fall back to its source's destinations. Turning syncing off is the supported
    way to stop a table.
    """
    if destination_ids is not None and not destination_ids:
        raise ValidationError({"destination_ids": EMPTY_SET_MESSAGE})

    # Resolved before anything is deleted. There are no `ATOMIC_REQUESTS` here, so a rejection
    # after the delete would commit it, and the table would silently fall back to its source's
    # destinations on a request that returned 400.
    destinations = [] if destination_ids is None else _resolve_destinations(team_id, destination_ids)

    with transaction.atomic():
        ExternalDataSchemaDestination.objects.for_team(team_id).filter(schema_id=schema_id).delete()

        if destination_ids is None:
            return None

        for destination in destinations:
            ExternalDataSchemaDestination.objects.for_team(team_id).create(
                team_id=team_id, schema_id=schema_id, destination=destination
            )
    return [str(d.id) for d in destinations]
