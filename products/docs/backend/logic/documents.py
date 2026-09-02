"""Doc lifecycle: list, create, reorder, save, soft delete."""

import logging
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max, QuerySet

from posthog.models.team import Team

from products.context_layer.backend.facade import api as context_layer
from products.docs.backend.facade.enums import DocKind, DocTemplate
from products.docs.backend.logic.markdown import from_markdown
from products.docs.backend.logic.templates import template_content, template_title
from products.docs.backend.models import Doc
from products.tasks.backend.facade.api import channel_exists, visible_channels_q

logger = logging.getLogger(__name__)


class ChannelNotVisibleError(Exception):
    """The channel is missing, deleted, or another user's personal space."""


def visible_docs(team_id: int, user_id: int | None) -> QuerySet[Doc]:
    return (
        Doc.objects.unscoped()
        .filter(visible_channels_q(user_id, relation="channel"), team_id=team_id, deleted=False)
        .select_related("created_by")
    )


def docs_in_channel(team_id: int, user_id: int | None, channel_id: str | UUID) -> QuerySet[Doc]:
    """The space's pages, in tab order. The context notes are a doc too, but not a page."""
    return (
        visible_docs(team_id, user_id)
        .filter(channel_id=channel_id)
        .exclude(kind=DocKind.CONTEXT)
        .order_by("position", "created_at")
    )


def context_doc(team_id: int, user_id: int, channel_id: str | UUID) -> Doc:
    """The one doc that is the space's context notes, made on first use.

    A space that already wrote notes in the wiki starts from them: the page body is
    read once and becomes the doc, and from then on the doc is what people edit and
    the page is compiled from it.
    """
    existing = visible_docs(team_id, user_id).filter(channel_id=channel_id, kind=DocKind.CONTEXT).first()
    if existing is not None:
        return existing
    if not channel_exists(team_id, channel_id, user_id):
        raise ChannelNotVisibleError("Channel not found in this team.")
    content = from_markdown(_wiki_notes(team_id, channel_id))
    return Doc.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        created_by_id=user_id,
        title="Context",
        kind=DocKind.CONTEXT,
        position=-1,
        content=content,
        text_content=plain_text(content),
    )


def _wiki_notes(team_id: int, channel_id: str | UUID) -> str:
    """The body of the space's wiki page, without its frontmatter and title. Empty when there is none."""
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return ""
    try:
        path = context_layer.resolve_channel_page(organization_id, channel_id)
        if path is None:
            return ""
        return page_body(context_layer.get_page(organization_id, path).content)
    except Exception:
        logger.warning("docs_context_wiki_read_failed", extra={"team_id": team_id, "channel_id": str(channel_id)})
        return ""


def page_body_lines(content: str) -> list[str]:
    """A wiki page's lines after its frontmatter block."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return lines
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        index += 1
    return lines[index + 1 :]


def page_body(content: str) -> str:
    """A wiki page's prose: what is left after the frontmatter block and the page's own heading."""
    lines = content.splitlines()
    index = 0
    if lines and lines[0].strip() == "---":
        index = 1
        while index < len(lines) and lines[index].strip() != "---":
            index += 1
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        index += 1
    return "\n".join(lines[index:]).strip() + ("\n" if index < len(lines) else "")


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
