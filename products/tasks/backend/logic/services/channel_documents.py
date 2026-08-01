"""Channel documents: shared markdown docs (todos, plans) that live in a task channel.

Stored as ``TaskArtifact`` rows with ``adapter="native"``: the markdown body lives in
``metadata["content"]`` on the row itself rather than in an external system, because
these docs are small, read on every sidepanel poll, and written under a row lock.
Concurrency model:

- Appends (the selection-capture path) serialize on ``select_for_update``, so two
  concurrent captures both land instead of clobbering each other.
- Full edits carry ``expected_version`` checked against ``current_version`` under the
  same lock, so a stale editor gets a conflict instead of silently losing someone
  else's write (the same optimistic-concurrency shape as canvas publishing).

``versions`` keeps bounded, metadata-only history (who/when/size) — not content
snapshots — so the row stays small while edits remain attributable.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from products.tasks.backend.models import Channel, TaskArtifact

CHANNEL_DOCUMENT_KINDS = ["todo", "plan"]
ChannelDocumentKind = Literal["todo", "plan"]

# One doc is a capped markdown file, not a data store: the cap bounds what every
# reader must download on each poll and what one member can make the team store.
CHANNEL_DOCUMENT_MAX_CONTENT_BYTES = 256 * 1024
MAX_DOCUMENTS_PER_CHANNEL = 100
VERSION_HISTORY_LIMIT = 50


class ChannelDocumentTooLarge(Exception):
    pass


class ChannelDocumentLimitExceeded(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class DocumentUpdate:
    """A full-content edit: ``expected_version`` guards against lost updates."""

    content: str
    expected_version: int
    name: str | None = None


def channel_documents_queryset(channel: Channel) -> QuerySet[TaskArtifact]:
    return TaskArtifact.objects.for_team(channel.team_id).filter(
        channel_id=channel.id,
        adapter=TaskArtifact.Adapter.NATIVE,
        artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
    )


def list_documents(channel: Channel) -> list[TaskArtifact]:
    return list(channel_documents_queryset(channel).select_related("created_by").order_by("-updated_at"))


def get_document(channel: Channel, document_id: str | UUID) -> TaskArtifact | None:
    return channel_documents_queryset(channel).select_related("created_by").filter(id=document_id).first()


def _validate_size(content: str) -> None:
    if len(content.encode("utf-8")) > CHANNEL_DOCUMENT_MAX_CONTENT_BYTES:
        raise ChannelDocumentTooLarge(f"Document content exceeds {CHANNEL_DOCUMENT_MAX_CONTENT_BYTES // 1024} KB limit")


def _version_entry(version: int, action: str, user_id: int | None, size: int) -> dict:
    return {
        "version": version,
        "action": action,
        "edited_by": user_id,
        "edited_at": timezone.now().isoformat(),
        "size": size,
    }


def create_document(
    channel: Channel,
    user_id: int | None,
    *,
    name: str,
    doc_kind: str,
    content: str,
) -> TaskArtifact:
    """Create a document, or return the channel's existing live document with the same
    name and kind — the capture flow calls this blindly ("add to todos"), so creation
    must be resolve-or-create to avoid a new doc per capture. Best-effort (no unique
    constraint): two racing first-captures can still create twins, which the UI just
    renders as two docs.
    """
    _validate_size(content)
    name = name.strip()[:255]
    with transaction.atomic():
        existing = (
            channel_documents_queryset(channel)
            .select_for_update()
            .filter(name=name, metadata__doc_kind=doc_kind)
            .first()
        )
        if existing is not None:
            return existing
        if channel_documents_queryset(channel).count() >= MAX_DOCUMENTS_PER_CHANNEL:
            raise ChannelDocumentLimitExceeded(f"Channel already has {MAX_DOCUMENTS_PER_CHANNEL} documents")
        return TaskArtifact.objects.for_team(channel.team_id).create(
            team_id=channel.team_id,
            channel_id=channel.id,
            created_by_id=user_id,
            name=name,
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            adapter=TaskArtifact.Adapter.NATIVE,
            status=TaskArtifact.Status.ACTIVE,
            location={},
            metadata={"doc_kind": doc_kind, "content": content},
            versions=[_version_entry(1, "create", user_id, len(content.encode("utf-8")))],
            current_version=1,
        )


def _save_new_content(document: TaskArtifact, content: str, action: str, user_id: int | None) -> TaskArtifact:
    document.metadata = {**(document.metadata or {}), "content": content}
    document.current_version += 1
    versions = list(document.versions or [])
    versions.append(_version_entry(document.current_version, action, user_id, len(content.encode("utf-8"))))
    document.versions = versions[-VERSION_HISTORY_LIMIT:]
    document.save(update_fields=["metadata", "versions", "current_version", "updated_at"])
    return document


def append_to_document(
    channel: Channel,
    document_id: str | UUID,
    user_id: int | None,
    *,
    text: str,
) -> TaskArtifact | None:
    """Append lines to a document under a row lock. Concurrent appends both land."""
    with transaction.atomic():
        document = channel_documents_queryset(channel).select_for_update().filter(id=document_id).first()
        if document is None:
            return None
        current = str((document.metadata or {}).get("content") or "")
        block = text.strip("\n")
        new_content = f"{current.rstrip()}\n{block}\n" if current.strip() else f"{block}\n"
        _validate_size(new_content)
        return _save_new_content(document, new_content, "append", user_id)


def update_document(
    channel: Channel,
    document_id: str | UUID,
    user_id: int | None,
    update: DocumentUpdate,
) -> TaskArtifact | None | Literal["conflict"]:
    _validate_size(update.content)
    with transaction.atomic():
        document = channel_documents_queryset(channel).select_for_update().filter(id=document_id).first()
        if document is None:
            return None
        if document.current_version != update.expected_version:
            return "conflict"
        if update.name is not None and update.name.strip():
            document.name = update.name.strip()[:255]
            document.save(update_fields=["name"])
        return _save_new_content(document, update.content, "edit", user_id)


def delete_document(channel: Channel, document_id: str | UUID) -> bool:
    deleted, _ = channel_documents_queryset(channel).filter(id=document_id).delete()
    return deleted > 0
