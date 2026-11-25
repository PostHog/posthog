from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models import User

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
    if topic is None:
        if Topic.objects.unscoped().filter(pk=topic_id).exists():
            raise ValidationError("Topic unavailable.")
        topic = Topic(id=topic_id, team_id=team_id, owner=owner)
    else:
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
    CommandReceipt.objects.create(command_id=command_id, topic=topic, revision=topic.revision)
    return {"status": "applied", "id": command_id, "topic": topic_id, "revision": topic.revision}
