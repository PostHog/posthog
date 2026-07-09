"""Supporting activities for the vision-action engine: per-scanner eligibility/claim, run lifecycle, and emit."""

from datetime import UTC, datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction

import structlog
from temporalio import activity

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
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
    EvaluateDueVisionActionsInputs,
    UpdateVisionActionRunInputs,
    ValidateVisionActionInputs,
)

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$replay_vision_action_ready"


@activity.defn
@track_activity()
async def evaluate_due_vision_actions_activity(inputs: EvaluateDueVisionActionsInputs) -> list[DueVisionAction]:
    return await database_sync_to_async(_evaluate_due, thread_sensitive=False)(inputs)


def _evaluate_due(inputs: EvaluateDueVisionActionsInputs) -> list[DueVisionAction]:
    """Return this scanner's due schedule actions, claiming each by advancing next_run_at.

    The claim happens in the same transaction as the read so the next sweep can't re-fire an action
    while its child is still running — advancing the cursor here (not in the child) is what prevents
    a slow or failed child from hot-looping.
    """
    now = datetime.now(UTC)
    due: list[DueVisionAction] = []
    with transaction.atomic():
        # for_team scopes the read to one team (no all_teams scan); select_for_update guards against
        # a concurrent claim (belt-and-suspenders — per-scanner sweeps are already serialized).
        actions = (
            VisionAction.objects.for_team(inputs.team_id)
            .select_for_update()
            .filter(
                scanner_id=inputs.scanner_id,
                enabled=True,
                trigger_type=TriggerType.SCHEDULE,
                next_run_at__isnull=False,
                next_run_at__lte=now,
            )
        )
        for action in actions:
            scheduled_at = action.next_run_at
            # Claim via a direct .update() rather than save(): VisionAction.save() re-derives
            # next_run_at when the schedule key changed, and we've already advanced it here — going
            # through .update() bypasses that override so the claim can't double-recompute the cursor.
            action._recompute_next_run_at()
            VisionAction.objects.for_team(inputs.team_id).filter(pk=action.id).update(
                next_run_at=action.next_run_at, last_run_at=now, updated_at=now
            )
            due.append(DueVisionAction(vision_action_id=action.id, team_id=action.team_id, scheduled_at=scheduled_at))
    return due


@activity.defn
@track_activity()
async def create_vision_action_run_activity(inputs: CreateVisionActionRunInputs) -> UUID:
    return await database_sync_to_async(_create_run, thread_sensitive=False)(inputs)


def _create_run(inputs: CreateVisionActionRunInputs) -> UUID:
    # idempotency_key is unique → get_or_create makes the activity safe to retry. for_team scopes the
    # lookup; team_id stays in defaults because the filter doesn't propagate into row creation.
    run, _ = VisionActionRun.objects.for_team(inputs.team_id).get_or_create(
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
async def validate_vision_action_activity(inputs: ValidateVisionActionInputs) -> str | None:
    """Return a skip reason if the action shouldn't deliver, else None."""
    return await database_sync_to_async(_validate, thread_sensitive=False)(inputs)


def _validate(inputs: ValidateVisionActionInputs) -> str | None:
    action = VisionAction.objects.for_team(inputs.team_id).filter(pk=inputs.vision_action_id).first()
    if action is None:
        return "not_found"
    if not action.enabled:
        return "disabled"
    # No delivery_config is fine: the persisted run is the in-app artifact (scanner digest, run
    # history); _emit no-ops when there's nowhere to deliver.
    return None


@activity.defn
@track_activity()
async def update_vision_action_run_activity(inputs: UpdateVisionActionRunInputs) -> None:
    await database_sync_to_async(_update_run, thread_sensitive=False)(inputs)


def _update_run(inputs: UpdateVisionActionRunInputs) -> None:
    # .update() bypasses auto_now, so stamp updated_at explicitly.
    VisionActionRun.objects.for_team(inputs.team_id).filter(pk=inputs.run_id).update(
        status=inputs.status, error=inputs.error, updated_at=datetime.now(UTC)
    )


@activity.defn
@track_activity()
async def emit_action_ready_activity(inputs: EmitActionReadyInputs) -> None:
    await database_sync_to_async(_emit, thread_sensitive=False)(inputs)


def _emit(inputs: EmitActionReadyInputs) -> None:
    run = VisionActionRun.objects.for_team(inputs.team_id).select_related("vision_action", "team").get(pk=inputs.run_id)
    action = run.vision_action
    team = run.team

    if not action.delivery_config:
        # Nothing to deliver to; the run row (synthesized_markdown) is the in-app artifact.
        return

    action_url = f"{settings.SITE_URL}/project/{team.id}/replay/vision-actions/{action.id}"
    # Private internal event (cdp_internal_events topic), NOT the public capture pipeline — an
    # internal_destination HogFunction filtered on vision_action_id delivers it. This is non-forgeable
    # with the public project token, and (unlike capture) it does NOT land in the analytics events
    # table — VisionActionRun is the durable history. `uuid=run.id` keeps the emit idempotent on retry.
    produce_internal_event(
        team_id=team.id,
        event=InternalEventEvent(
            event=_EVENT_NAME,
            distinct_id=replay_vision_distinct_id(team.id),
            uuid=str(run.id),
            properties={
                "vision_action_id": str(action.id),
                "scanner_id": str(action.scanner_id) if action.scanner_id else None,
                "vision_action_run_id": str(run.id),
                "slack_text": run.output.get("slack", ""),
                "action_url": action_url,
            },
        ),
    )
