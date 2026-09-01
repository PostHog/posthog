"""Doc lifecycle: list, create, reorder, save, soft delete."""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max, QuerySet

from products.docs.backend.facade.enums import DocTemplate
from products.docs.backend.logic.templates import template_content, template_title
from products.docs.backend.models import Doc
from products.tasks.backend.facade.api import channel_exists, visible_channels_q


class ChannelNotVisibleError(Exception):
    """The channel is missing, deleted, or another user's personal space."""


def visible_docs(team_id: int, user_id: int | None) -> QuerySet[Doc]:
    return (
        Doc.objects.unscoped()
        .filter(visible_channels_q(user_id, relation="channel"), team_id=team_id, deleted=False)
        .select_related("created_by")
    )


def docs_in_channel(team_id: int, user_id: int | None, channel_id: str | UUID) -> QuerySet[Doc]:
    return visible_docs(team_id, user_id).filter(channel_id=channel_id).order_by("position", "created_at")


def create_doc(
    *,
    team_id: int,
    user_id: int,
    channel_id: str | UUID,
    title: str = "",
    template: str = DocTemplate.BLANK,
) -> Doc:
    if not channel_exists(team_id, channel_id, user_id):
        raise ChannelNotVisibleError("Channel not found in this team.")

    with transaction.atomic():
        last = (
            Doc.objects.unscoped()
            .filter(team_id=team_id, channel_id=channel_id, deleted=False)
            .aggregate(top=Max("position"))["top"]
        )
        content = template_content(template)
        return Doc.objects.create(
            team_id=team_id,
            channel_id=channel_id,
            created_by_id=user_id,
            title=title or template_title(template),
            content=content,
            text_content=plain_text(content),
            position=0 if last is None else last + 1,
        )


def update_doc(doc: Doc, *, title: str | None = None, status: str | None = None) -> Doc:
    changed: list[str] = []
    if title is not None and title != doc.title:
        doc.title = title
        changed.append("title")
    if status is not None and status != doc.status:
        doc.status = status
        changed.append("status")
    if changed:
        doc.save(update_fields=[*changed, "updated_at"])
    return doc


def soft_delete_doc(doc: Doc) -> None:
    doc.deleted = True
    doc.save(update_fields=["deleted"])


def reorder_docs(*, team_id: int, user_id: int | None, channel_id: str | UUID, doc_ids: list[UUID]) -> None:
    """Write the given order onto the channel's docs. Ids that are not in the channel are ignored."""
    positions = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    docs = list(docs_in_channel(team_id, user_id, channel_id).filter(id__in=positions))
    for doc in docs:
        doc.position = positions[doc.id]
    if docs:
        Doc.objects.unscoped().bulk_update(docs, ["position"])


def plain_text(content: dict[str, Any] | None) -> str:
    """Flatten a ProseMirror document to text, one block per line."""
    if not content:
        return ""
    lines: list[str] = []
    _collect_text(content, lines)
    return "\n".join(line for line in lines if line)


_BLOCK_TYPES = frozenset({"paragraph", "heading", "listItem", "taskItem", "blockquote", "codeBlock"})


def _collect_text(node: dict[str, Any], lines: list[str]) -> None:
    node_type = node.get("type")
    if node_type == "text":
        if lines:
            lines[-1] += node.get("text", "")
        else:
            lines.append(node.get("text", ""))
        return
    if node_type in _BLOCK_TYPES:
        lines.append("")
    for child in node.get("content", []) or []:
        if isinstance(child, dict):
            _collect_text(child, lines)
