from uuid import UUID, uuid5

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.models import Team, User

from products.meep.backend.board import check_child_capacity
from products.meep.backend.chat import check_access
from products.meep.backend.delegation import _parent
from products.meep.backend.models import BoardRun
from products.meep.backend.replication import apply_command
from products.tasks.backend.facade import api


@transaction.atomic
def answer_child(
    team: Team,
    user: User,
    parent_task_id: UUID,
    topic_id: UUID,
    request_id: UUID,
    item_id: UUID,
    answer: str,
    question_run_id: UUID,
    parent_run_id: UUID,
) -> dict[str, str]:
    topic = _parent(team, user, parent_task_id, topic_id, parent_run_id)
    replay_key = uuid5(request_id, f"answer:{item_id}:{question_run_id}:{answer}")
    previous = topic.board_runs.filter(request_id=replay_key).first()
    if previous:
        return {"item_id": str(previous.item_id), "task_id": str(previous.task_id), "run_id": str(previous.run_id)}

    job = topic.board_runs.filter(item_id=item_id).order_by("-id").first()
    if job is None or job.parent_turn_id is None or not job.finished or job.run_id != question_run_id:
        raise ValidationError("This task is no longer waiting for that answer.")
    run = api.get_task_run(job.run_id, team.pk)
    if (
        run is None
        or run.task_id != job.task_id
        or run.status != "completed"
        or not isinstance(run.output, dict)
        or run.output.get("needs_input") is not True
    ):
        raise ValidationError("This task has no question to answer.")
    item = next((item for item in topic.state["tasks"] if item["id"] == str(item_id)), None)
    if item is None or item["column"] != "NeedsYou" or item.get("action") is not None:
        raise ValidationError("Open the task to review its current state.")

    check_child_capacity(topic)
    check_access(team, user)
    apply_command(
        team.pk, user, replay_key, topic_id, {"kind": "MoveTask", "task": str(item_id), "column": "InProgress"}
    )
    result = api.run_task(
        job.task_id,
        team.pk,
        user.pk,
        validated_data={"resume_from_run_id": str(job.run_id), "pending_user_message": answer, "mode": "background"},
    )
    if result is None or result.run_id is None:
        raise ValidationError("The task could not resume. Try again.")
    BoardRun.objects.create(
        topic=topic,
        parent_turn_id=job.parent_turn_id,
        item_id=item_id,
        task_id=job.task_id,
        run_id=result.run_id,
        request_id=replay_key,
    )
    return {"item_id": str(item_id), "task_id": str(job.task_id), "run_id": str(result.run_id)}
