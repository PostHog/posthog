"""Live editing for docs, on the shared Redis transport in ``posthog/collab``.

The stream is the authority while people are typing; the ``Doc`` row is the durable copy
every client reloads from. A save is accepted only when the client's baseline matches both
the stream head and the stored version, so versions stay linear.
"""

from collections.abc import AsyncGenerator
from typing import Any

from django.utils.timezone import now

from posthog.collab import SubmitResult, publish_ephemeral_event, publish_presence, stream_collab_sse, submit_steps

from products.docs.backend.logic.documents import plain_text
from products.docs.backend.models import Doc

DOC_COLLAB_NAMESPACE = "doc"

DISCUSSION_EVENT_TYPE = "discussion"

# Carets and "a discussion was posted" both ride the ephemeral stream, so one open
# SSE connection carries everything a doc view needs.
DOC_EPHEMERAL_EVENT_TYPES = ("presence", DISCUSSION_EVENT_TYPE)


def save_steps(
    doc: Doc,
    *,
    client_id: str,
    steps: list[dict],
    last_seen_version: int,
    content: dict[str, Any],
    text_content: str | None,
    title: str | None,
    user_id: int,
    user_name: str,
    cursor_head: int | None,
) -> SubmitResult:
    result = submit_steps(
        DOC_COLLAB_NAMESPACE,
        doc.team_id,
        str(doc.id),
        client_id,
        steps,
        last_seen_version,
        last_saved_version=doc.version,
        user_id=user_id,
        user_name=user_name,
        cursor_head=cursor_head,
    )
    if result.status != "accepted":
        return result

    Doc.objects.unscoped().filter(pk=doc.pk).update(
        content=content,
        text_content=text_content if text_content else plain_text(content),
        title=title if title is not None else doc.title,
        version=result.version,
        updated_at=now(),
    )
    return result


def publish_caret(doc: Doc, *, client_id: str, user_id: int, user_name: str, version: int, cursor: dict) -> None:
    publish_presence(
        DOC_COLLAB_NAMESPACE,
        doc.team_id,
        str(doc.id),
        client_id=client_id,
        user_id=user_id,
        user_name=user_name,
        version=version,
        cursor=cursor,
    )


def publish_discussion_change(doc: Doc, *, thread_id: str) -> None:
    """Tell open clients that a thread changed. It carries no content: receivers refetch."""
    publish_ephemeral_event(
        DOC_COLLAB_NAMESPACE,
        doc.team_id,
        str(doc.id),
        event_type=DISCUSSION_EVENT_TYPE,
        payload={"thread_id": thread_id},
    )


def stream_doc_sse(team_id: int, doc_id: str, *, last_event_id: str | None) -> AsyncGenerator[bytes]:
    return stream_collab_sse(
        DOC_COLLAB_NAMESPACE,
        team_id,
        doc_id,
        last_event_id=last_event_id,
        ephemeral_event_types=DOC_EPHEMERAL_EVENT_TYPES,
    )
