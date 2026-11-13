import json
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.plugins.plugin_server_api import (
    WORKFLOWS_SCHEDULED_RUNS_JWT_PURPOSE,
    create_hog_flow_scheduled_invocations,
)

from products.workflows.backend.facade.contracts import ProcessedSchedules, WorkflowSchedule, WorkflowScheduleNotFound
from products.workflows.backend.facade.enums import HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import SCHEDULED_TRIGGER_TYPES, HogFlowSchedule
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences

logger = structlog.get_logger(__name__)

WRITABLE_SCHEDULE_FIELDS = frozenset({"rrule", "starts_at", "timezone", "variables"})
SCHEDULED_RUNS_PER_DISPATCH = 100
SCHEDULED_RUN_BYTES_PER_DISPATCH = 4 * 1024 * 1024
REFUSED_BEFORE_QUEUEING = frozenset({400, 401, 404, 503})


@frozen
class ScheduledRun:
    schedule_id: str
    team_id: int
    hog_flow_id: str
    variables: dict[str, Any]
    claimed_run_at: datetime | None
    next_run_at: datetime | None


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
    # Same order as the schedules a workflow response embeds, so the editor and the broadcast
    # screens agree on which schedule is the first one.
    schedules = HogFlowSchedule.objects.filter(hog_flow_id=hog_flow_id, team_id=team_id).order_by("created_at", "id")
    return [_to_schedule(s) for s in schedules]


def list_schedules_oldest_first(*, team_id: int, hog_flow_id: UUID) -> list[WorkflowSchedule]:
    """The schedules a workflow response embeds, in the order they were added."""
    schedules = HogFlowSchedule.objects.filter(hog_flow_id=hog_flow_id, team_id=team_id).order_by("created_at", "id")
    return [_to_schedule(s) for s in schedules]


def list_open_schedules(*, team_id: int, hog_flow_ids: Collection[UUID]) -> list[WorkflowSchedule]:
    """The schedules of several workflows that still have sends to come, oldest first."""
    schedules = (
        HogFlowSchedule.objects.filter(team_id=team_id, hog_flow_id__in=hog_flow_ids)
        .exclude(status=HogFlowScheduleStatus.COMPLETED)
        .order_by("created_at", "id")
    )
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


class _ScheduledRunDispatch:
    def __init__(self) -> None:
        self.dispatched: list[str] = []
        self.failed: list[str] = []
        self._pending: list[ScheduledRun] = []
        self._pending_bytes = 0

    def add(self, run: ScheduledRun) -> None:
        run_bytes = len(json.dumps(run.variables))
        if self._pending_bytes + run_bytes > SCHEDULED_RUN_BYTES_PER_DISPATCH:
            self.flush()
        self._pending.append(run)
        self._pending_bytes += run_bytes
        if len(self._pending) == SCHEDULED_RUNS_PER_DISPATCH:
            self.flush()

    def flush(self) -> None:
        chunk, self._pending, self._pending_bytes = self._pending, [], 0
        if not chunk:
            return
        try:
            response = create_hog_flow_scheduled_invocations(
                [{"team_id": run.team_id, "hog_flow_id": run.hog_flow_id, "variables": run.variables} for run in chunk]
            )
            if response.status_code in REFUSED_BEFORE_QUEUEING:
                _return_to_due(chunk)
            response.raise_for_status()
            outcomes = list(zip(chunk, [result["status"] for result in response.json()["results"]], strict=True))
        except Exception:
            logger.exception("Error dispatching scheduled runs", schedule_ids=[run.schedule_id for run in chunk])
            self.failed.extend(run.schedule_id for run in chunk)
            return
        for run, outcome in outcomes:
            if outcome == "queued":
                self.dispatched.append(run.schedule_id)
            elif outcome == "quota_limited":
                logger.info(
                    "Skipped a scheduled run over the workflow quota",
                    schedule_id=run.schedule_id,
                    team_id=run.team_id,
                    hog_flow_id=run.hog_flow_id,
                )
                self.dispatched.append(run.schedule_id)
            else:
                logger.warning("CDP refused a scheduled run", schedule_id=run.schedule_id, outcome=outcome)
                self.failed.append(run.schedule_id)


def _return_to_due(chunk: list[ScheduledRun]) -> None:
    for run in chunk:
        returned = HogFlowSchedule.objects.filter(
            id=run.schedule_id,
            team_id=run.team_id,
            status=HogFlowScheduleStatus.ACTIVE if run.next_run_at else HogFlowScheduleStatus.COMPLETED,
            next_run_at=run.next_run_at,
        ).update(status=HogFlowScheduleStatus.ACTIVE, next_run_at=run.claimed_run_at, updated_at=timezone.now())
        if not returned:
            logger.warning(
                "A refused scheduled run could not return to due, its schedule moved on",
                schedule_id=run.schedule_id,
                claimed_run_at=run.claimed_run_at,
            )


def _scheduled_run(schedule: HogFlowSchedule, hog_flow: HogFlow, claimed_run_at: datetime | None) -> ScheduledRun:
    if not WORKFLOWS_SCHEDULED_RUNS_JWT_PURPOSE.enabled():
        raise ImproperlyConfigured("Set WORKFLOWS_CANCEL_JWT_SECRET on the web tier to send scheduled runs")
    return ScheduledRun(
        schedule_id=str(schedule.id),
        team_id=schedule.team_id,
        hog_flow_id=str(hog_flow.id),
        variables=_resolve_variables(hog_flow, schedule),
        claimed_run_at=claimed_run_at,
        next_run_at=schedule.next_run_at,
    )


def process_due_schedules() -> ProcessedSchedules:
    """Execute due schedules and initialize next_run_at for new ones, across all teams."""
    processed: list[str] = []
    initialized: list[str] = []
    failed: list[str] = []
    dispatch = _ScheduledRunDispatch()

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
            scheduled_run: ScheduledRun | None = None
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

                claimed_run_at = schedule.next_run_at
                _advance_next_run(schedule, after=claimed_run_at)

                if trigger_type == "batch":
                    batch_job_params = {
                        "team_id": schedule.team_id,
                        "hog_flow": hog_flow,
                        "variables": _resolve_variables(hog_flow, schedule),
                        "filters": (hog_flow.trigger or {}).get("filters", {}),
                    }
                else:
                    scheduled_run = _scheduled_run(schedule, hog_flow, claimed_run_at)

            if scheduled_run:
                dispatch.add(scheduled_run)
            if batch_job_params:
                dispatch.flush()
                dispatch_error: Exception | None = None
                with transaction.atomic():
                    # Re-read the status under the flow's lock, so a stop that committed after
                    # the check above wins, and a stop that lands later sees this job.
                    still_active = (
                        HogFlow.objects.select_for_update()
                        .filter(id=batch_job_params["hog_flow"].id, status=HogFlow.State.ACTIVE)
                        .exists()
                    )
                    if still_active:
                        try:
                            HogFlowBatchJob.objects.create(
                                **batch_job_params,
                                status=HogFlowBatchJob.State.QUEUED,
                            )
                        except Exception as e:
                            # Keep the job and its recorded cap: a failed dispatch may still have queued the resolver.
                            dispatch_error = e
                if dispatch_error is not None:
                    raise dispatch_error
                if still_active:
                    processed.append(str(schedule_id))
        except Exception:
            logger.exception("Error processing schedule", schedule_id=str(schedule_id))
            failed.append(str(schedule_id))

    dispatch.flush()
    processed.extend(dispatch.dispatched)
    failed.extend(dispatch.failed)

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
