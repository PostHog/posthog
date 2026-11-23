"""Switch a PostHog AI run onto the model or reasoning effort that a message asks for, such as "use opus for this".

The run stays on its runtime adapter: the harness process is fixed when the sandbox starts, so the
classifier only offers the models of that adapter.
"""

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.feature_flags import get_model_access_error, prompt_model_switch_enabled
from products.tasks.backend.logic.model_override import (
    ModelOverrideAttribution,
    classify_model_override,
    may_request_model_override,
)
from products.tasks.backend.logic.services.gateway_model_pin import pinned_run_allows_model
from products.tasks.backend.logic.services.model_catalogue import (
    TASK_RUN_GATEWAY_PRODUCT,
    available_model_choices,
    filter_unsupported_effort,
    runtime_adapter_for,
)
from products.tasks.backend.logic.services.run_actor import get_actor_distinct_id
from products.tasks.backend.models import Task, TaskRun

logger = get_logger(__name__)


@frozen
class SwitchModelFromMessageInput:
    run_id: str
    # None reads the first message from the run state, before the agent starts and sends it itself.
    message: str | None = None
    actor_user_id: int | None = None
    # A live agent takes the switch as `set_config_option`. Before boot, the run state is enough,
    # because the agent starts on the model the state names.
    live: bool = False


def switch_model(input: SwitchModelFromMessageInput) -> bool:
    from products.posthog_ai.backend.turn_suggestions.transcript import (  # noqa: PLC0415 — keeps PostHog AI off the worker import path
        strip_context_blocks,
    )
    from products.tasks.backend.facade.api import (
        apply_task_run_model_config,  # noqa: PLC0415 — the facade imports this module's callers
    )

    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    run = TaskRun.objects.select_related("task__created_by", "task__team").filter(id=input.run_id).first()
    if run is None or run.task.origin_product != Task.OriginProduct.POSTHOG_AI:
        return False
    state = run.state or {}
    raw_message = input.message if input.message is not None else state.get("pending_user_message")
    if not isinstance(raw_message, str):
        return False
    # The composer puts page context in front of the person's text. The context is not an
    # instruction, and its untrusted part can hold any text, so the classifier never reads it.
    message = strip_context_blocks(raw_message)
    actor = User.objects.filter(id=input.actor_user_id).first() if input.actor_user_id else run.task.created_by
    current_model = state.get("model")
    runtime_adapter = state.get("runtime_adapter") or runtime_adapter_for(current_model)
    if not message or actor is None or runtime_adapter is None:
        return False

    catalogue = tuple(
        choice
        for choice in available_model_choices(TASK_RUN_GATEWAY_PRODUCT)
        if choice.runtime_adapter == runtime_adapter
    )
    # The flag and model access checks are network calls, so the free word check goes first.
    if not may_request_model_override(message, catalogue) or not prompt_model_switch_enabled(run.task.team, actor):
        return False
    distinct_id = get_actor_distinct_id(actor)
    choices = tuple(
        choice
        for choice in catalogue
        if get_model_access_error(choice.model, distinct_id=distinct_id) is None
        and pinned_run_allows_model(state, choice.model)
    )
    override = classify_model_override(
        message,
        choices,
        ModelOverrideAttribution(
            ai_product="posthog_ai",
            properties={"posthog_ai_feature": "model_override", "task_id": str(run.task_id), "run_id": str(run.id)},
            distinct_id=distinct_id,
            privacy_mode=is_privacy_mode_enabled(run.task.team),
        ),
    )
    if override is None:
        return False
    model = override.model if override.model != current_model else None
    effort = filter_unsupported_effort(runtime_adapter, model or current_model, override.reasoning_effort)
    if not model and not effort:
        return False

    logger.info("switch_model_from_message", run_id=str(run.id), model=model, reasoning_effort=effort, live=input.live)
    if input.live:
        return apply_task_run_model_config(
            run.id, run.task_id, run.team_id, model=model, reasoning_effort=effort, actor_user_id=actor.id
        )
    updates: dict[str, str | None] = {}
    if model:
        updates["model"] = model
        # An effort the new model does not support would fail the run when the agent starts.
        updates["reasoning_effort"] = effort or filter_unsupported_effort(
            runtime_adapter, model, state.get("reasoning_effort")
        )
    elif effort:
        updates["reasoning_effort"] = effort
    TaskRun.update_state_atomic(run.id, updates=updates)
    return True


@activity.defn
@close_db_connections
def switch_model_from_message(input: SwitchModelFromMessageInput) -> bool:
    return switch_model(input)
