from uuid import UUID, uuid4

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.models import User

from products.meep.backend.chat import check_access, environment
from products.meep.backend.domain import transition
from products.meep.backend.models import BoardRun, CommandReceipt, Topic
from products.meep.backend.task_profiles import MEEP
from products.tasks.backend.facade import api
from products.tasks.backend.facade.profiles import TaskRunOptions


def apply_board_action(topic: Topic, state: dict, command: dict) -> dict:
    kind = command["kind"]
    item_id = command.get("task", command.get("id"))
    if kind in ("DeleteTopic", "ArchiveTopic", "DeleteTask", "CancelRun"):
        jobs = topic.board_runs.filter(finished=False)
        if kind in ("DeleteTask", "CancelRun"):
            jobs = jobs.filter(item_id=item_id)
        for job in jobs:
            transaction.on_commit(lambda run_id=job.run_id: api.send_cancel(run_id), robust=True)
            job.finished = True
            job.save(update_fields=["finished"])
        return state
    if kind not in ("StartTask", "StartTaskWithInput", "AddConfiguredTask") or command.get("start") is False:
        return state
    item = next(t for t in state["tasks"] if t["id"] == item_id)
    if item.get("billing") == "own-subscription":
        raise ValidationError("Select PostHog gateway billing for this task.")
    check_access(topic.team, topic.owner)
    state = transition("board", state, {"id": item_id, "text": "Starting PostHog task", "stage": "start"})
    created = api.create_and_run_task(
        team=topic.team,
        user_id=topic.owner_id,
        profile=MEEP,
        create_pr=False,
        title=item["title"],
        description=f"Use working-with-meep to investigate this board task for topic {topic.pk}.\nMission: {topic.mission}\n{item['title']}\n{item.get('instructions') or ''}\nReturn your findings in reply.",
        sandbox_environment_id=str(environment(topic.team_id)),
        extra_run_state={"meep_board_item": item_id},
        options=TaskRunOptions(
            model=item.get("model"),
            reasoning_effort=item.get("reasoning_effort"),
            output_schema={
                "type": "object",
                "properties": {"reply": {"type": "string"}},
                "required": ["reply"],
                "additionalProperties": False,
            },
        ),
    )
    if not created.latest_run:
        raise RuntimeError("PostHog did not create the board run.")
    BoardRun.objects.create(topic=topic, item_id=item_id, task_id=created.task_id, run_id=created.latest_run.id)
    return state


@transaction.atomic
def finish_board(run_id: UUID, team_id: int) -> None:
    job = BoardRun.objects.select_related("topic").filter(run_id=run_id, topic__team_id=team_id, finished=False).first()
    if not job:
        return
    run = api.get_task_run(run_id, team_id)
    if not run or not run.is_terminal or run.task_id != job.task_id:
        return
    User.objects.select_for_update().only("pk").get(pk=job.topic.owner_id)
    if not BoardRun.objects.filter(pk=job.pk, finished=False).update(finished=True):
        return
    topic = Topic.objects.for_team(team_id).select_for_update().get(pk=job.topic_id)
    if (
        topic.deleted
        or topic.archived
        or not any(t["id"] == str(job.item_id) and t["column"] == "InProgress" for t in topic.state["tasks"])
    ):
        return
    reply = (run.output or {}).get("reply")
    success = run.status == "completed" and isinstance(reply, str) and bool(reply.strip())
    topic.state = transition(
        "board",
        topic.state,
        {
            "id": job.item_id,
            "stage": "done" if success else "failed",
            "text": reply if success else run.error_message or f"Run {run.status} without findings.",
        },
    )
    topic.revision += 1
    topic.save(update_fields=["state", "revision"])
    CommandReceipt.objects.create(topic=topic, command_id=uuid4(), revision=topic.revision)
