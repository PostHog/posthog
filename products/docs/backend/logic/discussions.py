"""Discussions on a doc: threads anchored to a phrase or to a data point the page asked for.

Threads are ``Comment`` rows, so they inherit the existing storage and activity handling.
A thread is a root comment scoped to the doc; posts point at it through ``source_comment``.
The anchor key also lives on a mark in the doc body (or on the inline data request), which
is what makes the place in the text and the thread in the panel find each other.

The agent is a participant: a thread that someone tagged the agent in carries the agent's
task id, and the agent's turns land as posts with no ``created_by``.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from posthog.models.comment import Comment

from products.docs.backend.facade.enums import DiscussionKind, PostAuthorKind
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


def create_thread(
    doc: Doc,
    *,
    user_id: int,
    content: str,
    anchor_key: str,
    anchor_text: str,
    kind: DiscussionKind = DiscussionKind.TEXT,
    task_id: str | None = None,
    sent_to_agent: bool = False,
    loop_id: str | None = None,
) -> Comment:
    return Comment.objects.create(
        team_id=doc.team_id,
        created_by_id=user_id,
        scope=DOC_COMMENT_SCOPE,
        item_id=str(doc.id),
        item_context={
            "anchor_key": anchor_key,
            "anchor_text": anchor_text,
            "resolved": False,
            "kind": kind.value,
            "task_id": task_id,
            "loop_id": loop_id,
            "author_kind": PostAuthorKind.HUMAN.value,
            "sent_to_agent": sent_to_agent,
        },
        content=content,
    )


def get_thread(doc: Doc, thread_id: str | UUID) -> Comment:
    thread = doc_comments(doc).filter(id=thread_id, source_comment__isnull=True).first()
    if thread is None:
        raise ThreadNotFoundError("Thread not found on this doc.")
    return thread


def thread_for_request(team_id: int, request_id: str) -> Comment | None:
    """The data thread behind an inline request, wherever the doc is."""
    return (
        Comment.objects.filter(
            team_id=team_id,
            scope=DOC_COMMENT_SCOPE,
            deleted=False,
            source_comment__isnull=True,
            item_context__anchor_key=request_id,
            item_context__kind=DiscussionKind.DATA.value,
        )
        .order_by("-created_at")
        .first()
    )


def threads_for_task(team_id: int, task_id: str) -> list[Comment]:
    return list(
        Comment.objects.filter(
            team_id=team_id,
            scope=DOC_COMMENT_SCOPE,
            deleted=False,
            source_comment__isnull=True,
            item_context__task_id=task_id,
        )
    )


def threads_for_loop(team_id: int, loop_id: str) -> list[Comment]:
    return list(
        Comment.objects.filter(
            team_id=team_id,
            scope=DOC_COMMENT_SCOPE,
            deleted=False,
            source_comment__isnull=True,
            item_context__loop_id=loop_id,
        )
    )


def add_post(
    doc: Doc,
    thread: Comment,
    *,
    content: str,
    user_id: int | None,
    author_kind: PostAuthorKind,
    sent_to_agent: bool = False,
    run_id: str | None = None,
    turn_key: str | None = None,
) -> Comment:
    context: dict[str, Any] = {"author_kind": author_kind.value, "sent_to_agent": sent_to_agent}
    if run_id:
        context["run_id"] = run_id
    if turn_key:
        context["turn_key"] = turn_key
    return Comment.objects.create(
        team_id=doc.team_id,
        created_by_id=user_id,
        scope=DOC_COMMENT_SCOPE,
        item_id=str(doc.id),
        source_comment=thread,
        item_context=context,
        content=content,
    )


def append_agent_turn(doc: Doc, thread: Comment, *, run_id: str, turn_key: str, text: str) -> Comment | None:
    """The agent's turn as a post. A relay can replay a turn, so the same key lands once."""
    exists = doc_comments(doc).filter(
        source_comment=thread, item_context__run_id=run_id, item_context__turn_key=turn_key
    )
    if exists.exists():
        return None
    return add_post(
        doc, thread, content=text, user_id=None, author_kind=PostAuthorKind.AGENT, run_id=run_id, turn_key=turn_key
    )


def _update_context(thread: Comment, **changes: Any) -> Comment:
    thread.item_context = {**(thread.item_context or {}), **changes}
    thread.save(update_fields=["item_context"])
    return thread


def set_thread_task(thread: Comment, task_id: str) -> Comment:
    return _update_context(thread, task_id=task_id)


def human_ask_count(doc: Doc, thread: Comment) -> int:
    """How many times a person sent this thread to the agent, the first post included."""
    root = 1 if (thread.item_context or {}).get("sent_to_agent") else 0
    return (
        root
        + doc_comments(doc)
        .filter(
            source_comment=thread,
            item_context__sent_to_agent=True,
            item_context__author_kind=PostAuthorKind.HUMAN.value,
        )
        .count()
    )


def set_reminders(thread: Comment, count: int) -> Comment:
    return _update_context(thread, reminders=count)


def set_thread_resolved(doc: Doc, *, thread_id: str | UUID, resolved: bool) -> Comment:
    return _update_context(get_thread(doc, thread_id), resolved=resolved)


def set_thread_answer(
    thread: Comment, *, query: str, label: str, note: str, run_id: str | None, at: datetime | None = None
) -> Comment:
    answer = {
        "query": query,
        "label": label,
        "note": note,
        "run_id": run_id,
        "updated_at": (at or timezone.now()).isoformat(),
    }
    return _update_context(thread, answer=answer)


def clear_thread_answer(thread: Comment) -> Comment:
    return _update_context(thread, answer=None)


def threads_for_docs(team_id: int, doc_ids: list[UUID]) -> list[Comment]:
    """Every thread on these docs, for counts and the watch list on the space's context page."""
    return list(
        Comment.objects.filter(
            team_id=team_id,
            scope=DOC_COMMENT_SCOPE,
            deleted=False,
            source_comment__isnull=True,
            item_id__in=[str(doc_id) for doc_id in doc_ids],
        ).order_by("created_at")
    )


def last_reports(team_id: int, thread_ids: list[UUID]) -> dict[str, Comment]:
    """The newest post the agent or the page wrote on each thread, keyed by thread id."""
    posts = (
        Comment.objects.filter(
            team_id=team_id,
            scope=DOC_COMMENT_SCOPE,
            deleted=False,
            source_comment_id__in=thread_ids,
            created_by__isnull=True,
        )
        .exclude(item_context__author_kind=PostAuthorKind.SYSTEM.value)
        .order_by("created_at")
    )
    latest: dict[str, Comment] = {}
    for post in posts:
        latest[str(post.source_comment_id)] = post
    return latest
