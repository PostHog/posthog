import json
from uuid import UUID, uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404

import requests
from pydantic import JsonValue
from rest_framework.exceptions import NotFound, ValidationError

from posthog.models import User

from products.meep.backend.chat import check_access, environment
from products.meep.backend.domain import transition
from products.meep.backend.models import BoardRun, ChatTurn, CommandReceipt, Topic
from products.meep.backend.task_profiles import MEEP, MEEP_MCP_SCOPES, agent_instructions
from products.tasks.backend.facade import api
from products.tasks.backend.facade.profiles import TaskRunOptions


def task_conversation(team_id: int, owner_id: int, topic_id: UUID, item_id: UUID) -> dict[str, JsonValue]:
    topic = get_object_or_404(Topic.objects.for_team(team_id), pk=topic_id, owner_id=owner_id, deleted=False)
    item = next((item for item in topic.state.get("tasks", []) if item["id"] == str(item_id)), None)
    if item is None:
        raise NotFound()
    jobs = list(topic.board_runs.filter(item_id=item_id).order_by("id"))
    seen_tasks = set()
    attempts = []
    status = ""
    for job in jobs:
        run = api.get_task_run(job.run_id, team_id)
        if run is None or run.task_id != job.task_id or run.created_by_id != owner_id:
            continue
        if not run.is_terminal:
            api.mark_task_run_stream_watched(job.run_id, job.task_id, team_id)
        events = api.read_task_run_history(job.run_id, job.task_id, team_id, max_bytes=None, include_ancestors=False)
        output = run.output if isinstance(run.output, dict) else {}
        attempts.append(
            {
                "id": str(run.id),
                "started_at": run.created_at.isoformat() if run.created_at else None,
                "finished_at": run.completed_at.isoformat() if run.completed_at else None,
                "initial": job.task_id not in seen_tasks,
                "logs": api.thread_view_of_log_content(
                    "\n".join(
                        json.dumps(event)
                        for event in events or []
                        if isinstance(notification := event.get("notification"), dict)
                        and notification.get("method")
                        in {
                            "session/prompt",
                            "session/update",
                            "_posthog/user_message",
                            "_posthog/run_started",
                            "_posthog/turn_complete",
                        }
                    )
                ),
                "reply": output.get("reply") if isinstance(output.get("reply"), str) else None,
                "followup": run.state.get("pending_user_message"),
                "status": run.status,
            }
        )
        seen_tasks.add(job.task_id)
        if job == jobs[-1]:
            status = run.status
    return {"status": status, "brief": item.get("instructions") or item["title"], "attempts": attempts}


@transaction.atomic
def send_task_message(team_id: int, owner_id: int, topic_id: UUID, item_id: UUID, text: str, model: str | None) -> None:
    owner = User.objects.select_for_update().get(pk=owner_id)
    topic = get_object_or_404(
        Topic.objects.for_team(team_id).select_for_update(),
        pk=topic_id,
        owner_id=owner_id,
        deleted=False,
        archived=False,
    )
    if not any(item["id"] == str(item_id) for item in topic.state.get("tasks", [])):
        raise NotFound()
    job = topic.board_runs.filter(item_id=item_id).order_by("-id").first()
    if job is None:
        raise ValidationError("Start the task before sending a message.")
    check_access(topic.team, owner)
    run = api.get_task_run(job.run_id, team_id)
    if run is None or run.task_id != job.task_id or run.created_by_id != owner_id:
        raise NotFound()
    if not run.is_terminal:
        if model and model != run.state.get("model"):
            raise ValidationError("Wait for the current run to finish before changing its model.")
        if api.signal_task_run_user_message(
            job.run_id, job.task_id, team_id, content=text, artifact_ids=[], actor_user_id=owner_id
        ):
            return
        raise ValidationError("The run just stopped. Try sending the message again.")
    finish_board(job.run_id, team_id)
    if job.parent_turn_id:
        check_child_capacity(topic)
    from products.meep.backend.replication import apply_command  # noqa: PLC0415 — replication imports board actions

    apply_command(team_id, owner, uuid4(), topic_id, {"kind": "MoveTask", "task": str(item_id), "column": "InProgress"})
    result = api.run_task(
        job.task_id,
        team_id,
        owner_id,
        validated_data={
            "resume_from_run_id": str(job.run_id),
            "pending_user_message": text,
            "mode": "background",
            **({"model": model} if model else {}),
        },
    )
    if result is None or result.run_id is None:
        raise ValidationError("Couldn’t resume the task.")
    BoardRun.objects.create(
        topic=topic, item_id=item_id, task_id=job.task_id, run_id=result.run_id, parent_turn_id=job.parent_turn_id
    )


def check_child_capacity(topic: Topic) -> None:
    live = BoardRun.objects.filter(
        topic__team_id=topic.team_id, topic__owner_id=topic.owner_id, parent_turn__isnull=False, finished=False
    )
    if live.count() >= 3:
        raise ValidationError("Three delegated tasks are already running. Wait for one to finish.")


def apply_board_action(topic: Topic, state: dict, command: dict, *, delegated_parent: ChatTurn | None = None) -> dict:
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
    if delegated_parent:
        check_child_capacity(topic)
    check_access(topic.team, topic.owner)
    state = transition("board", state, {"id": item_id, "text": "Starting PostHog task", "stage": "start"})
    created = api.create_and_run_task(
        team=topic.team,
        user_id=topic.owner_id,
        profile=MEEP,
        create_pr=False,
        title=item["title"],
        description=(
            f"{agent_instructions()}\n\nInvestigate this board task for topic {topic.pk}.\nMission: {topic.mission}\n"
            f"{item['title']}\n{item.get('instructions') or ''}\nReturn your findings in reply."
            + (" Set needs_input to true if you need an answer before you can continue." if delegated_parent else "")
        ),
        sandbox_environment_id=str(environment(topic.team_id)),
        extra_run_state={
            "meep_board_item": item_id,
            **(
                {
                    "agent_parent_task_id": str(topic.conversation_id),
                    "agent_parent_run_id": str(delegated_parent.run_id),
                }
                if delegated_parent
                else {}
            ),
        },
        options=TaskRunOptions(
            mcp_scopes=[scope for scope in MEEP_MCP_SCOPES if scope != "meep_task:write"],
            model=item.get("model"),
            reasoning_effort=item.get("reasoning_effort"),
            output_schema={
                "type": "object",
                "properties": {
                    "reply": {"type": "string"},
                    **({"needs_input": {"type": "boolean"}} if delegated_parent else {}),
                },
                "required": ["reply", "needs_input"] if delegated_parent else ["reply"],
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
    output = run.output if isinstance(run.output, dict) else {}
    reply = output.get("reply")
    success = (
        run.status == "completed" and isinstance(reply, str) and bool(reply.strip()) and not output.get("needs_input")
    )
    topic.state = transition(
        "board",
        topic.state,
        {
            "id": job.item_id,
            "stage": "done" if success else "failed",
            "text": reply
            if isinstance(reply, str) and reply.strip()
            else run.error_message or f"Run {run.status} without findings.",
        },
    )
    topic.revision += 1
    topic.save(update_fields=["state", "revision"])
    CommandReceipt.objects.create(topic=topic, command_id=uuid4(), revision=topic.revision)
    if job.parent_turn_id:
        from products.meep.backend.tasks import reconcile_topic_tasks  # noqa: PLC0415

        transaction.on_commit(lambda: reconcile_topic_tasks.delay(team_id, str(topic.pk)), robust=True)


def topic_artifacts(team_id: int, owner_id: int, topic_id: UUID) -> list[dict[str, JsonValue]]:
    topic = get_object_or_404(Topic.objects.for_team(team_id), pk=topic_id, owner_id=owner_id, deleted=False)
    rows: list[dict[str, JsonValue]] = []
    for job in topic.board_runs.order_by("id"):
        run = api.get_task_run(job.run_id, team_id)
        if run is None or run.created_by_id != owner_id:
            continue
        for artifact in run.artifacts or []:
            if not isinstance(artifact, dict) or not artifact.get("storage_path"):
                continue
            rows.append(
                {
                    "task": str(job.item_id),
                    "run": str(job.run_id),
                    "id": str(artifact["id"]),
                    "name": str(artifact.get("name") or "file"),
                    "kind": str(artifact.get("type") or "output"),
                    "version": 0,
                    "size": artifact.get("size") if isinstance(artifact.get("size"), int) else None,
                    "content_type": artifact.get("content_type"),
                    "updated_at": artifact.get("uploaded_at"),
                }
            )
    return rows


def read_topic_artifact(
    team_id: int, owner_id: int, topic_id: UUID, item_id: UUID, run_id: UUID, artifact_id: str, max_bytes: int
) -> tuple[bytes, str] | None:
    topic = get_object_or_404(Topic.objects.for_team(team_id), pk=topic_id, owner_id=owner_id, deleted=False)
    job = topic.board_runs.filter(item_id=item_id, run_id=run_id).first()
    if job is None:
        raise NotFound()
    url, error = api.presign_task_run_artifact_download(run_id, job.task_id, team_id, artifact_id=artifact_id)
    if url is None:
        raise NotFound()
    response = requests.get(url, timeout=20, stream=True)
    response.raise_for_status()
    declared = response.headers.get("content-length")
    if declared and int(declared) > max_bytes:
        return None
    data = response.raw.read(max_bytes + 1, decode_content=True)
    if len(data) > max_bytes:
        return None
    return data, response.headers.get("content-type") or "application/octet-stream"
