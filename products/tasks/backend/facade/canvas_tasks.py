from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from posthog.storage import object_storage

from products.tasks.backend.facade import api
from products.tasks.backend.facade.contracts import TaskRunDTO
from products.tasks.backend.models import Channel, Task

TaskScreenshot = tuple[str, bytes, str]


def _stage_screenshots(task: Task, screenshots: list[TaskScreenshot]) -> list[str]:
    from products.tasks.backend.logic.services.staged_artifacts import (
        STAGED_ARTIFACT_TTL_DAYS,
        build_task_artifact_entry,
        build_task_staged_artifact_storage_path,
        cache_task_staged_artifact,
        tag_task_artifact,
    )

    artifact_ids = []
    for name, content, content_type in screenshots:
        artifact_id = uuid4().hex
        storage_path = build_task_staged_artifact_storage_path(task, artifact_id, name)
        object_storage.write(storage_path, content)
        tag_task_artifact(storage_path, ttl_days=STAGED_ARTIFACT_TTL_DAYS, team_id=task.team_id)
        cache_task_staged_artifact(
            task,
            build_task_artifact_entry(
                artifact_id=artifact_id,
                name=name,
                artifact_type="user_attachment",
                source="user",
                size=len(content),
                content_type=content_type,
                storage_path=storage_path,
            ),
        )
        artifact_ids.append(artifact_id)
    return artifact_ids


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
    load_screenshots: Callable[[], list[TaskScreenshot]] | None = None,
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
            from products.tasks.backend.temporal.process_task.utils import (
                get_reasoning_effort_error,
                get_runtime_adapter_for_model,
            )

            run_options: dict[str, Any] = {}
            if reasoning_effort is not None and model is None:
                raise ValueError("Select a model before setting reasoning effort.")
            if model is not None:
                runtime_adapter = get_runtime_adapter_for_model(model)
                if runtime_adapter is None:
                    raise ValueError("This model is not available. Select a model from the task model catalogue.")
                if error := get_reasoning_effort_error(runtime_adapter, model, reasoning_effort):
                    raise ValueError(error)
                run_options = {"model": model, "runtime_adapter": runtime_adapter.value}
                if reasoning_effort is not None:
                    run_options["reasoning_effort"] = reasoning_effort
            before_create()
            screenshots = load_screenshots() if load_screenshots else []
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
            if screenshots:
                run_options["pending_user_artifact_ids"] = _stage_screenshots(Task.objects.get(id=task.id), screenshots)
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
