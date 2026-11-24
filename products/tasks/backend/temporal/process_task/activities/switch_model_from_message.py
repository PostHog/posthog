"""Switch a live PostHog AI run onto the model or reasoning effort that a follow-up asks for, such as "use opus for this".

The run stays on its runtime adapter, because the harness process is fixed when the sandbox starts.
A new or resumed run reads its first message before the run exists, in the create and run requests.
"""

from time import monotonic

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.services.model_catalogue import filter_unsupported_effort, runtime_adapter_for
from products.tasks.backend.logic.services.prompt_model_switch import requested_model_switch
from products.tasks.backend.models import Task, TaskRun

logger = get_logger(__name__)

# A switch that lands after the follow-up starts would change the model in the middle of that turn.
# So a classification that runs past this budget is dropped, and the workflow timeout leaves room
# for the budget plus the two `set_config_option` commands that follow it.
CLASSIFY_BUDGET_SECONDS = 25


@frozen
class SwitchModelFromMessageInput:
    run_id: str
    message: str
    actor_user_id: int | None = None


def switch_model(input: SwitchModelFromMessageInput) -> bool:
    from products.tasks.backend.facade.api import (  # noqa: PLC0415 — the facade imports this module's callers
        apply_task_run_model_config,
    )

    run = TaskRun.objects.select_related("task__created_by", "task__team__organization").filter(id=input.run_id).first()
    if run is None or run.task.origin_product != Task.OriginProduct.POSTHOG_AI:
        return False
    state = run.state or {}
    actor = User.objects.filter(id=input.actor_user_id).first() if input.actor_user_id else run.task.created_by
    current_model = state.get("model")
    runtime_adapter = state.get("runtime_adapter") or runtime_adapter_for(current_model)
    if actor is None or runtime_adapter is None:
        return False

    started = monotonic()
    override = requested_model_switch(
        input.message, team=run.task.team, user=actor, runtime_adapter=runtime_adapter, run_state=state
    )
    if override is None:
        return False
    if monotonic() - started > CLASSIFY_BUDGET_SECONDS:
        logger.warning("switch_model_from_message_classification_overran", run_id=str(run.id))
        return False
    model = override.model if override.model != current_model else None
    effort = filter_unsupported_effort(runtime_adapter, model or current_model, override.reasoning_effort)
    if not model and not effort:
        return False
    logger.info("switch_model_from_message", run_id=str(run.id), model=model, reasoning_effort=effort)
    return apply_task_run_model_config(
        run.id, run.task_id, run.team_id, model=model, reasoning_effort=effort, actor_user_id=actor.id
    )


@activity.defn
@close_db_connections
def switch_model_from_message(input: SwitchModelFromMessageInput) -> bool:
    return switch_model(input)
