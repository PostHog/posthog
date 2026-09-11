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
            result = api.run_task(task.id, team_id, user_id, validated_data={})
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
