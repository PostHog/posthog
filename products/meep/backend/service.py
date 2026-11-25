from uuid import UUID, uuid4

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Max, QuerySet
from django.shortcuts import get_object_or_404

from pydantic import JsonValue
from rest_framework.exceptions import NotFound, ValidationError

from posthog.models import User

from products.meep.backend import authoring, replication
from products.meep.backend.chat import finish_turn
from products.meep.backend.domain import transition
from products.meep.backend.facade.contracts import FileData, TopicDetails
from products.meep.backend.files import write_file
from products.meep.backend.import_workspace import import_workspace as import_workspace
from products.meep.backend.models import (
    ChatTurn,
    CommandReceipt,
    DeletionReceipt,
    Topic,
    ViewJob,
    ViewReceipt,
    WorkspaceView,
)
from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.facade.api import task_owned_by_user
from products.tasks.backend.facade.model_catalogue import TASK_RUN_GATEWAY_PRODUCT, available_model_choices


def _topics(team_id: int, owner_id: int) -> QuerySet[Topic]:
    return Topic.objects.for_team(team_id).filter(owner_id=owner_id)


def _details(topic: Topic) -> TopicDetails:
    return TopicDetails(
        id=topic.pk,
        title=topic.title,
        mission=topic.mission,
        conversation_id=topic.conversation_id,
        created_at=topic.created_at,
    )


def list_topics(team_id: int, owner_id: int, conversation: UUID | None) -> list[TopicDetails]:
    topics = _topics(team_id, owner_id).filter(archived=False, deleted=False)
    if conversation is not None:
        topics = topics.filter(conversation_id=conversation)
    return [_details(t) for t in topics]


def read_topic(team_id: int, owner_id: int, topic_id: UUID, conversation: UUID | None) -> TopicDetails:
    topics = _topics(team_id, owner_id).filter(archived=False, deleted=False)
    if conversation is not None:
        topics = topics.filter(conversation_id=conversation)
    return _details(get_object_or_404(topics, pk=topic_id))


@transaction.atomic
def create_topic(team_id: int, owner_id: int, title: str, mission: str) -> TopicDetails:
    User.objects.select_for_update().only("pk").get(pk=owner_id)
    topic = Topic.objects.for_team(team_id).create(team_id=team_id, owner_id=owner_id, title=title, mission=mission)
    CommandReceipt.objects.create(command_id=uuid4(), topic=topic, revision=topic.revision)
    return _details(topic)


@transaction.atomic
def bind_conversation(team_id: int, owner_id: int, topic_id: UUID, task_id: UUID) -> TopicDetails:
    topic = get_object_or_404(
        _topics(team_id, owner_id).select_for_update(), pk=topic_id, deleted=False, archived=False
    )
    if topic.conversation_id == task_id:
        return _details(topic)
    if topic.conversation_id or not task_owned_by_user(task_id, team_id, owner_id):
        raise ValidationError("This task cannot be bound to the topic.")
    try:
        with transaction.atomic():
            topic.conversation_id = task_id
            topic.save(update_fields=["conversation_id"])
    except IntegrityError as error:
        raise ValidationError("This task is already bound to a topic.") from error
    return _details(topic)


def cursor(team_id: int, owner_id: int) -> int:
    return (
        CommandReceipt.objects.filter(topic__in=_topics(team_id, owner_id)).aggregate(latest=Max("id"))["latest"] or 0
    )


def command(
    team_id: int, owner_id: int, command_id: UUID, topic_id: UUID, body: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    return replication.apply_command(team_id, User.objects.get(pk=owner_id), command_id, topic_id, body)


def changes(team_id: int, owner_id: int, after: int) -> dict[str, JsonValue]:
    topics = _topics(team_id, owner_id)
    if cache.add(f"meep:reconcile:{team_id}:{owner_id}", 1, timeout=60):
        for run_id in ChatTurn.objects.filter(topic__in=topics, finished_at=None).values_list("run_id", flat=True):
            finish_turn(run_id, team_id)
        for run_id in ViewJob.objects.filter(
            view__team_id=team_id, view__owner_id=owner_id, finished=False
        ).values_list("run_id", flat=True):
            authoring.finish_view(run_id, team_id)
    entries = list(
        CommandReceipt.objects.filter(topic__in=topics, pk__gt=after).order_by("pk").values_list("pk", "topic_id")[:65]
    )
    page = entries[:64]
    return {
        "topics": [replication.snapshot(t) for t in topics.filter(pk__in=[i for _, i in page])],
        "cursor": page[-1][0] if page else after,
        "more": len(entries) > 64,
    }


def topic_snapshot(team_id: int, owner_id: int, topic_id: UUID) -> dict[str, JsonValue]:
    return replication.snapshot(get_object_or_404(_topics(team_id, owner_id), pk=topic_id))


def grants(team_id: int, owner_id: int) -> list[str]:
    return [str(pk) for pk in _topics(team_id, owner_id).filter(deleted=False).values_list("pk", flat=True)]


def views(team_id: int, owner_id: int) -> list[dict[str, JsonValue]]:
    return list(WorkspaceView.objects.for_team(team_id).filter(owner_id=owner_id).values_list("state", flat=True))


@transaction.atomic
def edit_view(
    team_id: int, owner_id: int, view_id: UUID, command_id: UUID, envelope: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    User.objects.select_for_update().only("pk").get(pk=owner_id)
    view = WorkspaceView.objects.for_team(team_id).filter(pk=view_id, owner_id=owner_id).first()
    if view and ViewReceipt.objects.filter(view=view, command_id=command_id).exists():
        return view.state
    state = transition("view", view.state if view else None, envelope)
    if view is None:
        if WorkspaceView.objects.unscoped().filter(pk=view_id).exists():
            raise ValidationError("View unavailable.")
        view = WorkspaceView(id=view_id, team_id=team_id, owner_id=owner_id)
    view.state = state
    view.save(force_insert=view._state.adding)
    ViewReceipt.objects.create(view=view, command_id=command_id)
    if envelope.get("command", {}).get("kind") in ("delete", "stop"):
        for job in view.jobs.filter(finished=False):
            if state["deleted"] or any(turn["id"] == str(job.turn_id) and turn.get("stop") for turn in state["turns"]):
                transaction.on_commit(lambda run_id=job.run_id: tasks_api.send_cancel(run_id), robust=True)
    authoring.advance(view)
    return view.state


@transaction.atomic
def acknowledge(team_id: int, owner_id: int, replica: UUID, revisions: dict[UUID, int]) -> None:
    for pk, revision in revisions.items():
        topic = get_object_or_404(_topics(team_id, owner_id), pk=pk, deleted=True, revision=revision)
        DeletionReceipt.objects.get_or_create(topic=topic, replica=replica, defaults={"revision": revision})


def files(team_id: int, owner_id: int, topic_id: UUID) -> list[str]:
    topic = get_object_or_404(_topics(team_id, owner_id), pk=topic_id, deleted=False)
    return list(
        topic.files.exclude(path__in=topic.state.get("deleted_files", {}))
        .order_by("path")
        .values_list("path", flat=True)
        .distinct()
    )


def read_file(team_id: int, owner_id: int, topic_id: UUID, path: str, revision: int | None) -> FileData:
    topic = get_object_or_404(_topics(team_id, owner_id), pk=topic_id, deleted=False)
    versions = topic.files.filter(path=path)
    if revision is not None:
        file = get_object_or_404(versions, revision=revision)
    else:
        file = versions.filter(competing_with=None).order_by("-revision").first()
        if path in topic.state.get("deleted_files", {}) or file is None:
            raise NotFound()
    return FileData(contents=bytes(file.contents), revision=file.revision, competing_with=file.competing_with)


@transaction.atomic
def upload(
    team_id: int, owner_id: int, topic_id: UUID, path: str, contents: bytes, key: UUID, base: int | None
) -> FileData:
    User.objects.select_for_update().only("pk").get(pk=owner_id)
    topic = get_object_or_404(_topics(team_id, owner_id), pk=topic_id, deleted=False, archived=False)
    file = write_file(topic, replication.snapshot(topic)["state"], path, contents, key, base)
    return FileData(contents=bytes(file.contents), revision=file.revision, competing_with=file.competing_with)


def chat_models(
    team_id: int, owner_id: int, topic_id: UUID | None, update: bool, selected: str | None, billing: str | None
) -> dict[str, JsonValue]:
    topic = get_object_or_404(_topics(team_id, owner_id), pk=topic_id, deleted=False) if topic_id else None
    choices = available_model_choices(TASK_RUN_GATEWAY_PRODUCT)
    if update:
        if topic is None or (selected and selected not in {c.model for c in choices}):
            raise ValidationError("Select an available model.")
        if billing not in (None, "posthog-gateway"):
            raise ValidationError("Meep runs use the PostHog gateway.")
        topic.chat_model = selected or ""
        topic.save(update_fields=["chat_model"])
    return {
        "models": [
            {
                "id": c.model,
                "name": c.label,
                "runtime": c.runtime_adapter,
                "supported_efforts": list(c.supported_efforts),
                "meep_tools": True,
            }
            for c in choices
        ],
        "selected": topic.chat_model if topic and topic.chat_model else None,
        "billing": "posthog-gateway",
    }


def topic_context(team_id: int, owner_id: int, topic_id: UUID, conversation: UUID | None) -> dict[str, JsonValue]:
    read_topic(team_id, owner_id, topic_id, conversation)
    state = topic_snapshot(team_id, owner_id, topic_id)["state"]
    return {k: state["topic"][k] for k in ("goals", "facts", "rules", "context_sources")}


def view_source(team_id: int, owner_id: int, view_id: UUID, topic_id: UUID, tool: str, path: str | None) -> JsonValue:
    get_object_or_404(WorkspaceView.objects.for_team(team_id), pk=view_id, owner_id=owner_id, state__deleted=False)
    state = topic_snapshot(team_id, owner_id, topic_id)["state"]
    if tool == "routine_data":
        return state.get("view_data", {}).get(str(view_id))
    if tool == "files":
        return list(files(team_id, owner_id, topic_id))
    if tool == "file" and path:
        return read_file(team_id, owner_id, topic_id, path, None).contents.decode()
    if tool not in ("tasks", "threads", "facts"):
        raise ValidationError("Unknown topic collection.")
    return transition("topic-rows", state, {"tool": tool})["rows"]
