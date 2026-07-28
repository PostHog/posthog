from datetime import timedelta
from typing import Any

from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.formatting import extract_images_from_rich_content
from products.conversations.backend.models import Ticket
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.models import SignalEmissionRecord

logger = structlog.get_logger(__name__)

# How long a thread must be quiet before it is snapshotted. Keyed off the last message rather than
# ticket creation, because the decisive detail in a support thread (the repro, the error text, the
# escalation) usually arrives in a reply, not the opening message.
TICKET_QUIET_PERIOD_HOURS = 1
# Floor between successive snapshots of the same ticket. A thread that keeps going gets re-read, but
# at most once a window, so a chatty ticket can't emit a signal per lull.
TICKET_RESNAPSHOT_MIN_INTERVAL_HOURS = 24


def conversations_ticket_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch conversation tickets from Postgres and record emission in SignalEmissionRecord."""
    now = timezone.now()
    quiet_since = now - timedelta(hours=TICKET_QUIET_PERIOD_HOURS)
    resnapshot_floor = now - timedelta(hours=TICKET_RESNAPSHOT_MIN_INTERVAL_HOURS)
    lookback = now - timedelta(days=config.first_sync_lookback_days)
    # Quiet for long enough, measured from the last message when there is one. Tickets predating
    # last_message_at backfill fall back to created_at.
    thread_is_quiet = Q(last_message_at__lte=quiet_since) | Q(last_message_at__isnull=True, created_at__lte=quiet_since)
    # Skip a ticket when we already snapshotted it at or after its latest message (nothing new to
    # read), or when the last snapshot is too recent to take another.
    snapshot_still_current = SignalEmissionRecord.objects.filter(
        team=team,
        source_product=config.source_product,
        source_type=config.source_type,
        source_id=Cast(OuterRef("id"), output_field=CharField()),
    ).filter(
        Q(emitted_at__gte=Coalesce(OuterRef("last_message_at"), OuterRef("created_at")))
        | Q(emitted_at__gte=resnapshot_floor)
    )
    tickets_qs = Ticket.objects.filter(team=team, created_at__gte=lookback).filter(
        thread_is_quiet, ~Exists(snapshot_still_current)
    )
    if config.where_clause:
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (where_clause is a hardcoded config constant, not user input)
        tickets_qs = tickets_qs.extra(where=[config.where_clause])
    tickets_qs = tickets_qs.values(*config.fields).order_by(config.partition_field)[: config.max_records]
    tickets = list(tickets_qs)
    if not tickets:
        return []
    ticket_ids = [t["id"] for t in tickets]
    logger.info(
        "Fetched conversation tickets for signal emission",
        team_id=team.id,
        ticket_count=len(tickets),
        signals_type="conversations-signals",
    )
    # Fetch all comments for these tickets in one query.
    # Each message is a (author_type, content) tuple so the emitter can attribute them.
    comments_by_ticket: dict[str, list[tuple[str, str]]] = {}
    # Image URLs from rich_content are attached per-ticket as image_attachments.
    images_by_ticket: dict[str, list[dict[str, str]]] = {}
    comments_qs = (
        Comment.objects.filter(
            team=team,
            scope="conversations_ticket",
            item_id__in=[str(tid) for tid in ticket_ids],
            deleted=False,
        )
        # Exclude private notes and AI drafts (mirrors widget.py / suggest.py semantics)
        .filter(~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True))
        .order_by("created_at")
        .values_list("item_id", "content", "item_context", "rich_content")
    )
    for item_id, content, item_context, rich_content in comments_qs:
        author_type = (item_context or {}).get("author_type", "customer")
        if content:
            comments_by_ticket.setdefault(item_id, []).append((author_type, content))
        for image in extract_images_from_rich_content(rich_content):
            src = image.get("url")
            if src:
                images_by_ticket.setdefault(item_id, []).append({"url": src, "author": author_type})
    # Attach messages and image attachments to each ticket record
    for ticket in tickets:
        ticket_id = str(ticket["id"])
        ticket["messages"] = comments_by_ticket.get(ticket_id, [])
        ticket["image_attachments"] = images_by_ticket.get(ticket_id, [])
    # Record emission optimistically. Upsert rather than ignore conflicts, because a re-snapshotted
    # ticket already has a row and its emitted_at is what gates the next one.
    # TODO: Revisit if signal loss on transient pipeline failure becomes a concern
    SignalEmissionRecord.objects.bulk_create(
        [
            SignalEmissionRecord(
                team=team,
                source_product=config.source_product,
                source_type=config.source_type,
                source_id=str(tid),
                emitted_at=now,
            )
            for tid in ticket_ids
        ],
        update_conflicts=True,
        update_fields=["emitted_at"],
        unique_fields=["team", "source_product", "source_type", "source_id"],
    )
    return tickets
