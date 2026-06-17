"""Supporting activities for the vision-action engine: due scan, run lifecycle, advance, and emit."""

import datetime as dt
from datetime import UTC, datetime
from uuid import UUID

from django.conf import settings

import structlog
from temporalio import activity

from posthog.api.capture_dispatch import capture_internal_routed
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.vision_action import (
    TriggerType,
    VisionAction,
    VisionActionRun,
    VisionActionRunStatus,
)
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.vision_actions.types import (
    CreateVisionActionRunInputs,
    DueVisionAction,
    EmitActionReadyInputs,
    ScheduleAllVisionActionsInputs,
    UpdateVisionActionRunInputs,
)

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$replay_vision_action_ready"
_EVENT_SOURCE = "replay_vision"


@activity.defn
@track_activity()
async def fetch_due_vision_actions_activity(inputs: ScheduleAllVisionActionsInputs) -> list[DueVisionAction]:
    return await database_sync_to_async(_fetch_due, thread_sensitive=False)(inputs)


def _fetch_due(inputs: ScheduleAllVisionActionsInputs) -> list[DueVisionAction]:
    cutoff = datetime.now(UTC) + dt.timedelta(seconds=inputs.buffer_seconds)
    # nosemgrep: semgrep.rules.idor-lookup-without-team — internal scheduler scans all teams
    rows = VisionAction.all_teams.filter(
        enabled=True,
        trigger_type=TriggerType.SCHEDULE,
        next_run_at__isnull=False,
        next_run_at__lte=cutoff,
    ).values_list("id", "team_id", "next_run_at")
    return [DueVisionAction(vision_action_id=row[0], team_id=row[1], scheduled_at=row[2]) for row in rows]


@activity.defn
@track_activity()
async def create_vision_action_run_activity(inputs: CreateVisionActionRunInputs) -> UUID:
    return await database_sync_to_async(_create_run, thread_sensitive=False)(inputs)


def _create_run(inputs: CreateVisionActionRunInputs) -> UUID:
    # idempotency_key is unique → get_or_create makes the activity safe to retry.
    run, _ = VisionActionRun.all_teams.get_or_create(
        idempotency_key=inputs.idempotency_key,
        defaults={
            "vision_action_id": inputs.vision_action_id,
            "team_id": inputs.team_id,
            "temporal_workflow_id": inputs.temporal_workflow_id,
            "scheduled_at": inputs.scheduled_at,
            "status": VisionActionRunStatus.RUNNING,
        },
    )
    return run.id


@activity.defn
@track_activity()
async def validate_vision_action_activity(vision_action_id: UUID) -> str | None:
    """Return a skip reason if the action shouldn't deliver, else None."""
    return await database_sync_to_async(_validate, thread_sensitive=False)(vision_action_id)


def _validate(vision_action_id: UUID) -> str | None:
    action = VisionAction.all_teams.filter(pk=vision_action_id).first()
    if action is None:
        return "not_found"
    if not action.enabled:
        return "disabled"
    if action.hog_flow_id is None:
        return "no_delivery_flow"
    return None


@activity.defn
@track_activity()
async def update_vision_action_run_activity(inputs: UpdateVisionActionRunInputs) -> None:
    await database_sync_to_async(_update_run, thread_sensitive=False)(inputs)


def _update_run(inputs: UpdateVisionActionRunInputs) -> None:
    # .update() bypasses auto_now, so stamp updated_at explicitly.
    VisionActionRun.all_teams.filter(pk=inputs.run_id).update(
        status=inputs.status, error=inputs.error, updated_at=datetime.now(UTC)
    )


@activity.defn
@track_activity()
async def advance_next_run_at_activity(vision_action_id: UUID) -> None:
    await database_sync_to_async(_advance_next_run, thread_sensitive=False)(vision_action_id)


def _advance_next_run(vision_action_id: UUID) -> None:
    action = VisionAction.all_teams.filter(pk=vision_action_id).first()
    if action is None:
        return
    # Recompute to the next occurrence after now and stamp the run time. The save() guard won't
    # re-touch next_run_at (rrule unchanged), so our computed value is what persists.
    action._recompute_next_run_at()
    action.last_run_at = datetime.now(UTC)
    action.save(update_fields=["next_run_at", "last_run_at", "updated_at"])


@activity.defn
@track_activity()
async def emit_action_ready_activity(inputs: EmitActionReadyInputs) -> None:
    await database_sync_to_async(_emit, thread_sensitive=False)(inputs)


def _emit(inputs: EmitActionReadyInputs) -> None:
    run = VisionActionRun.all_teams.select_related("vision_action", "team").get(pk=inputs.run_id)
    action = run.vision_action
    team = run.team

    action_url = f"{settings.SITE_URL}/project/{team.id}/replay/vision-actions/{action.id}"
    properties = {
        "$insert_id": str(run.id),
        "vision_action_id": str(action.id),
        "scanner_id": str(action.scanner_id) if action.scanner_id else None,
        "vision_action_run_id": str(run.id),
        "slack_text": run.output.get("slack", ""),
        "action_url": action_url,
    }
    result = capture_internal_routed(
        token=team.api_token,
        event_name=_EVENT_NAME,
        event_source=_EVENT_SOURCE,
        distinct_id=replay_vision_distinct_id(team.id),
        timestamp=datetime.now(UTC),
        properties=properties,
        process_person_profile=False,
        event_uuid=str(run.id),
    )
    result.raise_for_status()
