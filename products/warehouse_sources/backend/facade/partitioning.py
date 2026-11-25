"""Partitioning policy, repartition history and "repartition now" for the schema API."""

from uuid import UUID

from products.warehouse_sources.backend.facade.contracts import RepartitionRequest
from products.warehouse_sources.backend.logic import partitioning as _logic
from products.warehouse_sources.backend.logic.partitioning import (
    PartitioningHistory,
    RepartitionHistoryEntry,
    RepartitionOutcome,
    RepartitionTrigger,
    partitioning_controls_enabled_for_team,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def partitioning_history(team_id: int, schema_id: UUID) -> PartitioningHistory:
    """The table's repartitions, newest first, and its sync stats for each layout it had."""
    schema = ExternalDataSchema.objects.get(id=schema_id, team_id=team_id)
    return _logic.partitioning_history(schema)


def stage_repartition(
    team_id: int,
    schema_id: UUID,
    request: RepartitionRequest,
    *,
    trigger_reason: RepartitionTrigger,
    requested_by_id: int | None = None,
) -> RepartitionOutcome:
    """Validate a chosen scheme, stage it, and start one run that rewrites the table."""
    schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id, team_id=team_id)
    return _logic.stage_repartition(schema, request, trigger_reason=trigger_reason, requested_by_id=requested_by_id)


__all__ = [
    "PartitioningHistory",
    "RepartitionHistoryEntry",
    "RepartitionOutcome",
    "partitioning_controls_enabled_for_team",
    "partitioning_history",
    "stage_repartition",
]
