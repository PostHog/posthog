"""
Facade for docs.

The ONLY module other products and this product's own presentation layer are allowed
to import. Accept frozen dataclasses, call logic/, return frozen dataclasses. Never
return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from django.conf import settings

from posthog.models.comment import Comment
from posthog.models.user import User

from ..logic import collab, discussions, documents, kpis
from ..models import Doc, SpaceKpi
from . import contracts
from .enums import CollabSubmitStatus, DocStatus

ChannelNotVisibleError = documents.ChannelNotVisibleError
ThreadNotFoundError = discussions.ThreadNotFoundError


def doc_url(channel_id: str | UUID, doc_id: str | UUID) -> str:
    """Canonical link to a doc. Share this when pointing someone at one; never build the URL yourself."""
    return f"{settings.SITE_URL}/code/docs/{channel_id}/{doc_id}"


# --- Docs ---


def list_docs(team_id: int, user_id: int | None, channel_id: str | UUID | None) -> list[contracts.DocSummaryDTO]:
    queryset = documents.visible_docs(team_id, user_id).defer("content", "text_content")
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


def space_home(team_id: int, user_id: int | None, channel_id: str | UUID) -> contracts.SpaceHomeDTO:
    docs = documents.docs_in_channel(team_id, user_id, channel_id).defer("content", "text_content")
    return contracts.SpaceHomeDTO(
        docs=[_to_summary(doc) for doc in docs],
        kpis=[_to_kpi(kpi) for kpi in kpis.kpis_in_channel(team_id, user_id, channel_id)],
    )


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


def create_thread(
    team_id: int, user_id: int, doc_id: str | UUID, *, content: str, anchor_key: str, anchor_text: str
) -> contracts.DiscussionThreadDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    thread = discussions.create_thread(
        doc, user_id=user_id, content=content, anchor_key=anchor_key, anchor_text=anchor_text
    )
    collab.publish_discussion_change(doc, thread_id=str(thread.id))
    return _to_thread(thread, [])


def reply_to_thread(
    team_id: int, user_id: int, doc_id: str | UUID, *, thread_id: str | UUID, content: str
) -> contracts.DiscussionThreadDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    discussions.reply_to_thread(doc, thread_id=thread_id, user_id=user_id, content=content)
    collab.publish_discussion_change(doc, thread_id=str(thread_id))
    return _reload_thread(doc, thread_id)


def set_thread_resolved(
    team_id: int, user_id: int | None, doc_id: str | UUID, *, thread_id: str | UUID, resolved: bool
) -> contracts.DiscussionThreadDTO | None:
    doc = _visible_doc(team_id, user_id, doc_id)
    if doc is None:
        return None
    discussions.set_thread_resolved(doc, thread_id=thread_id, resolved=resolved)
    collab.publish_discussion_change(doc, thread_id=str(thread_id))
    return _reload_thread(doc, thread_id)


# --- Numbers the space watches ---


def list_kpis(team_id: int, user_id: int | None, channel_id: str | UUID | None) -> list[contracts.SpaceKpiDTO]:
    queryset = kpis.visible_kpis(team_id, user_id)
    if channel_id:
        queryset = queryset.filter(channel_id=channel_id)
    return [_to_kpi(kpi) for kpi in queryset.order_by("position", "created_at")]


def create_kpi(payload: contracts.CreateKpiInput) -> contracts.SpaceKpiDTO:
    return _to_kpi(
        kpis.create_kpi(
            team_id=payload.team_id,
            user_id=payload.user_id,
            channel_id=payload.channel_id,
            name=payload.name,
            insight_short_id=payload.insight_short_id,
        )
    )


def delete_kpi(team_id: int, user_id: int | None, kpi_id: str | UUID) -> bool:
    kpi = kpis.visible_kpis(team_id, user_id).filter(id=kpi_id).first()
    if kpi is None:
        return False
    kpis.soft_delete_kpi(kpi)
    return True


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


def _to_summary(doc: Doc) -> contracts.DocSummaryDTO:
    return contracts.DocSummaryDTO(
        id=doc.id,
        channel_id=doc.channel_id,
        title=doc.title,
        status=DocStatus(doc.status),
        position=doc.position,
        version=doc.version,
        created_by=_to_person(doc.created_by),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_doc(doc: Doc) -> contracts.DocDTO:
    return contracts.DocDTO(
        id=doc.id,
        channel_id=doc.channel_id,
        title=doc.title,
        status=DocStatus(doc.status),
        position=doc.position,
        version=doc.version,
        content=doc.content,
        text_content=doc.text_content or "",
        created_by=_to_person(doc.created_by),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_kpi(kpi: SpaceKpi) -> contracts.SpaceKpiDTO:
    return contracts.SpaceKpiDTO(
        id=kpi.id,
        channel_id=kpi.channel_id,
        name=kpi.name,
        insight_short_id=kpi.insight_short_id,
        position=kpi.position,
        created_by=_to_person(kpi.created_by),
        created_at=kpi.created_at,
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
        replies=[
            contracts.DiscussionPostDTO(
                id=reply.id,
                content=reply.content or "",
                created_by=_to_person(reply.created_by),
                created_at=reply.created_at,
            )
            for reply in replies
        ],
    )


def _reload_thread(doc: Doc, thread_id: str | UUID) -> contracts.DiscussionThreadDTO:
    thread = discussions.get_thread(doc, thread_id)
    return _to_thread(thread, discussions.list_replies(doc, [thread.id]))
