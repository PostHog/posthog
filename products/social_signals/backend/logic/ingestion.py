"""Ingestion logic for social_signals.

Idempotent upserts on ``(team_id, source, external_id)`` and dispatch of
analyzer Celery tasks. The facade is the only intended caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from ..facade.contracts import CreateMentionInput, MentionFilters
from ..facade.enums import ProcessingStatus
from ..models import Mention, MentionSource
from .errors import MentionSourceNotFoundError

if TYPE_CHECKING:
    from django.db.models import QuerySet


def get_source_by_token(token: str) -> MentionSource:
    """Look up an *enabled* source by its ingest_token.

    We don't expose a "source exists but is disabled" distinction — both
    surface as the same NotFound to the caller, who maps it to a 404 to
    avoid leaking token-existence (see legal_documents webhook pattern).
    """
    try:
        # `all_teams` because the webhook view runs without team context;
        # the token itself is the credential. Once we have the row we set
        # team_scope for downstream calls.
        return MentionSource.all_teams.get(ingest_token=token, enabled=True)
    except MentionSource.DoesNotExist as exc:
        raise MentionSourceNotFoundError("No enabled source matches the given token") from exc


def get_or_create_source(*, team_id: int, kind: str) -> tuple[MentionSource, bool]:
    """Return ``(source, created)`` for a given team + kind."""
    return MentionSource.objects.get_or_create(team_id=team_id, kind=kind)


def list_sources(team_id: int) -> list[MentionSource]:
    return list(MentionSource.objects.filter(team_id=team_id).order_by("kind"))


def get_source(*, team_id: int, source_id: UUID) -> MentionSource:
    try:
        return MentionSource.objects.get(team_id=team_id, id=source_id)
    except MentionSource.DoesNotExist as exc:
        raise MentionSourceNotFoundError(f"No source {source_id} for team {team_id}") from exc


def upsert_mention(params: CreateMentionInput) -> tuple[Mention, bool]:
    """Idempotent upsert keyed on ``(team_id, source_id, external_id)``.

    Returns ``(mention, created)``. Caller dispatches downstream work
    (analyzer Celery task) only when ``created`` is True.
    """
    defaults = {
        "platform": params.platform,
        "mention_type": params.mention_type,
        "url": params.url,
        "content": params.content,
        "language": params.language,
        "author_handle": params.author_handle,
        "author_display_name": params.author_display_name,
        "author_profile_url": params.author_profile_url,
        "author_followers": params.author_followers,
        "posted_at": params.posted_at,
        "engagement": params.engagement,
        "raw_payload": params.raw_payload,
    }
    mention, created = Mention.objects.update_or_create(
        team_id=params.team_id,
        source_id=params.source_id,
        external_id=params.external_id,
        defaults=defaults,
    )
    return mention, created


def ingest_batch(inputs: list[CreateMentionInput]) -> tuple[int, int]:
    """Run upserts in a single transaction; dispatch analyzer tasks on commit.

    Returns ``(accepted, skipped)`` where accepted = newly-created mentions
    that triggered an analyzer dispatch, and skipped = repeat deliveries that
    were updates only.
    """
    # Inline import to avoid a circular reference between logic and tasks;
    # tasks.py imports the facade which imports logic.
    from ..tasks.tasks import analyze_mention_task

    accepted = 0
    skipped = 0
    newly_created_ids: list[UUID] = []

    with transaction.atomic(using="social_signals"):
        for inp in inputs:
            _, created = upsert_mention(inp)
            if created:
                accepted += 1
                # We need the id after the upsert; refetch is unnecessary
                # because update_or_create returns the saved instance.
                _mention_id = _last_upserted_id(inp)
                if _mention_id is not None:
                    newly_created_ids.append(_mention_id)
            else:
                skipped += 1

        # Registered inside the atomic block so it's tied to this txn's
        # lifecycle — fires once after commit, never runs if we roll back.
        def _dispatch_all() -> None:
            for mid in newly_created_ids:
                analyze_mention_task.delay(mention_id=str(mid))

        transaction.on_commit(_dispatch_all, using="social_signals")

    return accepted, skipped


def _last_upserted_id(inp: CreateMentionInput) -> UUID | None:
    """Resolve the mention id for the row just upserted by ``upsert_mention``.

    ``update_or_create`` returns the instance directly, but ``ingest_batch``
    discards it for clarity; we re-query here. A small extra SELECT is fine —
    webhook batches are tiny in practice.
    """
    try:
        return Mention.all_teams.values_list("id", flat=True).get(
            team_id=inp.team_id,
            source_id=inp.source_id,
            external_id=inp.external_id,
        )
    except Mention.DoesNotExist:
        return None


def list_mentions(*, team_id: int, filters: MentionFilters) -> "QuerySet[Mention]":
    qs = Mention.objects.filter(team_id=team_id).select_related("source")
    if filters.platform:
        qs = qs.filter(platform=filters.platform)
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.search:
        qs = qs.filter(content__icontains=filters.search)
    if filters.posted_after:
        qs = qs.filter(posted_at__gte=filters.posted_after)
    if filters.posted_before:
        qs = qs.filter(posted_at__lte=filters.posted_before)
    # Pagination at the boundary; views handle DRF pagination on top of this.
    return qs.prefetch_related("analyses")


def get_mention(*, team_id: int, mention_id: UUID) -> Mention:
    try:
        return (
            Mention.objects.filter(team_id=team_id, id=mention_id)
            .select_related("source")
            .prefetch_related("analyses")
            .get()
        )
    except Mention.DoesNotExist as exc:
        from .errors import MentionNotFoundError

        raise MentionNotFoundError(f"No mention {mention_id} for team {team_id}") from exc


def mark_mention_status(
    *,
    team_id: int,
    mention_id: UUID,
    status: ProcessingStatus,
    last_error: str = "",
) -> None:
    """Update a mention's pipeline status. Used by analyzer tasks."""
    Mention.objects.filter(team_id=team_id, id=mention_id).update(
        status=status.value,
        last_error=last_error,
    )
