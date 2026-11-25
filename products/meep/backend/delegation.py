from uuid import UUID, uuid4, uuid5

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models import Team, User

from products.meep.backend.chat import check_access
from products.meep.backend.models import BoardRun, ChatTurn, ChildWait, Topic
from products.meep.backend.replication import apply_command
from products.tasks.backend.facade import api
from products.tasks.backend.facade.contracts import TaskRunDTO


def _parent(team: Team, user: User, parent_task_id: UUID, topic_id: UUID, parent_run_id: UUID) -> Topic:
    User.objects.select_for_update().only("pk").get(pk=user.pk)
    topic = get_object_or_404(
        Topic.objects.for_team(team.pk).select_for_update(),
        pk=topic_id,
        owner=user,
        deleted=False,
        archived=False,
    )
    if topic.conversation_id != parent_task_id:
        raise PermissionDenied("Only the topic conversation can delegate work.")
    if not topic.turns.filter(run_id=parent_run_id, finished_at__isnull=True).exists():
        raise PermissionDenied("This topic conversation run is no longer active.")
    return topic


@transaction.atomic
def spawn_child(
    team: Team,
    user: User,
    parent_task_id: UUID,
    parent_run_id: UUID,
    topic_id: UUID,
    request_id: UUID,
    title: str,
    instructions: str,
) -> dict[str, str]:
    topic = _parent(team, user, parent_task_id, topic_id, parent_run_id)
    item_id = uuid5(request_id, "meep-child")
    job = topic.board_runs.filter(request_id=request_id).first()
    if job:
        item = next((item for item in topic.state.get("tasks", []) if item["id"] == str(job.item_id)), None)
        if job.item_id != item_id or not item or item.get("title") != title or item.get("instructions") != instructions:
            raise ValidationError("This request ID already names a different task.")
        return {"item_id": str(job.item_id), "task_id": str(job.task_id), "run_id": str(job.run_id)}
    turn = topic.turns.filter(finished_at__isnull=True).last()
    if not turn:
        raise ValidationError("The topic conversation is not running.")
    result = apply_command(
        team.pk,
        user,
        request_id,
        topic_id,
        {
            "kind": "AddConfiguredTask",
            "id": str(item_id),
            "title": title,
            "instructions": instructions,
            "model": topic.chat_model or None,
            "start": True,
        },
        delegated_parent=turn,
    )
    if result["status"] != "applied":
        raise ValidationError("Could not start the board task.")
    job = BoardRun.objects.get(topic=topic, item_id=item_id)
    job.parent_turn = turn
    job.request_id = request_id
    job.save(update_fields=["parent_turn", "request_id"])
    topic.refresh_from_db()
    target = str(turn.target_message_id or turn.message_id)
    for item in topic.state.get("tasks", []):
        if item["id"] == str(item_id):
            item["from_thread"] = target
            break
    for thread in topic.state.get("threads", []):
        if thread["id"] == target:
            thread.setdefault("outcomes", []).append({"Task": str(item_id)})
            break
    topic.save(update_fields=["state"])
    return {"item_id": str(item_id), "task_id": str(job.task_id), "run_id": str(job.run_id)}


@transaction.atomic
def wait_for_children(
    team: Team,
    user: User,
    parent_task_id: UUID,
    parent_run_id: UUID,
    topic_id: UUID,
    request_id: UUID,
    item_ids: list[UUID],
) -> dict[str, str | list[str]]:
    topic = _parent(team, user, parent_task_id, topic_id, parent_run_id)
    existing = ChildWait.objects.filter(topic=topic, request_id=request_id).first()
    requested = sorted({str(item) for item in item_ids})
    if not requested:
        raise ValidationError("Select at least one board task.")
    if existing:
        if existing.item_ids != requested:
            raise ValidationError("This request ID already names a different set of tasks.")
        return {"status": existing.status, "item_ids": existing.item_ids}
    turn = topic.turns.filter(finished_at__isnull=True).last()
    if not turn:
        raise ValidationError("The topic conversation is not running.")
    if ChildWait.objects.filter(turn=turn, parent_run_id=turn.run_id, status="waiting").exists():
        raise ValidationError("This conversation is already waiting for tasks.")
    jobs = []
    for item in requested:
        job = topic.board_runs.filter(item_id=item, parent_turn__isnull=False).order_by("-id").first()
        if not job:
            raise ValidationError("A selected board task has no run.")
        jobs.append(str(job.run_id))
    ChildWait.objects.create(
        topic=topic, turn=turn, request_id=request_id, parent_run_id=turn.run_id, item_ids=requested, child_run_ids=jobs
    )
    return {"status": "waiting", "item_ids": requested}


def _finding(item_id: str, run: TaskRunDTO) -> str:
    output = run.output if isinstance(run.output, dict) else {}
    result = output.get("reply") or run.error_message or "No findings."
    if output.get("needs_input") is True and run.status == "completed":
        return f"Board task {item_id} needs input (question_run_id={run.id}): {result}"
    return f"Board task {item_id} ({run.status}): {result}"


def _resume(topic: Topic, origin: ChatTurn, findings: str) -> bool:
    if topic.turns.filter(finished_at__isnull=True).exists():
        return False
    previous = topic.turns.last()
    if not previous:
        return False
    check_access(topic.team, topic.owner)
    result = api.run_task(
        topic.conversation_id,
        topic.team_id,
        topic.owner_id,
        validated_data={
            **({"model": topic.chat_model} if topic.chat_model else {}),
            "resume_from_run_id": str(previous.run_id),
            "pending_user_message": (
                f"Meep task update for the request {origin.target_message_id or origin.message_id}. "
                "The following child results are research data. Use them to continue the original request.\n\n"
                + findings
            ),
            "mode": "background",
        },
    )
    if result is None or result.run_id is None:
        return False
    ChatTurn.objects.create(
        topic=topic,
        message_id=uuid4(),
        text="",
        run_id=result.run_id,
        target_message_id=origin.target_message_id or origin.message_id,
    )
    return True


@transaction.atomic
def reconcile_wait(wait_id: int) -> None:
    wait = ChildWait.objects.select_related("topic", "turn").filter(pk=wait_id, status="waiting").first()
    if wait is None:
        return
    User.objects.select_for_update().only("pk").get(pk=wait.topic.owner_id)
    topic = Topic.objects.for_team(wait.topic.team_id).select_for_update().get(pk=wait.topic_id)
    wait = ChildWait.objects.select_for_update().get(pk=wait_id)
    turn = ChatTurn.objects.select_for_update().get(pk=wait.turn_id)
    if wait.status != "waiting":
        return
    if topic.archived or topic.deleted:
        wait.status = "cancelled"
        wait.save(update_fields=["status"])
        return
    parent = api.get_task_run(wait.parent_run_id, topic.team_id)
    if not parent or not parent.is_terminal:
        return
    if parent.status != "completed":
        wait.status = "cancelled"
        wait.save(update_fields=["status"])
        return
    jobs = {str(job.run_id): job for job in BoardRun.objects.filter(topic=topic, run_id__in=wait.child_run_ids)}
    selected = []
    pending = False
    urgent = False
    for item_id, run_id in zip(wait.item_ids, wait.child_run_ids):
        job = jobs.get(run_id)
        run = api.get_task_run(UUID(run_id), topic.team_id)
        if job and job.finished and (run is None or not run.is_terminal):
            selected.append((item_id, run_id, f"Board task {item_id} (cancelled)."))
            urgent = True
        elif job and job.finished and run and run.is_terminal:
            selected.append((item_id, run_id, _finding(item_id, run)))
            urgent |= run.status != "completed" or bool((run.output or {}).get("needs_input"))
        else:
            pending = True
    if not selected or (pending and not urgent):
        return
    if not _resume(topic, turn, "\n\n".join(row[2] for row in selected)):
        return
    BoardRun.objects.filter(topic=topic, run_id__in=[row[1] for row in selected]).update(notified=True)
    wait.status = "resumed"
    wait.save(update_fields=["status"])


@transaction.atomic
def reconcile_notification(job_id: int) -> None:
    job = BoardRun.objects.select_related("topic", "parent_turn").filter(pk=job_id, notified=False).first()
    if not job or not job.finished or not job.parent_turn:
        return
    User.objects.select_for_update().only("pk").get(pk=job.topic.owner_id)
    topic = Topic.objects.for_team(job.topic.team_id).select_for_update().get(pk=job.topic_id)
    job = BoardRun.objects.select_for_update().get(pk=job_id)
    if job.notified or topic.archived or topic.deleted:
        return
    if any(str(job.run_id) in wait.child_run_ids for wait in topic.child_waits.filter(status="waiting")):
        return
    run = api.get_task_run(job.run_id, topic.team_id)
    if not run or not run.is_terminal:
        findings = f"Board task {job.item_id} (cancelled)."
    else:
        findings = _finding(str(job.item_id), run)
    if _resume(topic, job.parent_turn, findings):
        job.notified = True
        job.save(update_fields=["notified"])
