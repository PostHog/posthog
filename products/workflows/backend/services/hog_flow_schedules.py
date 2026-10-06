from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.plugins.plugin_server_api import create_hog_flow_scheduled_invocation

from products.workflows.backend.facade.contracts import ProcessedSchedules, WorkflowSchedule, WorkflowScheduleNotFound
from products.workflows.backend.facade.enums import HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import SCHEDULED_TRIGGER_TYPES, HogFlowSchedule
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences

logger = structlog.get_logger(__name__)

WRITABLE_SCHEDULE_FIELDS = frozenset({"rrule", "starts_at", "timezone", "variables"})


def _to_schedule(schedule: HogFlowSchedule) -> WorkflowSchedule:
    return WorkflowSchedule(
        id=schedule.id,
        hog_flow_id=schedule.hog_flow_id,
        rrule=schedule.rrule,
        starts_at=schedule.starts_at,
        timezone=schedule.timezone,
        variables=schedule.variables,
        status=HogFlowScheduleStatus(schedule.status),
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _get_schedule_row(team_id: int, hog_flow_id: UUID, schedule_id: str | UUID) -> HogFlowSchedule:
    try:
        return HogFlowSchedule.objects.get(id=schedule_id, hog_flow_id=hog_flow_id, team_id=team_id)
    except (HogFlowSchedule.DoesNotExist, ValidationError, ValueError):
        # ValidationError and ValueError fire when the id is not a parseable UUID.
        raise WorkflowScheduleNotFound()


def list_schedules(*, team_id: int, hog_flow_id: UUID) -> list[WorkflowSchedule]:
    schedules = HogFlowSchedule.objects.filter(hog_flow_id=hog_flow_id, team_id=team_id).order_by("-created_at")
    return [_to_schedule(s) for s in schedules]


def get_schedule(*, team_id: int, hog_flow_id: UUID, schedule_id: str) -> WorkflowSchedule:
    return _to_schedule(_get_schedule_row(team_id, hog_flow_id, schedule_id))


def create_schedule(*, team_id: int, hog_flow_id: UUID, fields: Mapping[str, Any]) -> WorkflowSchedule:
    values = {key: value for key, value in fields.items() if key in WRITABLE_SCHEDULE_FIELDS}
    schedule = HogFlowSchedule.objects.create(team_id=team_id, hog_flow_id=hog_flow_id, **values)
    return _to_schedule(schedule)


def update_schedule(
    *, team_id: int, hog_flow_id: UUID, schedule_id: UUID, fields: Mapping[str, Any]
) -> WorkflowSchedule:
    schedule = _get_schedule_row(team_id, hog_flow_id, schedule_id)
    if any(field in fields for field in ("rrule", "starts_at", "timezone")):
        # Force the scheduler to recalculate the next occurrence on its next poll
        schedule.next_run_at = None
        if schedule.status != HogFlowScheduleStatus.PAUSED:
            schedule.status = HogFlowScheduleStatus.ACTIVE
    for key, value in fields.items():
        if key in WRITABLE_SCHEDULE_FIELDS:
            setattr(schedule, key, value)
    schedule.save()
    return _to_schedule(schedule)


def delete_schedule(*, team_id: int, hog_flow_id: UUID, schedule_id: UUID) -> None:
    _get_schedule_row(team_id, hog_flow_id, schedule_id).delete()


def _advance_next_run(schedule: HogFlowSchedule, after: datetime | None = None) -> list[datetime]:
    """Compute and set next_run_at, or mark completed if RRULE is exhausted."""
    occurrences = compute_next_occurrences(
        rrule_string=schedule.rrule,
        starts_at=schedule.starts_at,
        timezone_str=schedule.timezone,
        after=after,
        count=1,
    )
    if occurrences:
        schedule.next_run_at = occurrences[0]
        schedule.save(update_fields=["next_run_at", "updated_at"])
    else:
        schedule.status = HogFlowScheduleStatus.COMPLETED
        schedule.next_run_at = None
        schedule.save(update_fields=["status", "next_run_at", "updated_at"])
    return occurrences


def _resolve_variables(hog_flow: HogFlow, schedule: HogFlowSchedule) -> dict[str, Any]:
    """Build default variables from HogFlow schema, then merge schedule overrides."""
    variables = {}
    for var in hog_flow.variables or []:
        variables[var.get("key")] = var.get("default")
    variables.update(schedule.variables or {})
    return variables


def process_due_schedules() -> ProcessedSchedules:
    """Execute due schedules and initialize next_run_at for new ones, across all teams."""
    processed: list[str] = []
    initialized: list[str] = []
    failed: list[str] = []

    # 1. Process due schedules (next_run_at <= now)
    # nosemgrep: idor-lookup-without-team (internal endpoint processes all teams)
    due_schedule_ids = list(
        HogFlowSchedule.objects.filter(
            status=HogFlowScheduleStatus.ACTIVE, next_run_at__lte=timezone.now()
        ).values_list("id", flat=True)
    )

    for schedule_id in due_schedule_ids:
        try:
            batch_job_params: dict | None = None
            schedule_invocation_params: dict | None = None
            with transaction.atomic():
                # Per-schedule transaction: lock only one row at a time to minimize
                # lock duration and allow concurrent replicas via skip_locked.
                # Re-checks conditions since the schedule may have been processed
                # between the ID scan and this lock.
                schedule = (
                    # nosemgrep: idor-lookup-without-team
                    HogFlowSchedule.objects.select_for_update(skip_locked=True)
                    .select_related("hog_flow")
                    .filter(id=schedule_id, status=HogFlowScheduleStatus.ACTIVE, next_run_at__lte=timezone.now())
                    .first()
                )
                if not schedule:
                    continue

                hog_flow = schedule.hog_flow
                trigger_type = (hog_flow.trigger or {}).get("type")

                if hog_flow.status != "active" or trigger_type not in SCHEDULED_TRIGGER_TYPES:
                    schedule.next_run_at = None
                    schedule.save(update_fields=["next_run_at", "updated_at"])
                    continue

                _advance_next_run(schedule, after=schedule.next_run_at)

                if trigger_type == "batch":
                    batch_job_params = {
                        "team_id": schedule.team_id,
                        "hog_flow": hog_flow,
                        "variables": _resolve_variables(hog_flow, schedule),
                        "filters": (hog_flow.trigger or {}).get("filters", {}),
                    }
                else:
                    schedule_invocation_params = {
                        "team_id": schedule.team_id,
                        "hog_flow_id": str(hog_flow.id),
                        "variables": _resolve_variables(hog_flow, schedule),
                    }

            # Dispatch outside the transaction so HTTP calls don't hold the row lock.
            if batch_job_params:
                with transaction.atomic():
                    # Re-read the status under the flow's lock, so a stop that committed after
                    # the check above wins, and a stop that lands later sees this job.
                    still_active = (
                        HogFlow.objects.select_for_update()
                        .filter(id=batch_job_params["hog_flow"].id, status=HogFlow.State.ACTIVE)
                        .exists()
                    )
                    if still_active:
                        HogFlowBatchJob.objects.create(
                            **batch_job_params,
                            status=HogFlowBatchJob.State.QUEUED,
                        )
                if still_active:
                    processed.append(str(schedule_id))
            elif schedule_invocation_params:
                response = create_hog_flow_scheduled_invocation(**schedule_invocation_params)
                response.raise_for_status()
                processed.append(str(schedule_id))
        except Exception:
            logger.exception("Error processing schedule", schedule_id=str(schedule_id))
            failed.append(str(schedule_id))

    # 2. Initialize next_run_at for schedules that need it
    # nosemgrep: idor-lookup-without-team (internal endpoint processes all teams)
    uninitialized_ids = list(
        HogFlowSchedule.objects.filter(
            status=HogFlowScheduleStatus.ACTIVE,
            next_run_at__isnull=True,
            hog_flow__status="active",
            hog_flow__trigger__type__in=SCHEDULED_TRIGGER_TYPES,
        ).values_list("id", flat=True)
    )

    for schedule_id in uninitialized_ids:
        try:
            with transaction.atomic():
                # Per-schedule transaction: lock only one row at a time to minimize
                # lock duration and allow concurrent replicas via skip_locked.
                # Re-checks conditions since the schedule may have been initialized
                # between the ID scan and this lock.
                schedule = (
                    # nosemgrep: idor-lookup-without-team
                    HogFlowSchedule.objects.select_for_update(skip_locked=True)
                    .filter(id=schedule_id, status=HogFlowScheduleStatus.ACTIVE, next_run_at__isnull=True)
                    .first()
                )
                if not schedule:
                    continue

                if _advance_next_run(schedule):
                    initialized.append(str(schedule.id))
        except Exception:
            logger.exception("Error initializing schedule", schedule_id=str(schedule_id))
            failed.append(str(schedule_id))

    return ProcessedSchedules(processed=processed, initialized=initialized, failed=failed)
