"""
Facade for docs.

The ONLY module other products and this product's own presentation layer are allowed
to import. Accept frozen dataclasses, call logic/, return frozen dataclasses. Never
return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID

from django.conf import settings

from posthog.models.comment import Comment
from posthog.models.team import Team
from posthog.models.user import User

from products.context_layer.backend.facade import api as context_layer
from products.tasks.backend.facade import api as tasks_facade

from ..logic import collab, data_points, discussions, documents, markdown
from ..models import Doc
from . import contracts
from .enums import (
    AgentDelivery,
    CollabSubmitStatus,
    DataPointStatus,
    DiscussionKind,
    DocKind,
    DocStatus,
    PostAuthorKind,
)

ChannelNotVisibleError = documents.ChannelNotVisibleError
ThreadNotFoundError = discussions.ThreadNotFoundError


def doc_url(channel_id: str | UUID, doc_id: str | UUID) -> str:
    """Canonical link to a doc. Share this when pointing someone at one; never build the URL yourself."""
    return f"{settings.SITE_URL}/code/docs/{channel_id}/{doc_id}"


# --- Docs ---


def list_docs(team_id: int, user_id: int | None, channel_id: str | UUID | None) -> list[contracts.DocSummaryDTO]:
    queryset = documents.visible_docs(team_id, user_id).exclude(kind=DocKind.CONTEXT).defer("content", "text_content")
    if channel_id:
        queryset = queryset.filter(channel_id=channel_id)
    return [_to_summary(doc) for doc in queryset.order_by("position", "created_at")]


def get_doc(team_id: int, user_id: int | None, doc_id: str | UUID) -> contracts.DocDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    return _to_doc(doc) if doc is not None else None


def create_doc(payload: contracts.CreateDocInput) -> contracts.DocDTO:
    doc = documents.create_doc(
        team_id=payload.team_id,
        user_id=payload.user_id,
        channel_id=payload.channel_id,
        title=payload.title,
        template=payload.template,
    )
    return _to_doc(doc)


def update_doc(
    team_id: int, user_id: int | None, doc_id: str | UUID, *, title: str | None = None, status: str | None = None
) -> contracts.DocDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    return _to_doc(documents.update_doc(doc, title=title, status=status))


def delete_doc(team_id: int, user_id: int | None, doc_id: str | UUID) -> bool:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return False
    documents.soft_delete_doc(doc)
    return True


def reorder_docs(team_id: int, user_id: int | None, channel_id: str | UUID, doc_ids: list[UUID]) -> None:
    documents.reorder_docs(team_id=team_id, user_id=user_id, channel_id=channel_id, doc_ids=doc_ids)


EXCERPT_CHARS = 160


def space_home(team_id: int, user_id: int | None, channel_id: str | UUID) -> contracts.SpaceHomeDTO:
    """The context page's view of the space: each page with what lives in it, and every watched section."""
    docs = list(documents.docs_in_channel(team_id, user_id, channel_id).defer("content"))
    threads = discussions.threads_for_docs(team_id, [doc.id for doc in docs])
    open_counts: dict[str, int] = {}
    watch_counts: dict[str, int] = {}
    watch_threads: list[Comment] = []
    for thread in threads:
        context = thread.item_context or {}
        key = str(thread.item_id)
        if context.get("kind") == DiscussionKind.WATCH.value:
            watch_counts[key] = watch_counts.get(key, 0) + 1
            watch_threads.append(thread)
        elif not context.get("resolved"):
            open_counts[key] = open_counts.get(key, 0) + 1

    reports = discussions.last_reports(team_id, [thread.id for thread in watch_threads])
    titles = {str(doc.id): doc.title for doc in docs}
    watches = []
    for thread in sorted(watch_threads, key=lambda entry: entry.created_at, reverse=True):
        context = thread.item_context or {}
        report = reports.get(str(thread.id))
        watches.append(
            contracts.WatchSummaryDTO(
                doc_id=UUID(str(thread.item_id)),
                doc_title=titles.get(str(thread.item_id), ""),
                anchor_key=context.get("anchor_key", ""),
                anchor_text=context.get("anchor_text", ""),
                loop_id=str(context["loop_id"]) if context.get("loop_id") else None,
                last_report=(report.content or "") if report else "",
                last_report_at=report.created_at if report else None,
                created_at=thread.created_at,
            )
        )

    summaries = [
        _to_summary(
            doc,
            excerpt=_excerpt(doc.text_content),
            open_thread_count=open_counts.get(str(doc.id), 0),
            watch_count=watch_counts.get(str(doc.id), 0),
        )
        for doc in docs
    ]
    return contracts.SpaceHomeDTO(docs=summaries, watches=watches)


def _excerpt(text: str | None) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= EXCERPT_CHARS:
        return flat
    return f"{flat[:EXCERPT_CHARS].rsplit(' ', 1)[0]}…"


def context_doc(team_id: int, user_id: int, channel_id: str | UUID) -> contracts.DocDTO:
    """The space's context notes as a doc, made on first use."""
    return _to_doc(documents.context_doc(team_id, user_id, channel_id))


# --- The context notes as a wiki page ---

# Saves arrive every few hundred milliseconds while someone types; the page is
# written at most this often, from whatever the doc holds when the write runs.
CONTEXT_SYNC_DELAY_SECONDS = 8


def schedule_context_sync(doc_id: UUID) -> None:
    from django.core.cache import cache  # noqa: PLC0415 — keeps the cache off the facade import path

    from ..tasks.tasks import sync_context_doc_task  # noqa: PLC0415 — celery stays off the import path

    if cache.add(f"docs:context-sync:{doc_id}", 1, CONTEXT_SYNC_DELAY_SECONDS):
        sync_context_doc_task.apply_async((str(doc_id),), countdown=CONTEXT_SYNC_DELAY_SECONDS)


def sync_context_doc(doc_id: str | UUID) -> str | None:
    """Compile the context doc into the space's wiki page. Returns the new head, or None when nothing was written."""
    doc = Doc.objects.unscoped().filter(id=doc_id, deleted=False, kind=DocKind.CONTEXT).select_related("team").first()
    if doc is None:
        return None
    organization_id = doc.team.organization_id
    path = context_layer.resolve_channel_page(organization_id, doc.channel_id) or context_layer.create_channel_page(
        organization_id, doc.channel_id
    )
    current = context_layer.get_page(organization_id, path)
    title = _page_title(current.content) or "Context"
    header = context_layer.SpacePageHeader(
        team_id=doc.team_id,
        channel_id=str(doc.channel_id),
        summary="What this space writes down for every agent, kept as a page in the app.",
        sources="desktop-doc",
        doc_id=str(doc.id),
    )
    rendered = context_layer.render_space_page(header, title, markdown.to_markdown(doc.content))
    if rendered == current.content:
        return None
    return context_layer.write_page(organization_id, path=path, content=rendered, base_head=current.head_sha)


def _page_title(content: str) -> str | None:
    for line in documents.page_body_lines(content):
        if line.startswith("# "):
            return line[2:].strip()
    return None


# --- Live editing ---


def save_steps(payload: contracts.SaveStepsInput) -> contracts.CollabSaveResultDTO | None:
    doc = _visible_doc(payload.team_id, payload.user_id, payload.doc_id)
    if doc is None:
        return None

    result = collab.save_steps(
        doc,
        client_id=payload.client_id,
        steps=payload.steps,
        last_seen_version=payload.version,
        content=payload.content,
        text_content=payload.text_content,
        title=payload.title,
        user_id=payload.user_id,
        user_name=payload.user_name,
        cursor_head=payload.cursor_head,
    )

    if result.status == "accepted":
        doc.refresh_from_db()
        if doc.kind == DocKind.CONTEXT:
            schedule_context_sync(doc.id)
        return contracts.CollabSaveResultDTO(
            status=CollabSubmitStatus.ACCEPTED, version=result.version, doc=_to_doc(doc)
        )
    if result.status == "stale":
        return contracts.CollabSaveResultDTO(status=CollabSubmitStatus.STALE, version=result.version)

    missed = result.steps_since or []
    return contracts.CollabSaveResultDTO(
        status=CollabSubmitStatus.CONFLICT,
        version=result.version,
        steps=[entry.step for entry in missed],
        client_ids=[entry.client_id for entry in missed],
    )


def publish_caret(payload: contracts.PresenceInput) -> bool:
    doc = _visible_doc(payload.team_id, payload.user_id, payload.doc_id)
    if doc is None:
        return False
    collab.publish_caret(
        doc,
        client_id=payload.client_id,
        user_id=payload.user_id,
        user_name=payload.user_name,
        version=payload.version,
        cursor=payload.cursor,
    )
    return True


def stream_doc(
    team_id: int, user_id: int | None, doc_id: str | UUID, *, last_event_id: str | None
) -> AsyncGenerator[bytes] | None:
    """The live stream for a doc: steps, carets, and discussion pings. ``None`` when the doc is not visible."""
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    return collab.stream_doc_sse(doc.team_id, str(doc.id), last_event_id=last_event_id)


# --- Discussions ---


def list_threads(team_id: int, user_id: int | None, doc_id: str | UUID) -> list[contracts.DiscussionThreadDTO] | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None

    threads = discussions.list_threads(doc)
    replies = discussions.list_replies(doc, [thread.id for thread in threads])
    by_thread: dict[str, list] = {}
    for reply in replies:
        by_thread.setdefault(str(reply.source_comment_id), []).append(reply)
    return [_to_thread(thread, by_thread.get(str(thread.id), [])) for thread in threads]


def create_thread(payload: contracts.CreateThreadInput) -> contracts.ReplyResultDTO | None:
    doc = _visible_doc(payload.team_id, payload.user_id, payload.doc_id)
    if doc is None:
        return None
    thread = discussions.create_thread(
        doc,
        user_id=payload.user_id,
        content=payload.content,
        anchor_key=payload.anchor_key,
        anchor_text=payload.anchor_text,
        kind=payload.kind,
        task_id=payload.task_id,
        sent_to_agent=payload.send_to_agent,
        loop_id=payload.loop_id,
    )
    delivery = AgentDelivery.NOT_REQUESTED
    # A thread created with a task already has its question in the task, so nothing is
    # forwarded: the agent's first turn answers it.
    if payload.send_to_agent and not payload.task_id:
        delivery = AgentDelivery.NO_RUN
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return contracts.ReplyResultDTO(thread=_to_thread(thread, []), delivery=delivery)


def reply_to_thread(payload: contracts.ReplyInput) -> contracts.ReplyResultDTO | None:
    doc = _visible_doc(payload.team_id, payload.user_id, payload.doc_id)
    if doc is None:
        return None
    thread = discussions.get_thread(doc, payload.thread_id)

    delivery = AgentDelivery.NOT_REQUESTED
    if payload.task_id and (thread.item_context or {}).get("task_id") != payload.task_id:
        # A new task carries the whole thread in its prompt, so the post is not forwarded.
        discussions.set_thread_task(thread, payload.task_id)
        delivery = AgentDelivery.SENT
    elif payload.send_to_agent:
        delivery = _forward_to_agent(thread, team_id=payload.team_id, user_id=payload.user_id, content=payload.content)

    discussions.add_post(
        doc,
        thread,
        content=payload.content,
        user_id=payload.user_id,
        author_kind=PostAuthorKind.HUMAN,
        sent_to_agent=delivery == AgentDelivery.SENT,
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return contracts.ReplyResultDTO(thread=_reload_thread(doc, thread.id), delivery=delivery)


def _forward_to_agent(thread: Comment, *, team_id: int, user_id: int, content: str) -> AgentDelivery:
    task_id = (thread.item_context or {}).get("task_id")
    if not task_id:
        return AgentDelivery.NO_RUN
    outcome = tasks_facade.forward_message_to_run(task_id, team_id, content=content, actor_user_id=user_id)
    if outcome == "ok":
        return AgentDelivery.SENT
    if outcome == "signal_failed":
        return AgentDelivery.FAILED
    return AgentDelivery.NO_RUN


def set_thread_resolved(
    team_id: int, user_id: int | None, doc_id: str | UUID, *, thread_id: str | UUID, resolved: bool
) -> contracts.DiscussionThreadDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    discussions.set_thread_resolved(doc, thread_id=thread_id, resolved=resolved)
    collab.publish_discussion_change(doc, thread_id=str(thread_id))
    return _reload_thread(doc, thread_id)


# --- The agent in a thread ---


def record_agent_turn(
    *, team_id: int, task_id: str, run_id: str, turn_key: str, text: str, loop_id: str | None = None
) -> None:
    """An agent turn ended: it becomes a post on every thread that tagged this task, and on
    every thread watching through this loop.

    A data thread with no answer yet also reads a query out of the prose, for a run that
    wrote the tag and never called the tool.
    """
    if not text.strip():
        return
    threads = discussions.threads_for_task(team_id, task_id)
    if loop_id:
        threads += discussions.threads_for_loop(team_id, loop_id)
    for thread in threads:
        if not thread.item_id:
            continue
        doc = Doc.objects.for_team(team_id).filter(id=thread.item_id, deleted=False).first()
        if doc is None:
            continue
        context = thread.item_context or {}
        is_data = context.get("kind") == DiscussionKind.DATA.value
        structured = data_points.extract_structured(text) if is_data else None
        if structured is not None:
            _apply_structured_answer(doc, thread, run_id=run_id, turn_key=turn_key, structured=structured)
            collab.publish_discussion_change(doc, thread_id=str(thread.id))
            continue
        posted = discussions.append_agent_turn(doc, thread, run_id=run_id, turn_key=turn_key, text=text)
        if posted is None:
            continue
        if is_data and not context.get("answer"):
            found = data_points.extract_query(text)
            # A query out of prose is kept only when it runs: the page must never show a broken one.
            if found and data_points.run_once(Team.objects.get(id=team_id), found[0])[1] is None:
                discussions.set_thread_answer(thread, query=found[0], label=found[1], note="", run_id=run_id)
            else:
                _remind_data_point(doc, thread, team_id=team_id, task_id=task_id)
        collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _remind_data_point(doc: Doc, thread: Comment, *, team_id: int, task_id: str) -> None:
    """A turn ended with words and no query. The run gets one fixed reminder per ask, never a loop."""
    context = thread.item_context or {}
    asks = discussions.human_ask_count(doc, thread)
    if int(context.get("reminders") or 0) >= asks:
        return
    discussions.set_reminders(thread, asks)
    discussions.add_post(
        doc,
        thread,
        content="Asked the agent to hand in the number.",
        user_id=None,
        author_kind=PostAuthorKind.SYSTEM,
        sent_to_agent=True,
    )
    tasks_facade.forward_message_to_run(
        task_id, team_id, content=data_points.reminder_text(context["anchor_key"]), actor_user_id=None
    )


def _apply_structured_answer(
    doc: Doc, thread: Comment, *, run_id: str, turn_key: str, structured: dict[str, str]
) -> None:
    """The run ended as the JSON its schema asked for. The reader sees a line, never the JSON."""
    if discussions.doc_comments(doc).filter(source_comment=thread, item_context__turn_key=turn_key).exists():
        return
    if structured["status"] == "none":
        discussions.add_post(
            doc,
            thread,
            content=structured["note"] or "The project's data cannot answer this.",
            user_id=None,
            author_kind=PostAuthorKind.AGENT,
            run_id=run_id,
            turn_key=turn_key,
        )
        return
    query = data_points.clean_query(structured["query"])
    value, error = (None, "Only one SELECT is accepted.")
    if data_points.is_read_query(query):
        value, error = data_points.run_once(Team.objects.get(id=doc.team_id), query)
    if error:
        discussions.add_post(
            doc,
            thread,
            content=f"The query the agent wrote did not run: {error}",
            user_id=None,
            author_kind=PostAuthorKind.SYSTEM,
            run_id=run_id,
            turn_key=turn_key,
        )
        return
    had_answer = bool((thread.item_context or {}).get("answer"))
    discussions.set_thread_answer(
        thread, query=query, label=structured["label"], note=structured["note"], run_id=run_id
    )
    line = "Updated the data point." if had_answer else "Put the data point on the page."
    if structured["note"]:
        line = f"{line} {structured['note']}"
    discussions.add_post(
        doc, thread, content=line, user_id=None, author_kind=PostAuthorKind.SYSTEM, run_id=run_id, turn_key=turn_key
    )


def submit_data_point(payload: contracts.SubmitDataPointInput) -> contracts.SubmitDataPointResultDTO | None:
    """The agent hands in the query behind a data point. ``None`` when no such request exists.

    Raises ``PermissionError`` when the request belongs to another task: only the run that
    was asked may answer.
    """
    thread = discussions.thread_for_request(payload.team_id, payload.request_id)
    if thread is None:
        return None
    if (thread.item_context or {}).get("task_id") != payload.task_id:
        raise PermissionError("This data point belongs to another run.")
    if not thread.item_id:
        return None
    doc = Doc.objects.for_team(payload.team_id).filter(id=thread.item_id, deleted=False).first()
    if doc is None:
        return None
    run_id = _latest_run_id(payload.task_id, payload.team_id)

    if payload.status == DataPointStatus.NONE:
        discussions.clear_thread_answer(thread)
        note = payload.note.strip() or "The project's data cannot answer this."
        discussions.add_post(doc, thread, content=note, user_id=None, author_kind=PostAuthorKind.AGENT, run_id=run_id)
        collab.publish_discussion_change(doc, thread_id=str(thread.id))
        return contracts.SubmitDataPointResultDTO(ok=True, value=None, error=None)

    query = data_points.clean_query(payload.query)
    if not data_points.is_read_query(query):
        return contracts.SubmitDataPointResultDTO(
            ok=False, value=None, error="Only one SELECT (or WITH … SELECT) is accepted."
        )
    team = Team.objects.get(id=payload.team_id)
    value, error = data_points.run_once(team, query)
    if error:
        return contracts.SubmitDataPointResultDTO(ok=False, value=None, error=error)

    had_answer = bool((thread.item_context or {}).get("answer"))
    discussions.set_thread_answer(
        thread, query=query, label=payload.label.strip(), note=payload.note.strip(), run_id=run_id
    )
    discussions.add_post(
        doc,
        thread,
        content="Updated the data point." if had_answer else "Put the data point on the page.",
        user_id=None,
        author_kind=PostAuthorKind.SYSTEM,
        run_id=run_id,
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return contracts.SubmitDataPointResultDTO(ok=True, value=value, error=None)


def _latest_run_id(task_id: str, team_id: int) -> str | None:
    run_id = tasks_facade.latest_run_id(task_id, team_id)
    return str(run_id) if run_id else None


# --- Mapping ---


def _visible_doc(team_id: int, user_id: int | None, doc_id: str | UUID) -> Doc | None:
    return documents.visible_docs(team_id, user_id).filter(id=doc_id).first()


def _to_person(user: User | None) -> contracts.PersonDTO | None:
    if user is None:
        return None
    return contracts.PersonDTO(
        id=user.id,
        uuid=user.uuid,
        first_name=user.first_name,
        last_name=user.last_name or "",
        email=user.email,
    )


def _to_summary(
    doc: Doc, *, excerpt: str = "", open_thread_count: int = 0, watch_count: int = 0
) -> contracts.DocSummaryDTO:
    return contracts.DocSummaryDTO(
        id=doc.id,
        channel_id=doc.channel_id,
        title=doc.title,
        status=DocStatus(doc.status),
        kind=DocKind(doc.kind),
        position=doc.position,
        version=doc.version,
        created_by=_to_person(doc.created_by),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        excerpt=excerpt,
        open_thread_count=open_thread_count,
        watch_count=watch_count,
    )


def _to_doc(doc: Doc) -> contracts.DocDTO:
    return contracts.DocDTO(
        id=doc.id,
        channel_id=doc.channel_id,
        title=doc.title,
        status=DocStatus(doc.status),
        kind=DocKind(doc.kind),
        position=doc.position,
        version=doc.version,
        content=doc.content,
        text_content=doc.text_content or "",
        created_by=_to_person(doc.created_by),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_post(post: Comment) -> contracts.DiscussionPostDTO:
    context = post.item_context or {}
    return contracts.DiscussionPostDTO(
        id=post.id,
        content=post.content or "",
        created_by=_to_person(post.created_by),
        created_at=post.created_at,
        author_kind=PostAuthorKind(context.get("author_kind") or PostAuthorKind.HUMAN.value),
        sent_to_agent=bool(context.get("sent_to_agent", False)),
    )


def _to_answer(raw: object) -> contracts.DataAnswerDTO | None:
    if not isinstance(raw, dict) or not raw.get("query"):
        return None
    updated_at = raw.get("updated_at")
    return contracts.DataAnswerDTO(
        query=str(raw["query"]),
        label=str(raw.get("label") or ""),
        note=str(raw.get("note") or ""),
        run_id=str(raw["run_id"]) if raw.get("run_id") else None,
        updated_at=datetime.fromisoformat(updated_at) if isinstance(updated_at, str) else None,
    )


def _to_thread(thread: Comment, replies: list[Comment]) -> contracts.DiscussionThreadDTO:
    context = thread.item_context or {}
    return contracts.DiscussionThreadDTO(
        id=thread.id,
        content=thread.content or "",
        created_by=_to_person(thread.created_by),
        created_at=thread.created_at,
        anchor_key=context.get("anchor_key", ""),
        anchor_text=context.get("anchor_text", ""),
        resolved=bool(context.get("resolved", False)),
        replies=[_to_post(reply) for reply in replies],
        kind=DiscussionKind(context.get("kind") or DiscussionKind.TEXT.value),
        task_id=str(context["task_id"]) if context.get("task_id") else None,
        answer=_to_answer(context.get("answer")),
        author_kind=PostAuthorKind(context.get("author_kind") or PostAuthorKind.HUMAN.value),
        sent_to_agent=bool(context.get("sent_to_agent", False)),
        loop_id=str(context["loop_id"]) if context.get("loop_id") else None,
    )


def _reload_thread(doc: Doc, thread_id: str | UUID) -> contracts.DiscussionThreadDTO:
    thread = discussions.get_thread(doc, thread_id)
    return _to_thread(thread, discussions.list_replies(doc, [thread.id]))
