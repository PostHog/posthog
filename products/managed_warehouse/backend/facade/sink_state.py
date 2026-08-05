from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from django.db.models import Model

from products.managed_warehouse.backend import sink_state
from products.managed_warehouse.backend.facade.contracts import (
    DuckgresSinkBackfillPlanInput,
    DuckgresSinkBackfillRunReference,
    DuckgresSinkStateCreateInput,
    DuckgresSinkStateGaugeStats,
    DuckgresSinkStateRecord,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet


ModelT = TypeVar("ModelT", bound=Model)

__all__ = [
    "bulk_create_sink_states",
    "claim_backfill_plan",
    "claim_pending_backfill",
    "delete_sink_state",
    "exclude_schemas_with_sink_state",
    "get_sink_state",
    "get_sink_state_gauge_stats",
    "is_backfill_capacity_reached",
    "list_failing_schema_ids",
    "list_needs_resync_sink_states",
    "list_pending_sink_states",
    "list_primed_schema_ids",
    "list_reconciling_backfill_states",
    "list_sink_backfill_run_references",
    "list_sink_states_for_team",
    "mark_backfill_completed",
    "mark_backfill_superseded",
    "mark_backfill_unsupported",
    "mark_empty_backfill_primed",
    "mark_resync_completed",
    "mark_sink_state_diverged",
    "mark_sink_state_primed",
    "record_backfill_progress",
    "record_live_batch_applied",
    "record_terminal_backfill_failure",
    "reset_backfill_plan",
    "reset_stale_backfill_claims",
    "return_backfill_claim_to_pending",
]


def bulk_create_sink_states(inputs: Iterable[DuckgresSinkStateCreateInput]) -> None:
    sink_state.bulk_create_sink_states(inputs)


def get_sink_state(schema_id: str | UUID) -> DuckgresSinkStateRecord | None:
    return sink_state.get_sink_state(schema_id)


def list_sink_backfill_run_references(team_ids: list[int] | None) -> list[DuckgresSinkBackfillRunReference]:
    return sink_state.list_sink_backfill_run_references(team_ids)


def list_sink_states_for_team(team_id: int) -> list[DuckgresSinkStateRecord]:
    return sink_state.list_sink_states_for_team(team_id)


def list_primed_schema_ids(team_ids: list[int] | None) -> list[str]:
    return sink_state.list_primed_schema_ids(team_ids)


def list_failing_schema_ids(team_ids: list[int] | None, *, failing_threshold: int) -> list[str]:
    return sink_state.list_failing_schema_ids(team_ids, failing_threshold=failing_threshold)


def exclude_schemas_with_sink_state(
    schemas: QuerySet[ModelT],
) -> QuerySet[ModelT]:
    """Keep the ExternalDataSchema anti-join in SQL while state ownership stays private."""
    return sink_state.exclude_schemas_with_sink_state(schemas)


def list_pending_sink_states(team_ids: list[int] | None, *, limit: int) -> list[DuckgresSinkStateRecord]:
    return sink_state.list_pending_sink_states(team_ids, limit=limit)


def is_backfill_capacity_reached(
    max_concurrent_backfills: int,
    *,
    organization_id: UUID | None = None,
    exclude_id: UUID | None = None,
) -> bool:
    return sink_state.is_backfill_capacity_reached(
        max_concurrent_backfills,
        organization_id=organization_id,
        exclude_id=exclude_id,
    )


def claim_pending_backfill(state_id: UUID) -> bool:
    return sink_state.claim_pending_backfill(state_id)


def return_backfill_claim_to_pending(
    state_id: UUID,
    *,
    error: str | None = None,
    record_failure: bool = False,
) -> None:
    sink_state.return_backfill_claim_to_pending(state_id, error=error, record_failure=record_failure)


def mark_backfill_unsupported(state_id: UUID, *, error: str) -> None:
    sink_state.mark_backfill_unsupported(state_id, error=error)


def mark_sink_state_primed(
    schema_id: str | UUID,
    *,
    backfill_run_uuid: str,
    chunks_applied: int | None = None,
) -> bool:
    return sink_state.mark_sink_state_primed(
        schema_id,
        backfill_run_uuid=backfill_run_uuid,
        chunks_applied=chunks_applied,
    )


def mark_sink_state_diverged(
    schema_id: str | UUID,
    *,
    run_uuid: str,
    error: str,
    failing_threshold: int,
) -> bool:
    return sink_state.mark_sink_state_diverged(
        schema_id,
        run_uuid=run_uuid,
        error=error,
        failing_threshold=failing_threshold,
    )


def reset_backfill_plan(state_id: UUID) -> None:
    sink_state.reset_backfill_plan(state_id)


def mark_empty_backfill_primed(state_id: UUID) -> None:
    sink_state.mark_empty_backfill_primed(state_id)


def claim_backfill_plan(state_id: UUID, input: DuckgresSinkBackfillPlanInput) -> bool:
    return sink_state.claim_backfill_plan(state_id, input)


def delete_sink_state(schema_id: UUID) -> None:
    sink_state.delete_sink_state(schema_id)


def reset_stale_backfill_claims(team_ids: list[int] | None, *, lease_seconds: int) -> int:
    return sink_state.reset_stale_backfill_claims(team_ids, lease_seconds=lease_seconds)


def list_reconciling_backfill_states(team_ids: list[int] | None) -> list[DuckgresSinkStateRecord]:
    return sink_state.list_reconciling_backfill_states(team_ids)


def list_needs_resync_sink_states(team_ids: list[int] | None) -> list[DuckgresSinkStateRecord]:
    return sink_state.list_needs_resync_sink_states(team_ids)


def mark_backfill_completed(state_id: UUID, *, backfill_run_uuid: str, chunks_applied: int) -> bool:
    return sink_state.mark_backfill_completed(
        state_id,
        backfill_run_uuid=backfill_run_uuid,
        chunks_applied=chunks_applied,
    )


def mark_backfill_superseded(state_id: UUID) -> bool:
    return sink_state.mark_backfill_superseded(state_id)


def record_terminal_backfill_failure(
    state_id: UUID,
    *,
    error: str,
    chunks_applied: int,
    failing_threshold: int,
) -> None:
    sink_state.record_terminal_backfill_failure(
        state_id,
        error=error,
        chunks_applied=chunks_applied,
        failing_threshold=failing_threshold,
    )


def record_backfill_progress(
    state_id: UUID,
    *,
    chunks_applied: int,
    reset_failure_streak: bool,
) -> None:
    sink_state.record_backfill_progress(
        state_id,
        chunks_applied=chunks_applied,
        reset_failure_streak=reset_failure_streak,
    )


def mark_resync_completed(state_id: UUID) -> bool:
    return sink_state.mark_resync_completed(state_id)


def get_sink_state_gauge_stats(*, failing_threshold: int) -> DuckgresSinkStateGaugeStats:
    return sink_state.get_sink_state_gauge_stats(failing_threshold=failing_threshold)


def record_live_batch_applied(schema_id: str | UUID) -> None:
    sink_state.record_live_batch_applied(schema_id)
