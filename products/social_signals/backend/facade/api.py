"""
Facade API for social_signals.

The ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen-dataclass DTOs as input
- Call domain logic (``backend.logic``)
- Convert Django models to DTOs before returning
- Remain thin and stable

Do NOT:
- Implement business logic here (use ``logic/``)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets

Reserved seams for future cross-product wiring (not implemented yet):

- ``request_signal_emission`` will call ``products.signals.backend.facade.emit_signal``
  with ``source_product="social_signals"`` once Signals adds that source to its enum.
- ``create_ticket_from_mention`` will call into the Conversations product's
  ticket facade. Conversations does not yet expose a public facade for ticket
  creation; we just store enough on Mention to construct one later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .. import logic
from ..logic import ingestion
from ..logic.adapters import get_adapter
from . import contracts

if TYPE_CHECKING:
    from ..models import Mention as MentionModel
    from ..models import MentionAnalysis as MentionAnalysisModel
    from ..models import MentionSource as MentionSourceModel

# Re-export domain exceptions so callers don't reach into ``logic``.
MentionNotFoundError = logic.MentionNotFoundError
MentionSourceNotFoundError = logic.MentionSourceNotFoundError
UnknownAdapterError = logic.UnknownAdapterError


# --- Mappers (ORM model -> frozen dataclass DTO) ---


def _to_analysis(analysis: "MentionAnalysisModel") -> contracts.MentionAnalysis:
    return contracts.MentionAnalysis(
        id=analysis.id,
        mention_id=analysis.mention_id,
        kind=analysis.kind,
        status=analysis.status,
        result=dict(analysis.result or {}),
        model_used=analysis.model_used,
        error=analysis.error,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def _to_mention(mention: "MentionModel", *, include_analyses: bool = True) -> contracts.Mention:
    analyses: list[contracts.MentionAnalysis] = []
    if include_analyses:
        # Cheap when ``prefetch_related('analyses')`` was used upstream;
        # one extra query per mention otherwise — acceptable for retrieve.
        analyses = [_to_analysis(a) for a in mention.analyses.all()]
    return contracts.Mention(
        id=mention.id,
        team_id=mention.team_id,
        source_id=mention.source_id,
        platform=mention.platform,
        mention_type=mention.mention_type,
        external_id=mention.external_id,
        url=mention.url,
        content=mention.content,
        language=mention.language,
        author_handle=mention.author_handle,
        author_display_name=mention.author_display_name,
        author_profile_url=mention.author_profile_url,
        author_followers=mention.author_followers,
        posted_at=mention.posted_at,
        captured_at=mention.captured_at,
        engagement=dict(mention.engagement or {}),
        status=mention.status,
        last_error=mention.last_error,
        updated_at=mention.updated_at,
        analyses=analyses,
    )


def _to_source(source: "MentionSourceModel") -> contracts.MentionSource:
    return contracts.MentionSource(
        id=source.id,
        team_id=source.team_id,
        kind=source.kind,
        enabled=source.enabled,
        ingest_token=source.ingest_token,
        config=dict(source.config or {}),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


# --- Source API ---


def list_sources(team_id: int) -> list[contracts.MentionSource]:
    return [_to_source(s) for s in ingestion.list_sources(team_id)]


def get_source(*, team_id: int, source_id: UUID) -> contracts.MentionSource:
    return _to_source(ingestion.get_source(team_id=team_id, source_id=source_id))


def get_or_create_source(*, team_id: int, kind: str) -> contracts.MentionSource:
    source, _ = ingestion.get_or_create_source(team_id=team_id, kind=kind)
    return _to_source(source)


def rotate_source_token(*, team_id: int, source_id: UUID) -> contracts.MentionSource:
    source = ingestion.get_source(team_id=team_id, source_id=source_id)
    source.rotate_token()
    source.refresh_from_db()
    return _to_source(source)


# --- Mention API ---


def list_mentions(
    *,
    team_id: int,
    filters: contracts.MentionFilters,
) -> list[contracts.Mention]:
    qs = ingestion.list_mentions(team_id=team_id, filters=filters)
    rows = list(qs[filters.offset : filters.offset + filters.limit])
    return [_to_mention(m) for m in rows]


def get_mention(*, team_id: int, mention_id: UUID) -> contracts.Mention:
    return _to_mention(ingestion.get_mention(team_id=team_id, mention_id=mention_id))


# --- Ingestion API ---


def ingest_from_webhook(*, ingest_token: str, payload: dict) -> contracts.IngestResult:
    """Decode a webhook payload by its ingest_token, upsert mentions, dispatch
    analyzer tasks on commit. Returns counts of newly-accepted vs. dedup'd.

    Raises:
        MentionSourceNotFoundError: when no enabled source matches the token.
        UnknownAdapterError: when the matched source has an adapter kind that
            isn't registered (shouldn't happen unless an adapter is removed
            after a source was created with that kind).
    """
    source = ingestion.get_source_by_token(ingest_token)
    adapter = get_adapter(source.kind)
    inputs = adapter.to_create_inputs(payload, source)
    accepted, skipped = ingestion.ingest_batch(inputs)
    return contracts.IngestResult(accepted=accepted, skipped=skipped)


def ingest_mention(params: contracts.CreateMentionInput) -> contracts.Mention:
    """Direct ingestion entry point — used by future pollers / manual API push.
    Webhook ingestion goes through ``ingest_from_webhook``.
    """
    accepted, _ = ingestion.ingest_batch([params])
    # Re-fetch through the team-scoped manager so we return the canonical row.
    mention = ingestion.get_mention(team_id=params.team_id, mention_id=_resolve_id(params))
    return _to_mention(mention)


def _resolve_id(params: contracts.CreateMentionInput) -> UUID:
    """Look up the id of the mention identified by an input's dedup key."""
    from ..models import Mention

    return Mention.objects.values_list("id", flat=True).get(
        team_id=params.team_id,
        source_id=params.source_id,
        external_id=params.external_id,
    )
