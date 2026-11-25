from typing import Any
from uuid import UUID, uuid5

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models import User

from products.meep.backend.board import apply_board_action
from products.meep.backend.chat import start_turn
from products.meep.backend.domain import transition
from products.meep.backend.files import choose_revision
from products.meep.backend.models import CommandReceipt, Topic


def snapshot(topic: Topic) -> dict[str, Any]:
    state = topic.state or transition(
        "topic",
        None,
        {
            "id": topic.pk,
            "topic": topic.pk,
            "issued_at": topic.created_at,
            "command": {"kind": "CreateTopicWithoutSort", "name": topic.title, "mission": topic.mission},
        },
    )
    return {"revision": topic.revision, "state": state}


@transaction.atomic
def apply_command(
    team_id: int, owner: User, command_id: UUID, topic_id: UUID, command: dict[str, Any]
) -> dict[str, Any]:
    User.objects.select_for_update().only("pk").get(pk=owner.pk)
    topic = Topic.objects.for_team(team_id).filter(owner=owner, pk=topic_id).first()
    receipt = CommandReceipt.objects.filter(topic=topic, command_id=command_id).first() if topic else None
    if receipt:
        return {"status": "applied", "id": command_id, "topic": topic_id, "revision": receipt.revision}

    state = transition(
        "topic",
        snapshot(topic)["state"] if topic else None,
        {
            "id": command_id,
            "topic": topic_id,
            "issued_at": timezone.now(),
            "command": command,
        },
    )
    title = state["topic"]["name"]
    if not state["deleted"] and (not title.strip() or len(title) > 255):
        raise ValidationError("Supply a topic title of up to 255 characters.")
    created = topic is None
    if topic is None:
        if Topic.objects.unscoped().filter(pk=topic_id).exists():
            raise ValidationError("Topic unavailable.")
        topic = Topic(id=topic_id, team_id=team_id, owner=owner)
    else:
        state = apply_board_action(topic, state, command)
        if command.get("kind") == "Answer":
            choose_revision(topic, state, command, command_id)
        if command.get("kind") == "Chat":
            text = command["text"]
            if not text.strip() or len(text) > 32000:
                raise ValidationError("Send a message between 1 and 32000 characters.")
            if not start_turn(topic, owner, UUID(command["message_id"]), text):
                return {"status": "retry", "id": command_id, "reason": "Waiting for the current turn."}
        topic.revision += 1
    topic.title = title
    topic.mission = state["topic"]["mission"]
    topic.archived = state["archived"]
    topic.deleted = state["deleted"]
    topic.state = state
    topic.save(force_insert=topic._state.adding)
    if created and command["kind"] == "CreateTopic" and topic.mission.strip():
        # Provisioning is part of the accepted command and therefore shares its replay identity.
        message_id = uuid5(command_id, "mission")
        initial = {
            "kind": "Chat",
            "message_id": str(message_id),
            "task_id": str(uuid5(command_id, "setup-task")),
            "text": topic.mission,
        }
        state = transition(
            "topic", state, {"topic": topic_id, "id": message_id, "issued_at": timezone.now(), "command": initial}
        )
        try:
            with transaction.atomic():
                start_turn(topic, owner, message_id, topic.mission)
        except ValidationError as error:
            thread = next(t for t in state["threads"] if t["id"] == str(message_id))
            thread["state"] = "Handled"
            thread["outcomes"] = [{"Reply": {"to": "User", "text": str(error.detail)}}]
        topic.state = state
        topic.save(update_fields=["state"])
    CommandReceipt.objects.create(command_id=command_id, topic=topic, revision=topic.revision)
    return {"status": "applied", "id": command_id, "topic": topic_id, "revision": topic.revision}
