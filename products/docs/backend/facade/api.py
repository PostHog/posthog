"""
Facade for docs.

The ONLY module other products and this product's own presentation layer are allowed
to import. Accept frozen dataclasses, call logic/, return frozen dataclasses. Never
return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog

from posthog.models.comment import Comment
from posthog.models.team import Team
from posthog.models.user import User

from products.context_layer.backend.facade import api as context_layer
from products.signals.backend.facade import api as signals_facade
from products.tasks.backend.facade import (
    api as tasks_facade,
    contracts as tasks_contracts,
)

from ..logic import collab, data_points, discussions, documents, markdown, mentions, watches
from ..models import Doc
from . import contracts
from .enums import (
    AgentDelivery,
    CollabSubmitStatus,
    DataPointStatus,
    DataShape,
    DiscussionKind,
    DocKind,
    DocStatus,
    PostAuthorKind,
    WatchAction,
    WatchActor,
    WatchEvent,
    WatchStatus,
    WatchStopReason,
    WatchVerdict,
)

ChannelNotVisibleError = documents.ChannelNotVisibleError
ThreadNotFoundError = discussions.ThreadNotFoundError


logger = structlog.get_logger(__name__)


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
    was_done = doc.status == DocStatus.DONE
    updated = documents.update_doc(doc, title=title, status=status)
    is_done = updated.status == DocStatus.DONE
    if is_done and not was_done:
        _pause_page_watches(updated)
    elif was_done and not is_done:
        _resume_page_watches(updated)
    return _to_doc(updated)


def delete_doc(team_id: int, user_id: int | None, doc_id: str | UUID) -> bool:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return False
    for thread in discussions.watch_threads(doc=doc):
        if discussions.watch_of(thread).get("status") != WatchStatus.STOPPED.value:
            _stop_watch(doc, thread, WatchStopReason.PAGE_DELETED, line="The page was deleted, so the watch stopped.")
    documents.soft_delete_doc(doc)
    return True


def reorder_docs(team_id: int, user_id: int | None, channel_id: str | UUID, doc_ids: list[UUID]) -> None:
    documents.reorder_docs(team_id=team_id, user_id=user_id, channel_id=channel_id, doc_ids=doc_ids)


EXCERPT_CHARS = 160


def space_home(team_id: int, user_id: int | None, channel_id: str | UUID) -> contracts.SpaceHomeDTO:
    """The context page's view of the space: each page with what lives in it, and every watched hypothesis."""
    docs = list(documents.docs_in_channel(team_id, user_id, channel_id).exclude(kind=DocKind.CONTEXT))
    threads = discussions.threads_for_docs(team_id, [doc.id for doc in docs])
    open_counts: dict[str, int] = {}
    watch_counts: dict[str, int] = {}
    watch_threads: list[Comment] = []
    for thread in threads:
        key = str(thread.item_id)
        context = thread.item_context or {}
        if context.get("kind") == DiscussionKind.WATCH.value:
            if discussions.watch_of(thread).get("status") != WatchStatus.STOPPED.value:
                watch_counts[key] = watch_counts.get(key, 0) + 1
            watch_threads.append(thread)
        elif not context.get("resolved"):
            open_counts[key] = open_counts.get(key, 0) + 1

    reports = discussions.last_reports(team_id, [thread.id for thread in watch_threads])
    titles = {str(doc.id): doc.title for doc in docs}
    watches_out = []
    for thread in watch_threads:
        report = reports.get(str(thread.id))
        watch = _to_watch(discussions.watch_of(thread))
        watches_out.append(
            contracts.WatchSummaryDTO(
                thread_id=thread.id,
                doc_id=UUID(str(thread.item_id)),
                doc_title=titles.get(str(thread.item_id), ""),
                anchor_key=(thread.item_context or {}).get("anchor_key", ""),
                anchor_text=(thread.item_context or {}).get("anchor_text", ""),
                status=watch.status,
                verdict=watch.verdict.verdict,
                last_report=report.content or "" if report else "",
                last_report_at=report.created_at if report else None,
                created_at=thread.created_at,
            )
        )
    watches_out.sort(
        key=lambda entry: (
            _WATCH_ORDER.get(entry.verdict, 9)
            if entry.status == WatchStatus.ACTIVE
            else 10 + _STATUS_ORDER.get(entry.status, 9),
            -entry.created_at.timestamp(),
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
    return contracts.SpaceHomeDTO(docs=summaries, watches=watches_out)


_WATCH_ORDER = {
    WatchVerdict.MOVED: 0,
    WatchVerdict.STALE: 1,
    WatchVerdict.PENDING: 2,
    WatchVerdict.HOLDING: 3,
}
_STATUS_ORDER = {WatchStatus.PAUSED: 0, WatchStatus.STOPPED: 1}


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
        _reconcile_watch_anchors(doc)
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
    watch = _new_watch(doc, payload) if payload.kind == DiscussionKind.WATCH else None
    thread = discussions.create_thread(
        doc,
        user_id=payload.user_id,
        content=payload.content,
        anchor_key=payload.anchor_key,
        anchor_text=payload.anchor_text,
        kind=payload.kind,
        task_id=payload.task_id,
        sent_to_agent=payload.send_to_agent,
        watch=watch,
    )
    delivery = AgentDelivery.NOT_REQUESTED
    # A thread created with a task already has its question in the task, so nothing is
    # forwarded: the agent's first turn answers it.
    if payload.send_to_agent and not payload.task_id:
        delivery = AgentDelivery.NO_RUN
    _tell_people(doc, thread)
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

    post = discussions.add_post(
        doc,
        thread,
        content=payload.content,
        user_id=payload.user_id,
        author_kind=PostAuthorKind.HUMAN,
        sent_to_agent=delivery == AgentDelivery.SENT,
    )
    _tell_people(doc, post)
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return contracts.ReplyResultDTO(thread=_reload_thread(doc, thread.id), delivery=delivery)


def _tell_people(doc: Doc, post: Comment) -> None:
    """The people a post concerns hear about it in their Activity: the page's owner for a new
    thread, the thread's people for a reply, and anyone the post names. Never fails the post."""
    try:
        tasks_facade.record_comment_activity(
            team_id=doc.team_id,
            comment_id=post.id,
            mentioned_user_ids=mentions.mentioned_user_ids(doc.team, post.content or ""),
            target=tasks_contracts.CommentActivityTargetDTO(
                scope=discussions.DOC_COMMENT_SCOPE,
                item_id=str(doc.id),
                title=doc.title or "Untitled",
                channel_id=doc.channel_id,
                owner_id=doc.created_by_id,
            ),
        )
    except Exception:
        logger.exception("doc_post_activity_failed", doc_id=str(doc.id), post_id=str(post.id))


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
    thread = discussions.get_thread(doc, thread_id)
    if (thread.item_context or {}).get("kind") == DiscussionKind.WATCH.value:
        if resolved:
            _stop_watch(doc, thread, WatchStopReason.HANDLED, line="Marked handled, so the watch stopped.")
        else:
            _resume_watch(doc, thread, line="Reopened, so the watch runs again.")
        return _reload_thread(doc, thread_id)
    discussions.set_thread_resolved(doc, thread_id=thread_id, resolved=resolved)
    collab.publish_discussion_change(doc, thread_id=str(thread_id))
    return _reload_thread(doc, thread_id)


# --- The agent in a thread ---


def record_agent_turn(*, team_id: int, task_id: str, run_id: str, turn_key: str, text: str) -> None:
    """An agent turn ended: it becomes a post on every thread that tagged this task.

    The tool is the way in for a number or a brief. A turn that is only a JSON blob is not a
    post: people never read it, and the run gets the reminder to call the tool instead.
    """
    if not text.strip():
        return
    is_blob = _is_json_blob(text)
    for thread in discussions.threads_for_task(team_id, task_id):
        if not thread.item_id:
            continue
        doc = Doc.objects.for_team(team_id).filter(id=thread.item_id, deleted=False).first()
        if doc is None:
            continue
        context = thread.item_context or {}
        is_data = context.get("kind") == DiscussionKind.DATA.value
        is_watch = context.get("kind") == DiscussionKind.WATCH.value
        if not is_blob:
            posted = discussions.append_agent_turn(doc, thread, run_id=run_id, turn_key=turn_key, text=text)
            if posted is None:
                continue
            _tell_people(doc, posted)
        if is_watch and not discussions.watch_of(thread).get("brief"):
            _remind(
                doc,
                thread,
                team_id=team_id,
                task_id=task_id,
                text=watches.reminder_text(context["anchor_key"]),
                line="Asked the agent to hand in the brief.",
            )
        if is_data and not context.get("answer"):
            found = data_points.extract_query(text)
            # A query out of prose is kept only when it runs: the page must never show a broken one.
            run = data_points.run_once(Team.objects.get(id=team_id), found[0]) if found else None
            if found and run is not None and run.shape is not None:
                discussions.set_thread_answer(
                    thread, query=found[0], label=found[1], note="", shape=run.shape.value, run_id=run_id
                )
            else:
                _remind_data_point(doc, thread, team_id=team_id, task_id=task_id)
        collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _is_json_blob(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(("{", "[")) and stripped.endswith(("}", "]"))


def _remind_data_point(doc: Doc, thread: Comment, *, team_id: int, task_id: str) -> None:
    anchor_key = (thread.item_context or {})["anchor_key"]
    _remind(
        doc,
        thread,
        team_id=team_id,
        task_id=task_id,
        text=data_points.reminder_text(anchor_key),
        line="Asked the agent to hand in the number.",
    )


def _remind(doc: Doc, thread: Comment, *, team_id: int, task_id: str, text: str, line: str) -> None:
    """A turn ended with words and no tool call. The run gets one fixed reminder per ask, never a loop."""
    context = thread.item_context or {}
    asks = discussions.human_ask_count(doc, thread)
    if int(context.get("reminders") or 0) >= asks:
        return
    discussions.set_reminders(thread, asks)
    discussions.add_post(doc, thread, content=line, user_id=None, author_kind=PostAuthorKind.SYSTEM, sent_to_agent=True)
    tasks_facade.forward_message_to_run(task_id, team_id, content=text, actor_user_id=None)


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
        return _submit_result(ok=True, run=None)

    query = data_points.clean_query(payload.query)
    if not data_points.is_read_query(query):
        return _submit_result(ok=False, run=None, error="Only one SELECT (or WITH … SELECT) is accepted.")
    team = Team.objects.get(id=payload.team_id)
    run = data_points.run_once(team, query)
    if run.error or run.shape is None:
        return _submit_result(ok=False, run=run, error=run.error or "The query came back with no rows.")

    had_answer = bool((thread.item_context or {}).get("answer"))
    discussions.set_thread_answer(
        thread,
        query=query,
        label=payload.label.strip(),
        note=payload.note.strip(),
        shape=run.shape.value,
        run_id=run_id,
    )
    discussions.add_post(
        doc,
        thread,
        content=_placed_line(run.shape, updated=had_answer),
        user_id=None,
        author_kind=PostAuthorKind.SYSTEM,
        run_id=run_id,
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return _submit_result(ok=True, run=run)


def _submit_result(
    *, ok: bool, run: data_points.DataPointRun | None, error: str | None = None
) -> contracts.SubmitDataPointResultDTO:
    return contracts.SubmitDataPointResultDTO(
        ok=ok,
        shape=run.shape if run else None,
        value=run.value if run else None,
        rows=run.rows if run else 0,
        columns=run.columns if run else 0,
        error=error,
    )


_PLACED = {
    DataShape.NUMBER: "the number",
    DataShape.SERIES: "the trend",
    DataShape.TABLE: "the table",
}


def _placed_line(shape: DataShape, *, updated: bool) -> str:
    """The system line under a submit, so the thread says what the page now shows."""
    what = _PLACED[shape]
    return f"Updated {what} on the page." if updated else f"Put {what} on the page."


def _latest_run_id(task_id: str, team_id: int) -> str | None:
    run_id = tasks_facade.latest_run_id(task_id, team_id)
    return str(run_id) if run_id else None


# --- Watches ---


def _now() -> datetime:
    return datetime.now(UTC)


def _new_watch(doc: Doc, payload: contracts.CreateThreadInput) -> dict[str, Any]:
    """A hypothesis watch waits for the agent's brief. A watch on a number already on the page
    is its own brief: the query is the evidence, and no scout runs."""
    watch: dict[str, Any] = {
        "status": WatchStatus.ACTIVE.value,
        "stopped_reason": None,
        "verdict": {"verdict": WatchVerdict.PENDING.value, "reason": "", "by": WatchActor.PAGE.value, "at": None},
        "brief": None,
        "scout": None,
        "scout_error": None,
        "seen_report_ids": [],
        "next_check_at": None,
        "checked_at": None,
        "evidence_only": bool(payload.evidence),
    }
    if not payload.evidence:
        return watch
    team = Team.objects.get(id=doc.team_id)
    evidence = []
    for entry in payload.evidence:
        checked, _ = watches.run_evidence(team, watches.EvidenceInput(label=entry.label, query=entry.query))
        if checked is not None:
            evidence.append(checked)
    now = _now()
    brief = watches.Brief(
        claim=payload.anchor_text or payload.content,
        confirms="The number stays where it is.",
        refutes="The number moves by a fifth or more.",
        evidence=evidence,
        signals=[],
        submitted_at=now.isoformat(),
        run_id=None,
    )
    watch["brief"] = brief.to_json()
    watch["verdict"] = _verdict_json(WatchVerdict.HOLDING, "", WatchActor.PAGE)
    watch["checked_at"] = now.isoformat()
    watch["next_check_at"] = watches.next_check(now).isoformat()
    return watch


def _verdict_json(verdict: WatchVerdict, reason: str, by: WatchActor) -> dict[str, Any]:
    return {"verdict": verdict.value, "reason": reason, "by": by.value, "at": _now().isoformat()}


def _watch_thread(team_id: int, request_id: str) -> tuple[Doc, Comment] | None:
    thread = discussions.thread_for_watch(team_id, request_id)
    if thread is None or not thread.item_id:
        return None
    doc = Doc.objects.for_team(team_id).filter(id=thread.item_id, deleted=False).first()
    return (doc, thread) if doc is not None else None


def _run_may_speak_for(thread: Comment, *, team_id: int, task_id: str) -> bool:
    """The compile run, a run someone tagged in, or a run of the thread's own scout."""
    if (thread.item_context or {}).get("task_id") == task_id:
        return True
    return signals_facade.scout_run_owns_task(team_id, watches.SCOUT_SOURCE_PRODUCT, str(thread.id), task_id)


def submit_watch_brief(
    payload: contracts.SubmitWatchBriefInput, *, request: Any
) -> contracts.SubmitWatchBriefResultDTO | None:
    """The agent hands in what the claim stands on. ``None`` when no such watch exists.

    Raises ``PermissionError`` when the watch belongs to another run.
    """
    found = _watch_thread(payload.team_id, payload.request_id)
    if found is None:
        return None
    doc, thread = found
    if not _run_may_speak_for(thread, team_id=payload.team_id, task_id=payload.task_id):
        raise PermissionError("This watch belongs to another run.")
    brief_json = {
        "claim": payload.claim.strip(),
        "confirms": payload.confirms.strip(),
        "refutes": payload.refutes.strip(),
        "evidence": [
            {"label": entry.label, "query": entry.query} for entry in payload.evidence[: watches.MAX_EVIDENCE]
        ],
        "signals": [entry.strip() for entry in payload.signals if entry.strip()][: watches.MAX_SIGNALS],
    }
    if not brief_json["claim"]:
        return contracts.SubmitWatchBriefResultDTO(ok=False, evidence=[], error="The claim is missing.")
    if not brief_json["evidence"]:
        return contracts.SubmitWatchBriefResultDTO(
            ok=False,
            evidence=[],
            error="Add at least one evidence query: one SELECT that returns one number, or a date and a number per row. Run it once first.",
        )
    return _apply_brief(
        doc, thread, brief_json, run_id=_latest_run_id(payload.task_id, payload.team_id), request=request
    )


def _apply_brief(
    doc: Doc,
    thread: Comment,
    brief_json: dict[str, Any],
    *,
    run_id: str | None,
    request: Any,
    turn_key: str | None = None,
) -> contracts.SubmitWatchBriefResultDTO:
    """Runs the evidence once, keeps the brief, and stands the scout up. A query that does not
    run sends the whole brief back, so the agent fixes it in the same turn."""
    team = Team.objects.get(id=doc.team_id)
    results = []
    evidence = []
    for raw in brief_json["evidence"]:
        checked, result = watches.run_evidence(team, watches.EvidenceInput(label=raw["label"], query=raw["query"]))
        results.append(
            contracts.WatchEvidenceResultDTO(label=result.label, ok=result.ok, value=result.value, error=result.error)
        )
        if checked is not None:
            evidence.append(checked)
    if any(not result.ok for result in results):
        return contracts.SubmitWatchBriefResultDTO(ok=False, evidence=results, error="An evidence query did not run.")

    now = _now()
    brief = watches.Brief(
        claim=brief_json["claim"],
        confirms=brief_json["confirms"],
        refutes=brief_json["refutes"],
        evidence=evidence,
        signals=brief_json["signals"],
        submitted_at=now.isoformat(),
        run_id=run_id,
    )
    had_brief = bool(discussions.watch_of(thread).get("brief"))
    discussions.set_watch(
        thread,
        brief=brief.to_json(),
        verdict=_verdict_json(WatchVerdict.HOLDING, "", WatchActor.PAGE),
        checked_at=now.isoformat(),
        next_check_at=watches.next_check(now).isoformat(),
    )
    scout_line = _ensure_scout(doc, thread, brief, request=request, replace=had_brief)
    checks = len(evidence)
    line = " ".join(
        [
            "Brief updated." if had_brief else "Watching.",
            f"{checks} {'check runs' if checks == 1 else 'checks run'} daily." if checks else "No numbers to recheck.",
            scout_line,
        ]
    )
    discussions.add_post(
        doc,
        thread,
        content=line,
        user_id=None,
        author_kind=PostAuthorKind.SYSTEM,
        run_id=run_id,
        turn_key=turn_key,
        event=WatchEvent.BRIEF.value,
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return contracts.SubmitWatchBriefResultDTO(ok=True, evidence=results, error=None)


def _ensure_scout(doc: Doc, thread: Comment, brief: watches.Brief, *, request: Any, replace: bool) -> str:
    """Stands the hypothesis's scout up, or says why it could not. A watch without a scout still
    rechecks its evidence, so this never fails the brief."""
    watch = discussions.watch_of(thread)
    if watch.get("evidence_only"):
        return ""
    if request is None:
        return "The scout starts when the thread is opened."
    team = doc.team.parent_team or doc.team
    if watch.get("scout") and replace:
        try:
            signals_facade.delete_scout_for_source(
                team=team, source_product=watches.SCOUT_SOURCE_PRODUCT, config_id=str(watch["scout"]["config_id"])
            )
        except Exception:
            logger.exception("doc_watch_scout_delete_failed", thread_id=str(thread.id))
    elif watch.get("scout"):
        return "The scout keeps following the signals."
    definition = watches.scout_definition(
        thread_id=str(thread.id),
        request_id=str((thread.item_context or {}).get("anchor_key") or ""),
        brief=brief,
        doc_title=doc.title or "Untitled",
        page_url=doc_url(doc.channel_id, doc.id),
    )
    try:
        created = signals_facade.create_scout_for_source(
            team=team,
            user=request.user,
            name=definition.name,
            description=definition.description,
            body=definition.body,
            files=[],
            config_options={},
            request=request,
            serializer_context={"project_id": doc.team.project_id, "request": request},
            source_product=watches.SCOUT_SOURCE_PRODUCT,
            source_id=str(thread.id),
        )
    except Exception as err:
        message = str(err).strip().splitlines()[0][:200] if str(err).strip() else "The scout could not be created."
        logger.exception("doc_watch_scout_create_failed", thread_id=str(thread.id))
        discussions.set_watch(thread, scout=None, scout_error=message)
        return "The scout could not start: " + message
    discussions.set_watch(
        thread, scout={"config_id": str(created.config.id), "skill_name": created.config.skill_name}, scout_error=None
    )
    count = len(brief.signals)
    return (
        f"The scout follows {count} {'signal' if count == 1 else 'signals'} daily."
        if count
        else "The scout follows the signals daily."
    )


def submit_watch_verdict(payload: contracts.SubmitWatchVerdictInput) -> bool | None:
    """The agent says where the claim stands. ``None`` when no such watch exists.

    Raises ``PermissionError`` when the watch belongs to another run.
    """
    found = _watch_thread(payload.team_id, payload.request_id)
    if found is None:
        return None
    doc, thread = found
    if not _run_may_speak_for(thread, team_id=payload.team_id, task_id=payload.task_id):
        raise PermissionError("This watch belongs to another run.")
    if payload.verdict in (WatchVerdict.PENDING, WatchVerdict.STALE):
        return False
    if discussions.watch_of(thread).get("status") != WatchStatus.ACTIVE.value:
        return False
    _set_verdict(
        doc,
        thread,
        payload.verdict,
        payload.reason.strip(),
        WatchActor.AGENT,
        run_id=_latest_run_id(payload.task_id, payload.team_id),
    )
    return True


_VERDICT_WORD = {
    WatchVerdict.HOLDING: "Holding",
    WatchVerdict.MOVED: "Moved",
    WatchVerdict.CONFIRMED: "Confirmed",
    WatchVerdict.REFUTED: "Refuted",
}


def _set_verdict(
    doc: Doc,
    thread: Comment,
    verdict: WatchVerdict,
    reason: str,
    by: WatchActor,
    *,
    run_id: str | None = None,
    user_id: int | None = None,
) -> None:
    discussions.set_watch(thread, verdict=_verdict_json(verdict, reason, by))
    line = f"{_VERDICT_WORD[verdict]}. {reason}".strip()
    author = PostAuthorKind.AGENT if by == WatchActor.AGENT else PostAuthorKind.HUMAN
    post = discussions.add_post(
        doc, thread, content=line, user_id=user_id, author_kind=author, run_id=run_id, event=WatchEvent.VERDICT.value
    )
    _tell_people(doc, post)
    if verdict in (WatchVerdict.CONFIRMED, WatchVerdict.REFUTED):
        _stop_watch(doc, thread, WatchStopReason.VERDICT, line=f"{_VERDICT_WORD[verdict]}, so the watch ended.")
    else:
        collab.publish_discussion_change(doc, thread_id=str(thread.id))


def watch_action(payload: contracts.WatchActionInput, *, request: Any = None) -> contracts.DiscussionThreadDTO | None:
    """What a person does to a watch from its thread."""
    doc = _visible_doc(payload.team_id, payload.user_id, payload.doc_id)
    if doc is None:
        return None
    thread = discussions.get_thread(doc, payload.thread_id)
    if (thread.item_context or {}).get("kind") != DiscussionKind.WATCH.value:
        raise discussions.ThreadNotFoundError("This thread is not a watch.")
    if payload.action == WatchAction.CHECK:
        _check_watch(doc, thread, by_person=True)
        _ingest_scout_reports(doc, thread)
    elif payload.action == WatchAction.STOP:
        _stop_watch(doc, thread, WatchStopReason.PERSON, line="Stopped watching.", user_id=payload.user_id)
    elif payload.action == WatchAction.RESUME:
        _resume_watch(doc, thread, line="Watching again.", user_id=payload.user_id)
    elif payload.action == WatchAction.CLOSE and payload.verdict in (WatchVerdict.CONFIRMED, WatchVerdict.REFUTED):
        _set_verdict(doc, thread, payload.verdict, payload.reason, WatchActor.PERSON, user_id=payload.user_id)
    if payload.action in (WatchAction.CHECK, WatchAction.ARM, WatchAction.RESUME) and request is not None:
        _arm_scout(doc, thread, request=request)
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return _reload_thread(doc, thread.id)


def _arm_scout(doc: Doc, thread: Comment, *, request: Any) -> None:
    """A brief that arrived with no person in the room has no scout yet; the first person to act gives it one."""
    watch = discussions.watch_of(thread)
    brief = watches.Brief.from_json(watch.get("brief"))
    if brief is None or watch.get("scout") or watch.get("status") != WatchStatus.ACTIVE.value:
        return
    line = _ensure_scout(doc, thread, brief, request=request, replace=False)
    if discussions.watch_of(thread).get("scout"):
        discussions.add_post(
            doc, thread, content=line, user_id=None, author_kind=PostAuthorKind.SYSTEM, event=WatchEvent.SCOUT.value
        )


def check_due_watches(now: datetime | None = None) -> int:
    """The scheduled tick: rechecks every watch that is due and brings in the scouts' reports.
    Returns how many watches were checked."""
    at = now or _now()
    checked = 0
    for thread in discussions.watch_threads():
        watch = discussions.watch_of(thread)
        if watch.get("status") != WatchStatus.ACTIVE.value or not thread.item_id:
            continue
        doc = Doc.objects.unscoped().filter(id=thread.item_id, deleted=False).select_related("team").first()
        if doc is None:
            continue
        try:
            _ingest_scout_reports(doc, thread)
            due = _when(watch.get("next_check_at"))
            if watch.get("brief") and due is not None and due <= at:
                _check_watch(doc, thread)
                checked += 1
        except Exception:
            logger.exception("doc_watch_check_failed", thread_id=str(thread.id))
    return checked


def _check_watch(doc: Doc, thread: Comment, *, by_person: bool = False) -> None:
    """Runs the evidence again. A move is said once, in one line, and the scout is asked to explain it."""
    watch = discussions.watch_of(thread)
    brief = watches.Brief.from_json(watch.get("brief"))
    now = _now()
    if brief is None:
        discussions.set_watch(thread, checked_at=now.isoformat(), next_check_at=watches.next_check(now).isoformat())
        return
    team = Team.objects.get(id=doc.team_id)
    rechecked = [watches.recheck(team, entry) for entry in brief.evidence]
    new_brief = watches.Brief(
        claim=brief.claim,
        confirms=brief.confirms,
        refutes=brief.refutes,
        evidence=rechecked,
        signals=brief.signals,
        submitted_at=brief.submitted_at,
        run_id=brief.run_id,
    )
    previous = _member(WatchVerdict, (watch.get("verdict") or {}).get("verdict"), WatchVerdict.PENDING)
    verdict = watches.verdict_after_check(new_brief)
    changes: dict[str, Any] = {
        "brief": new_brief.to_json(),
        "checked_at": now.isoformat(),
        "next_check_at": watches.next_check(now).isoformat(),
    }
    if verdict != previous:
        changes["verdict"] = _verdict_json(verdict, "", WatchActor.PAGE)
    discussions.set_watch(thread, **changes)

    newly_moved = [
        entry for entry, before in zip(rechecked, brief.evidence, strict=True) if entry.moved and not before.moved
    ]
    if newly_moved:
        lines = [watches.moved_line(entry) for entry in newly_moved]
        if watch.get("scout") and signals_facade.run_scout_now_for_source(
            doc.team_id, watches.SCOUT_SOURCE_PRODUCT, str(watch["scout"]["config_id"])
        ):
            lines.append("The scout is looking into why.")
        post = discussions.add_post(
            doc,
            thread,
            content=" ".join(lines),
            user_id=None,
            author_kind=PostAuthorKind.SYSTEM,
            event=WatchEvent.MOVED.value,
        )
        _tell_people(doc, post)
    elif verdict == WatchVerdict.STALE and previous != WatchVerdict.STALE:
        error = next((entry.error for entry in rechecked if entry.error), "the query did not run")
        discussions.add_post(
            doc,
            thread,
            content=f"The checks could not run: {error}",
            user_id=None,
            author_kind=PostAuthorKind.SYSTEM,
            event=WatchEvent.STALE.value,
        )
    elif by_person and not newly_moved:
        moved = [entry for entry in rechecked if entry.moved]
        line = "Checked now. " + (
            "Still moved: " + " ".join(watches.moved_line(entry) for entry in moved) if moved else "Everything holds."
        )
        discussions.add_post(
            doc, thread, content=line, user_id=None, author_kind=PostAuthorKind.SYSTEM, event=WatchEvent.CHECK.value
        )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _ingest_scout_reports(doc: Doc, thread: Comment) -> None:
    """Every report the thread's scout filed lands once, as the agent's post."""
    watch = discussions.watch_of(thread)
    if not watch.get("scout"):
        return
    seen = [str(entry) for entry in watch.get("seen_report_ids") or []]
    reports = signals_facade.scout_reports_for_source(
        doc.team_id, watches.SCOUT_SOURCE_PRODUCT, str(thread.id), limit=10
    )
    fresh = [report for report in reports if report.report_id not in seen]
    if not fresh:
        return
    for report in reversed(fresh):
        post = discussions.add_post(
            doc,
            thread,
            content=watches.report_post(report.title, report.summary),
            user_id=None,
            author_kind=PostAuthorKind.AGENT,
            turn_key=f"report:{report.report_id}",
            event=WatchEvent.REPORT.value,
        )
        _tell_people(doc, post)
    discussions.set_watch(thread, seen_report_ids=[*seen, *(report.report_id for report in fresh)][-200:])
    collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _set_scout_enabled(doc: Doc, thread: Comment, enabled: bool) -> None:
    scout = discussions.watch_of(thread).get("scout")
    if not scout:
        return
    try:
        signals_facade.update_scout_for_source(
            doc.team_id, watches.SCOUT_SOURCE_PRODUCT, str(scout["config_id"]), enabled=enabled
        )
    except Exception:
        logger.exception("doc_watch_scout_toggle_failed", thread_id=str(thread.id))


def _stop_watch(doc: Doc, thread: Comment, reason: WatchStopReason, *, line: str, user_id: int | None = None) -> None:
    if discussions.watch_of(thread).get("status") == WatchStatus.STOPPED.value:
        return
    discussions.set_watch(thread, status=WatchStatus.STOPPED.value, stopped_reason=reason.value)
    discussions.set_thread_resolved(doc, thread_id=thread.id, resolved=True)
    _set_scout_enabled(doc, thread, False)
    author = PostAuthorKind.HUMAN if user_id else PostAuthorKind.SYSTEM
    discussions.add_post(doc, thread, content=line, user_id=user_id, author_kind=author, event=WatchEvent.STOPPED.value)
    collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _pause_watch(doc: Doc, thread: Comment, *, line: str) -> None:
    if discussions.watch_of(thread).get("status") != WatchStatus.ACTIVE.value:
        return
    discussions.set_watch(thread, status=WatchStatus.PAUSED.value, stopped_reason=WatchStopReason.PAGE_DONE.value)
    _set_scout_enabled(doc, thread, False)
    discussions.add_post(
        doc, thread, content=line, user_id=None, author_kind=PostAuthorKind.SYSTEM, event=WatchEvent.PAUSED.value
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _resume_watch(doc: Doc, thread: Comment, *, line: str, user_id: int | None = None) -> None:
    watch = discussions.watch_of(thread)
    if watch.get("status") == WatchStatus.ACTIVE.value:
        if (thread.item_context or {}).get("resolved"):
            discussions.set_thread_resolved(doc, thread_id=thread.id, resolved=False)
        return
    now = _now()
    discussions.set_watch(
        thread,
        status=WatchStatus.ACTIVE.value,
        stopped_reason=None,
        next_check_at=now.isoformat() if watch.get("brief") else None,
    )
    discussions.set_thread_resolved(doc, thread_id=thread.id, resolved=False)
    _set_scout_enabled(doc, thread, True)
    author = PostAuthorKind.HUMAN if user_id else PostAuthorKind.SYSTEM
    discussions.add_post(doc, thread, content=line, user_id=user_id, author_kind=author, event=WatchEvent.RESUMED.value)
    collab.publish_discussion_change(doc, thread_id=str(thread.id))


def _pause_page_watches(doc: Doc) -> None:
    for thread in discussions.watch_threads(doc=doc):
        _pause_watch(doc, thread, line="The page is done, so the watch paused.")


def _resume_page_watches(doc: Doc) -> None:
    for thread in discussions.watch_threads(doc=doc):
        watch = discussions.watch_of(thread)
        if watch.get("status") == WatchStatus.PAUSED.value:
            _resume_watch(doc, thread, line="The page is open again, so the watch runs again.")


def _reconcile_watch_anchors(doc: Doc) -> None:
    """A watch whose words left the page stops. The save is the moment the page knows."""
    threads = [
        thread
        for thread in discussions.watch_threads(doc=doc)
        if discussions.watch_of(thread).get("status") != WatchStatus.STOPPED.value
    ]
    if not threads:
        return
    keys = watches.anchor_keys(doc.content)
    for thread in threads:
        if (thread.item_context or {}).get("anchor_key") not in keys:
            _stop_watch(
                doc,
                thread,
                WatchStopReason.SECTION_REMOVED,
                line="The watched words left the page, so the watch stopped.",
            )


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
        event=_member(WatchEvent, context.get("event"), None),
    )


def _to_answer(raw: object) -> contracts.DataAnswerDTO | None:
    if not isinstance(raw, dict) or not raw.get("query"):
        return None
    updated_at = raw.get("updated_at")
    shape = raw.get("shape")
    return contracts.DataAnswerDTO(
        query=str(raw["query"]),
        label=str(raw.get("label") or ""),
        note=str(raw.get("note") or ""),
        shape=DataShape(str(shape)) if str(shape) in {member.value for member in DataShape} else DataShape.NUMBER,
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
        watch=_to_watch(context["watch"]) if isinstance(context.get("watch"), dict) else None,
    )


def _when(raw: object) -> datetime | None:
    return datetime.fromisoformat(raw) if isinstance(raw, str) and raw else None


def _to_watch(raw: dict[str, Any]) -> contracts.DocWatchDTO:
    brief = watches.Brief.from_json(raw.get("brief"))
    raw_verdict = raw.get("verdict")
    verdict: dict[str, Any] = raw_verdict if isinstance(raw_verdict, dict) else {}
    scout = raw.get("scout") if isinstance(raw.get("scout"), dict) else None
    return contracts.DocWatchDTO(
        status=_member(WatchStatus, raw.get("status"), WatchStatus.ACTIVE),
        stopped_reason=_member(WatchStopReason, raw.get("stopped_reason"), None),
        verdict=contracts.WatchVerdictDTO(
            verdict=_member(WatchVerdict, verdict.get("verdict"), WatchVerdict.PENDING),
            reason=str(verdict.get("reason") or ""),
            by=_member(WatchActor, verdict.get("by"), WatchActor.PAGE),
            at=_when(verdict.get("at")),
        ),
        brief=contracts.WatchBriefDTO(
            claim=brief.claim,
            confirms=brief.confirms,
            refutes=brief.refutes,
            evidence=[
                contracts.WatchEvidenceDTO(
                    label=entry.label,
                    query=entry.query,
                    shape=_member(DataShape, entry.shape, DataShape.NUMBER),
                    baseline=entry.baseline,
                    value=entry.value,
                    checked_at=_when(entry.checked_at),
                    error=entry.error,
                    history=entry.history,
                    moved=entry.moved,
                )
                for entry in brief.evidence
            ],
            signals=brief.signals,
            submitted_at=_when(brief.submitted_at),
        )
        if brief
        else None,
        scout=contracts.WatchScoutDTO(config_id=str(scout["config_id"]), skill_name=str(scout["skill_name"]))
        if scout and scout.get("config_id")
        else None,
        scout_error=raw.get("scout_error") or None,
        next_check_at=_when(raw.get("next_check_at")),
        checked_at=_when(raw.get("checked_at")),
        evidence_only=bool(raw.get("evidence_only", False)),
    )


def _member(enum: Any, raw: object, default: Any) -> Any:
    values = {member.value for member in enum}
    return enum(str(raw)) if str(raw) in values else default


def _reload_thread(doc: Doc, thread_id: str | UUID) -> contracts.DiscussionThreadDTO:
    thread = discussions.get_thread(doc, thread_id)
    return _to_thread(thread, discussions.list_replies(doc, [thread.id]))
