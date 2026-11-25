from typing import Any
from uuid import UUID

from rest_framework.exceptions import ValidationError

from products.meep.backend.domain import transition
from products.meep.backend.models import CommandReceipt, FileRevision, Topic


def write_file(topic: Topic, state: dict, path: str, data: bytes, operation: UUID, base: int | None) -> FileRevision:
    versions = topic.files.filter(path=path)
    replay = versions.filter(operation=operation).first()
    if replay:
        if bytes(replay.contents) != data or base != replay.base:
            raise ValidationError("File operation already used with different contents.")
        return replay
    latest = versions.order_by("-revision").first()
    revision = latest.revision + 1 if latest else 1
    head = versions.filter(competing_with=None).order_by("-revision").first()
    head_revision = head.revision if head else 0
    if base is not None and base > 0 and not versions.filter(revision=base).exists():
        raise ValidationError("Unknown file base revision.")
    competing = head_revision if head and base is not None and base != head_revision else None
    file = versions.create(
        topic=topic,
        path=path,
        contents=data,
        operation=operation,
        base=base,
        revision=revision,
        competing_with=competing,
    )
    topic.state = transition(
        "file",
        state,
        {"path": path, "current": competing or revision, "candidate": revision if competing else None, "id": operation},
    )
    topic.revision += 1
    topic.save(update_fields=["state", "revision"])
    CommandReceipt.objects.create(command_id=operation, topic=topic, revision=topic.revision)
    return file


def choose_revision(topic: Topic, state: dict[str, Any], command: dict, operation: UUID) -> None:
    suggestion = command.get("suggestion")
    choice = suggestion.get("ChooseFileRevision") if isinstance(suggestion, dict) else None
    if not choice:
        return
    versions = topic.files.filter(path=choice["path"])
    head = versions.filter(competing_with=None).order_by("-revision").first()
    if head is None or head.revision != choice["current"]:
        raise ValidationError("The reviewed file head changed.")
    if choice["use_candidate"]:
        candidate = versions.get(revision=choice["candidate"])
        revision = versions.latest("revision").revision + 1
        versions.create(
            topic=topic, path=choice["path"], operation=operation, revision=revision, contents=candidate.contents
        )
        state.update(
            transition("file", state, {"path": choice["path"], "current": revision, "candidate": None, "id": operation})
        )
