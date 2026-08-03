from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from django.db.models import Count, F, Min, Model, Q, Value
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from products.managed_warehouse.backend.facade.contracts import (
    DuckgresSinkBackfillPlanInput,
    DuckgresSinkBackfillRunReference,
    DuckgresSinkState,
    DuckgresSinkStateCreateInput,
    DuckgresSinkStateGaugeStats,
    DuckgresSinkStateRecord,
)
from products.managed_warehouse.backend.models import DuckgresSinkSchemaState

if TYPE_CHECKING:
    from django.db.models import QuerySet


ModelT = TypeVar("ModelT", bound=Model)


def _to_record(
    state: DuckgresSinkSchemaState,
    *,
    organization_id: UUID | None = None,
) -> DuckgresSinkStateRecord:
    return DuckgresSinkStateRecord(
        id=state.id,
        team_id=state.team_id,
        schema_id=state.schema_id,
        state=DuckgresSinkState(state.state),
        snapshot_version=state.snapshot_version,
        plan_cutoff=state.plan_cutoff,
        backfill_run_uuid=state.backfill_run_uuid,
        chunk_count=state.chunk_count,
        chunks_applied=state.chunks_applied,
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
        first_failed_at=state.first_failed_at,
        queue_last_applied_at=state.queue_last_applied_at,
        updated_at=state.updated_at,
        organization_id=organization_id,
    )


def _create_model(input: DuckgresSinkStateCreateInput) -> DuckgresSinkSchemaState:
    return DuckgresSinkSchemaState(
        team_id=input.team_id,
        schema_id=input.schema_id,
        state=input.state.value,
        snapshot_version=input.snapshot_version,
        plan_cutoff=input.plan_cutoff,
        backfill_run_uuid=input.backfill_run_uuid,
        chunk_count=input.chunk_count,
        chunks_applied=input.chunks_applied,
        last_error=input.last_error,
        consecutive_failures=input.consecutive_failures,
        first_failed_at=input.first_failed_at,
        queue_last_applied_at=input.queue_last_applied_at,
    )


def create_sink_state(input: DuckgresSinkStateCreateInput) -> DuckgresSinkStateRecord:
    state = _create_model(input)
    state.save(force_insert=True)
    return _to_record(state)


def bulk_create_sink_states(inputs: Iterable[DuckgresSinkStateCreateInput]) -> None:
    DuckgresSinkSchemaState.objects.bulk_create((_create_model(input) for input in inputs), ignore_conflicts=True)


def get_sink_state(schema_id: str | UUID) -> DuckgresSinkStateRecord | None:
    try:
        return _to_record(DuckgresSinkSchemaState.objects.get(schema_id=schema_id))
    except DuckgresSinkSchemaState.DoesNotExist:
        return None


def get_sink_state_by_id(state_id: UUID) -> DuckgresSinkStateRecord | None:
    try:
        return _to_record(DuckgresSinkSchemaState.objects.get(id=state_id))
    except DuckgresSinkSchemaState.DoesNotExist:
        return None


def list_sink_states_for_team(team_id: int) -> list[DuckgresSinkStateRecord]:
    return [
        _to_record(state) for state in DuckgresSinkSchemaState.objects.filter(team_id=team_id).order_by("schema_id")
    ]


def list_sink_backfill_run_references(team_ids: list[int] | None) -> list[DuckgresSinkBackfillRunReference]:
    states = DuckgresSinkSchemaState.objects.all()
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [
        DuckgresSinkBackfillRunReference(schema_id=schema_id, backfill_run_uuid=backfill_run_uuid)
        for schema_id, backfill_run_uuid in states.values_list("schema_id", "backfill_run_uuid")
    ]


def list_primed_schema_ids(team_ids: list[int] | None) -> list[str]:
    states = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkState.PRIMED.value)
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [str(schema_id) for schema_id in states.values_list("schema_id", flat=True)]


def _failing_q(failing_threshold: int) -> Q:
    return Q(consecutive_failures__gte=failing_threshold) | Q(state=DuckgresSinkState.NEEDS_RESYNC.value)


def list_failing_schema_ids(team_ids: list[int] | None, *, failing_threshold: int) -> list[str]:
    states = DuckgresSinkSchemaState.objects.exclude(state=DuckgresSinkState.PRIMED.value).filter(
        _failing_q(failing_threshold)
    )
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [str(schema_id) for schema_id in states.values_list("schema_id", flat=True)]


def exclude_schemas_with_sink_state(
    schemas: QuerySet[ModelT],
) -> QuerySet[ModelT]:
    return schemas.exclude(id__in=DuckgresSinkSchemaState.objects.values("schema_id"))


def list_pending_sink_states(team_ids: list[int] | None, *, limit: int) -> list[DuckgresSinkStateRecord]:
    states = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkState.PENDING_BACKFILL.value)
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [
        _to_record(state, organization_id=state.team.organization_id)
        for state in states.select_related("team").order_by("updated_at")[:limit]
    ]


def is_backfill_capacity_reached(
    max_concurrent_backfills: int,
    *,
    organization_id: UUID | None = None,
    exclude_id: UUID | None = None,
) -> bool:
    states = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkState.BACKFILLING.value)
    if organization_id is not None:
        states = states.filter(team__organization_id=organization_id)
    if exclude_id is not None:
        states = states.exclude(id=exclude_id)
    return states.count() >= max_concurrent_backfills


def claim_pending_backfill(state_id: UUID) -> bool:
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            id=state_id,
            state=DuckgresSinkState.PENDING_BACKFILL.value,
        ).update(
            state=DuckgresSinkState.BACKFILLING.value,
            updated_at=timezone.now(),
        )
    )


def return_backfill_claim_to_pending(
    state_id: UUID,
    *,
    error: str | None = None,
    record_failure: bool = False,
) -> None:
    now = timezone.now()
    updates: dict[str, object] = {
        "state": DuckgresSinkState.PENDING_BACKFILL.value,
        "updated_at": now,
    }
    if error is not None:
        updates["last_error"] = error
    if record_failure:
        updates.update(
            consecutive_failures=F("consecutive_failures") + 1,
            first_failed_at=Coalesce(F("first_failed_at"), Value(now)),
        )
    DuckgresSinkSchemaState.objects.filter(
        id=state_id,
        state=DuckgresSinkState.BACKFILLING.value,
        backfill_run_uuid__isnull=True,
    ).update(**updates)


def mark_backfill_unsupported(state_id: UUID, *, error: str) -> None:
    now = timezone.now()
    DuckgresSinkSchemaState.objects.filter(id=state_id).update(
        state=DuckgresSinkState.NEEDS_RESYNC.value,
        last_error=error[:2000],
        updated_at=now,
        consecutive_failures=F("consecutive_failures") + 1,
        first_failed_at=Coalesce(F("first_failed_at"), Value(now)),
    )


def mark_sink_state_primed(
    schema_id: str | UUID,
    *,
    backfill_run_uuid: str,
    chunks_applied: int | None = None,
) -> bool:
    updates: dict[str, object] = {
        "state": DuckgresSinkState.PRIMED.value,
        "last_error": None,
        "updated_at": timezone.now(),
        "consecutive_failures": 0,
        "first_failed_at": None,
    }
    if chunks_applied is not None:
        updates["chunks_applied"] = chunks_applied
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            schema_id=schema_id,
            state=DuckgresSinkState.BACKFILLING.value,
            backfill_run_uuid=backfill_run_uuid,
        ).update(**updates)
    )


def mark_sink_state_diverged(
    schema_id: str | UUID,
    *,
    run_uuid: str,
    error: str,
    failing_threshold: int,
) -> bool:
    now = timezone.now()
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            schema_id=schema_id,
            state=DuckgresSinkState.PRIMED.value,
        ).update(
            state=DuckgresSinkState.NEEDS_RESYNC.value,
            last_error=f"live run {run_uuid} failed in the duckgres sink: {error}"[:2000],
            updated_at=now,
            consecutive_failures=Greatest(F("consecutive_failures"), Value(failing_threshold)),
            first_failed_at=Coalesce(F("first_failed_at"), Value(now)),
        )
    )


def reset_backfill_plan(state_id: UUID) -> None:
    # Operator fresh start: the streak (and its backoff) must not outlive the run it was recorded against.
    DuckgresSinkSchemaState.objects.filter(id=state_id).update(
        state=DuckgresSinkState.PENDING_BACKFILL.value,
        snapshot_version=None,
        plan_cutoff=None,
        backfill_run_uuid=None,
        chunk_count=None,
        chunks_applied=0,
        last_error=None,
        updated_at=timezone.now(),
        consecutive_failures=0,
        first_failed_at=None,
    )


def mark_empty_backfill_primed(state_id: UUID) -> None:
    DuckgresSinkSchemaState.objects.filter(id=state_id).update(
        state=DuckgresSinkState.PRIMED.value,
        last_error=None,
        updated_at=timezone.now(),
        consecutive_failures=0,
        first_failed_at=None,
    )


def claim_backfill_plan(state_id: UUID, input: DuckgresSinkBackfillPlanInput) -> bool:
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            id=state_id,
            state=DuckgresSinkState.BACKFILLING.value,
            backfill_run_uuid__isnull=True,
        ).update(
            snapshot_version=input.snapshot_version,
            plan_cutoff=None,
            backfill_run_uuid=input.backfill_run_uuid,
            chunk_count=input.chunk_count,
            chunks_applied=0,
            last_error=None,
            updated_at=timezone.now(),
            consecutive_failures=0,
            first_failed_at=None,
        )
    )


def delete_sink_state(schema_id: UUID) -> None:
    DuckgresSinkSchemaState.objects.filter(schema_id=schema_id).delete()


def reset_stale_backfill_claims(team_ids: list[int] | None, *, lease_seconds: int) -> int:
    stale = DuckgresSinkSchemaState.objects.filter(
        state=DuckgresSinkState.BACKFILLING.value,
        backfill_run_uuid__isnull=True,
        updated_at__lt=timezone.now() - timedelta(seconds=lease_seconds),
    )
    if team_ids is not None:
        stale = stale.filter(team_id__in=team_ids)
    return stale.update(state=DuckgresSinkState.PENDING_BACKFILL.value, updated_at=timezone.now())


def list_reconciling_backfill_states(team_ids: list[int] | None) -> list[DuckgresSinkStateRecord]:
    states = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkState.BACKFILLING.value)
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [_to_record(state) for state in states if state.backfill_run_uuid]


def list_needs_resync_sink_states(team_ids: list[int] | None) -> list[DuckgresSinkStateRecord]:
    states = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkState.NEEDS_RESYNC.value)
    if team_ids is not None:
        states = states.filter(team_id__in=team_ids)
    return [_to_record(state) for state in states]


def mark_backfill_completed(state_id: UUID, *, backfill_run_uuid: str, chunks_applied: int) -> bool:
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            id=state_id,
            state=DuckgresSinkState.BACKFILLING.value,
            backfill_run_uuid=backfill_run_uuid,
        ).update(
            state=DuckgresSinkState.PRIMED.value,
            chunks_applied=chunks_applied,
            last_error=None,
            updated_at=timezone.now(),
            consecutive_failures=0,
            first_failed_at=None,
        )
    )


def mark_backfill_superseded(state_id: UUID) -> bool:
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            id=state_id,
            state=DuckgresSinkState.BACKFILLING.value,
        ).update(
            state=DuckgresSinkState.NEEDS_RESYNC.value,
            last_error=None,
            updated_at=timezone.now(),
        )
    )


def record_terminal_backfill_failure(
    state_id: UUID,
    *,
    error: str,
    chunks_applied: int,
    failing_threshold: int,
) -> None:
    now = timezone.now()
    DuckgresSinkSchemaState.objects.filter(id=state_id).update(
        last_error=error[:2000],
        chunks_applied=chunks_applied,
        consecutive_failures=Greatest(F("consecutive_failures"), Value(failing_threshold)),
        first_failed_at=Coalesce(F("first_failed_at"), Value(now)),
        updated_at=now,
    )


def record_backfill_progress(
    state_id: UUID,
    *,
    chunks_applied: int,
    reset_failure_streak: bool,
) -> None:
    updates: dict[str, object] = {
        "chunks_applied": chunks_applied,
        "updated_at": timezone.now(),
    }
    if reset_failure_streak:
        updates.update(consecutive_failures=0, first_failed_at=None)
    DuckgresSinkSchemaState.objects.filter(id=state_id).update(**updates)


def mark_resync_completed(state_id: UUID) -> bool:
    return bool(
        DuckgresSinkSchemaState.objects.filter(
            id=state_id,
            state=DuckgresSinkState.NEEDS_RESYNC.value,
        ).update(
            state=DuckgresSinkState.PRIMED.value,
            last_error=None,
            updated_at=timezone.now(),
            consecutive_failures=0,
            first_failed_at=None,
        )
    )


def get_sink_state_gauge_stats(*, failing_threshold: int) -> DuckgresSinkStateGaugeStats:
    counts = {
        DuckgresSinkState(state): count
        for state, count in DuckgresSinkSchemaState.objects.values_list("state").annotate(n=Count("id"))
    }
    failing = DuckgresSinkSchemaState.objects.exclude(state=DuckgresSinkState.PRIMED.value).filter(
        _failing_q(failing_threshold)
    )
    stats = failing.aggregate(n=Count("id"), oldest=Min("first_failed_at"))
    return DuckgresSinkStateGaugeStats(
        counts=counts,
        failing_count=stats["n"] or 0,
        oldest_failure_at=stats["oldest"],
    )


def record_live_batch_applied(schema_id: str | UUID) -> None:
    DuckgresSinkSchemaState.objects.filter(schema_id=schema_id).update(queue_last_applied_at=timezone.now())


def replace_sink_state_for_test(record: DuckgresSinkStateRecord) -> None:
    DuckgresSinkSchemaState.objects.filter(id=record.id).update(
        team_id=record.team_id,
        schema_id=record.schema_id,
        state=record.state.value,
        snapshot_version=record.snapshot_version,
        plan_cutoff=record.plan_cutoff,
        backfill_run_uuid=record.backfill_run_uuid,
        chunk_count=record.chunk_count,
        chunks_applied=record.chunks_applied,
        last_error=record.last_error,
        consecutive_failures=record.consecutive_failures,
        first_failed_at=record.first_failed_at,
        queue_last_applied_at=record.queue_last_applied_at,
        updated_at=record.updated_at,
    )


def list_sink_states_for_test() -> list[DuckgresSinkStateRecord]:
    return [_to_record(state) for state in DuckgresSinkSchemaState.objects.all()]


def count_sink_states_for_test() -> int:
    return DuckgresSinkSchemaState.objects.count()


def sink_state_exists_for_test(state_id: UUID) -> bool:
    return DuckgresSinkSchemaState.objects.filter(id=state_id).exists()
