from collections.abc import Callable
from uuid import UUID

from django.db import transaction

from products.tasks.backend.facade import api
from products.tasks.backend.facade.contracts import TaskRunDTO
from products.tasks.backend.models import Channel, Task


def create_and_run_channel_task(
    team_id: int,
    user_id: int,
    channel_id: UUID,
    *,
    canvas_id: UUID,
    title: str,
    description: str,
    idempotency_key: UUID,
    before_create: Callable[[], None],
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> TaskRunDTO:
    with transaction.atomic():
        channel = (
            Channel.objects.for_team(team_id)
            .select_for_update(of=("self",))
            .filter(Channel.visible_to_q(user_id), id=channel_id)
            .first()
        )
        if channel is None:
            raise ValueError("Space not found.")

        origin_key = f"canvas:{canvas_id}:{user_id}:{idempotency_key}"
        existing = Task.objects.filter(team_id=team_id, origin_key=origin_key).first()
        if existing is not None:
            if existing.deleted or existing.channel_id != channel.id or existing.created_by_id != user_id:
                raise ValueError("The previous task is no longer available. Start a new request.")
            latest_run = existing.latest_run
            if latest_run is None:
                raise ValueError("The previous task has no run. Open the task to start work.")
            run_id = latest_run.id
        else:
            run_options = _run_options(model, reasoning_effort)
            before_create()
            task = api.create_task(
                team_id,
                user_id,
                validated_data={
                    "title": title,
                    "description": description,
                    "channel": channel,
                    "origin_key": origin_key,
                },
            )
            result = api.run_task(task.id, team_id, user_id, validated_data=run_options)
            if result is None:
                raise ValueError("The task is no longer available.")
            if result.error is not None:
                raise ValueError(result.error.detail)
            if result.task is None or result.task.latest_run is None:
                raise ValueError("The cloud run could not be created. Try again.")
            run_id = result.task.latest_run.id

        run = api.get_task_run(run_id, team_id)
        if run is None:
            raise ValueError("The cloud run is no longer available.")
        return run


def _run_options(model: str | None, reasoning_effort: str | None) -> dict[str, str]:
    """Run selection for `api.run_task`; empty when the caller pinned nothing, so saved defaults apply."""
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the import path
        get_reasoning_effort_error,
        get_runtime_adapter_for_model,
    )

    if model is None:
        if reasoning_effort is not None:
            raise ValueError("Select a model before setting reasoning effort.")
        return {}
    runtime_adapter = get_runtime_adapter_for_model(model)
    if runtime_adapter is None:
        raise ValueError("This model is not available. Select a model from the task model catalogue.")
    if error := get_reasoning_effort_error(runtime_adapter, model, reasoning_effort):
        raise ValueError(error)
    run_options = {"model": model, "runtime_adapter": runtime_adapter.value}
    if reasoning_effort is not None:
        run_options["reasoning_effort"] = reasoning_effort
    return run_options
