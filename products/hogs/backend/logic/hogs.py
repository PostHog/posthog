"""Hogs, their chat messages, and the actions a hog takes through its tools."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Count, Q
from django.utils import timezone

from ..facade.enums import HogMessageAuthor, HogStatus, HogWakeCause
from ..models import Hog, HogMessage
from . import runner

GREETING = (
    "Hi, I'm {name}. Tell me what you want me to look after: what I should watch, "
    "what is worth telling you about, and how often I should check."
)


def list_hogs(*, team_id: int, user_id: int) -> list[Hog]:
    for hog in Hog.objects.filter(team_id=team_id, created_by_id=user_id, deleted=False, working_since__isnull=False):
        runner.settle_finished_run(hog)
    return list(
        Hog.objects.filter(team_id=team_id, created_by_id=user_id, deleted=False)
        .annotate(
            unread_count=Count(
                "messages",
                filter=Q(messages__in_chat=True, messages__read_at__isnull=True)
                & ~Q(messages__author=HogMessageAuthor.USER.value),
            )
        )
        .order_by("-last_message_at", "-created_at")
    )


def get_hog(*, team_id: int, user_id: int, hog_id: UUID) -> Hog | None:
    return Hog.objects.filter(team_id=team_id, created_by_id=user_id, deleted=False, id=hog_id).first()


def last_chat_messages(hogs: list[Hog]) -> dict[UUID, HogMessage]:
    latest: dict[UUID, HogMessage] = {}
    for hog in hogs:
        message = (
            HogMessage.objects.filter(hog=hog, in_chat=True)
            .select_related("report__hog", "action__hog")
            .order_by("-created_at")
            .first()
        )
        if message is not None:
            latest[hog.id] = message
    return latest


def create_hog(
    *,
    team_id: int,
    user_id: int,
    name: str,
    emoji: str,
    color: str,
    responsibility: str,
    mcp_installation_ids: list[str],
) -> Hog:
    hog = Hog.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=name,
        emoji=emoji,
        color=color,
        responsibility=responsibility,
        status=(HogStatus.ACTIVE if responsibility.strip() else HogStatus.SETUP).value,
        mcp_installation_ids=mcp_installation_ids,
    )
    if hog.status == HogStatus.SETUP:
        add_message(hog, author=HogMessageAuthor.HOG, content=GREETING.format(name=name))
    return hog


def update_hog(hog: Hog, **changes) -> Hog:
    for field, value in changes.items():
        setattr(hog, field, value.value if isinstance(value, HogStatus) else value)
    hog.save(update_fields=[*changes.keys(), "updated_at"])
    return hog


def delete_hog(hog: Hog) -> None:
    hog.deleted = True
    hog.save(update_fields=["deleted", "updated_at"])
    hog.schedules.update(enabled=False)


def add_message(hog: Hog, *, author: HogMessageAuthor, content: str, **fields) -> HogMessage:
    message = HogMessage.objects.create(team_id=hog.team_id, hog=hog, author=author.value, content=content, **fields)
    if message.in_chat:
        hog.last_message_at = message.created_at
        hog.save(update_fields=["last_message_at", "updated_at"])
    return message


def list_messages(hog: Hog, *, after: datetime | None, include_internal: bool) -> list[HogMessage]:
    messages = HogMessage.objects.filter(hog=hog).select_related("from_hog", "report__hog", "action__hog")
    if not include_internal:
        messages = messages.filter(in_chat=True)
    if after is not None:
        messages = messages.filter(created_at__gt=after)
    return list(messages.order_by("created_at")[:500])


def send_user_message(hog: Hog, *, content: str) -> HogMessage:
    """The owner's message: stored first so the chat shows it, then handed to the hog."""
    message = add_message(hog, author=HogMessageAuthor.USER, content=content)
    if hog.status == HogStatus.PAUSED:
        return message
    if runner.wake_hog(hog, trigger=f"Your owner sent you a message:\n\n{content}", cause=HogWakeCause.USER):
        message.delivered_at = timezone.now()
        message.task_run_id = hog.current_run_id
        message.save(update_fields=["delivered_at", "task_run_id"])
    return message


def mark_read(hog: Hog) -> int:
    return HogMessage.objects.filter(hog=hog, in_chat=True, read_at__isnull=True).update(read_at=timezone.now())


def mark_seen(hog: Hog) -> None:
    """Any tool call shows the hog has picked up what its owner sent."""
    HogMessage.objects.filter(hog=hog, author=HogMessageAuthor.USER.value, seen_at__isnull=True).update(
        seen_at=timezone.now()
    )


def hog_say(hog: Hog, *, content: str) -> HogMessage:
    mark_seen(hog)
    return add_message(hog, author=HogMessageAuthor.HOG, content=content, task_run_id=hog.current_run_id)


def hog_tell(hog: Hog, *, to_hog: Hog, content: str) -> HogMessage:
    """Raises runner.WakeRefused when the note would take a chain of notes past the hop limit."""
    mark_seen(hog)
    hops = hog.wake_hops + 1
    if hops > runner.MAX_HOPS:
        raise runner.WakeRefused(
            f"You were woken by a chain of {hog.wake_hops} hog-to-hog notes and the limit is {runner.MAX_HOPS}, "
            "so this note was not sent. Tell your owner with hog-say if it matters."
        )
    message = add_message(to_hog, author=HogMessageAuthor.HOG, content=content, in_chat=False, from_hog=hog)
    if to_hog.status != HogStatus.PAUSED:
        runner.wake_hog(
            to_hog,
            trigger=f"Another hog, {hog.name} (ID {hog.id}), sent you a note:\n\n{content}",
            cause=HogWakeCause.NOTE,
            hops=hops,
        )
    return message


def hog_done(hog: Hog) -> Hog:
    mark_seen(hog)
    hog.working_since = None
    hog.save(update_fields=["working_since", "updated_at"])
    return hog
