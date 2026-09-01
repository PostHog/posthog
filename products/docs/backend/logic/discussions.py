"""Discussions on a doc: threads anchored to a phrase.

Threads are ``Comment`` rows, so they inherit the existing storage and activity handling.
A thread is a root comment scoped to the doc; replies point at it through ``source_comment``.
The anchor key also lives on a mark in the doc body, which is what makes the phrase in the
text and the thread in the panel find each other.
"""

from uuid import UUID

from django.db.models import QuerySet

from posthog.models.comment import Comment

from products.docs.backend.models import Doc

DOC_COMMENT_SCOPE = "doc"


class ThreadNotFoundError(Exception):
    """No such thread on this doc."""


def doc_comments(doc: Doc) -> QuerySet[Comment]:
    return Comment.objects.filter(team_id=doc.team_id, scope=DOC_COMMENT_SCOPE, item_id=str(doc.id), deleted=False)


def list_threads(doc: Doc) -> list[Comment]:
    return list(
        doc_comments(doc).filter(source_comment__isnull=True).select_related("created_by").order_by("created_at")
    )


def list_replies(doc: Doc, thread_ids: list[UUID]) -> list[Comment]:
    return list(
        doc_comments(doc).filter(source_comment_id__in=thread_ids).select_related("created_by").order_by("created_at")
    )


def create_thread(doc: Doc, *, user_id: int, content: str, anchor_key: str, anchor_text: str) -> Comment:
    return Comment.objects.create(
        team_id=doc.team_id,
        created_by_id=user_id,
        scope=DOC_COMMENT_SCOPE,
        item_id=str(doc.id),
        item_context={"anchor_key": anchor_key, "anchor_text": anchor_text, "resolved": False},
        content=content,
    )


def get_thread(doc: Doc, thread_id: str | UUID) -> Comment:
    thread = doc_comments(doc).filter(id=thread_id, source_comment__isnull=True).first()
    if thread is None:
        raise ThreadNotFoundError("Thread not found on this doc.")
    return thread


def reply_to_thread(doc: Doc, *, thread_id: str | UUID, user_id: int, content: str) -> Comment:
    thread = get_thread(doc, thread_id)
    return Comment.objects.create(
        team_id=doc.team_id,
        created_by_id=user_id,
        scope=DOC_COMMENT_SCOPE,
        item_id=str(doc.id),
        source_comment=thread,
        content=content,
    )


def set_thread_resolved(doc: Doc, *, thread_id: str | UUID, resolved: bool) -> Comment:
    thread = get_thread(doc, thread_id)
    thread.item_context = {**(thread.item_context or {}), "resolved": resolved}
    thread.save(update_fields=["item_context"])
    return thread
