import asyncio
import dataclasses

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.accountability import OpportunityStatusLine, collect_accountability
from products.pulse.backend.generation.persist import opportunity_fingerprint, persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut
from products.pulse.backend.generation.synthesize import synthesize_brief
from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.registry import get_sources
from products.pulse.backend.temporal.inputs import (
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    SynthesizeActivityInputs,
)
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

# The cap guards Temporal's ~2 MiB activity payload limit; truncation is priority-aware so a
# chatty low-priority source can't crowd out actionable items.
MAX_ITEMS = 50
KIND_PRIORITY: dict[str, int] = {"health": 0, "signal": 1, "movement": 2, "context": 3}


class BriefGenerationFailed(Exception):
    """Carries workflow failures into error tracking; the full stack lives in Temporal."""


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _get_config(team: Team, brief_config_id: str | None) -> BriefConfig | None:
    if not brief_config_id:
        return None
    return BriefConfig.objects.for_team(team.pk).filter(id=brief_config_id).first()


def _get_brief(team_id: int, brief_id: str) -> ProductBrief:
    return (
        ProductBrief.objects.for_team(team_id)
        .select_related("team__organization", "created_by", "config")
        .get(id=brief_id)
    )


def _mark_brief_failed(team_id: int, brief_id: str, error: str) -> None:
    ProductBrief.objects.for_team(team_id).filter(id=brief_id).update(status=ProductBrief.Status.FAILED, error=error)


@temporalio.activity.defn
async def gather_brief_inputs_activity(inputs: GenerateBriefWorkflowInputs) -> list[dict]:
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(inputs.team_id)
    if not team.organization.is_ai_data_processing_approved:
        raise ApplicationError("AI data processing not approved for this organization", non_retryable=True)
    config = await database_sync_to_async(_get_config, thread_sensitive=False)(team, inputs.brief_config_id)
    sources = get_sources()
    items: list[SourceItem] = []
    failed_sources = 0
    for source in sources:
        try:
            gathered = await database_sync_to_async(source.gather, thread_sensitive=False)(
                team, config, inputs.period_days
            )
        except Exception:
            # One broken source must not kill the brief; the other sources still contribute.
            logger.exception("pulse_source_gather_failed", team_id=team.id, source=source.name)
            failed_sources += 1
            continue
        items.extend(gathered)
    if sources and failed_sources == len(sources):
        # Every source broke: that's a failure to retry. Partial failure in a quiet week is not.
        raise ApplicationError(f"brief gather failed: all {failed_sources} source(s) failed")
    # Stable sort: highest-priority kinds survive the cap, source order preserved within a kind.
    items.sort(key=lambda item: KIND_PRIORITY.get(item.kind, len(KIND_PRIORITY)))
    return [dataclasses.asdict(item) for item in items[:MAX_ITEMS]]


@temporalio.activity.defn
async def synthesize_brief_activity(inputs: SynthesizeActivityInputs) -> str:
    brief = await database_sync_to_async(_get_brief, thread_sensitive=False)(inputs.team_id, inputs.brief_id)
    if brief.created_by is None:
        raise ApplicationError("brief has no creating user for LLM attribution", non_retryable=True)
    items = [SourceItem(**item) for item in inputs.items]
    status_lines: list[OpportunityStatusLine] = []
    # Accountability is not movement-gated — past suggestions matter every period. Only an
    # empty gather skips it, since synthesize short-circuits without items anyway.
    # Best-effort: a broken re-score degrades to no accountability section.
    if items:
        try:
            status_lines = await database_sync_to_async(collect_accountability, thread_sensitive=False)(brief.team)
        except Exception:
            logger.exception("pulse_accountability_failed", team_id=brief.team_id, brief_id=str(brief.id))
    out = await synthesize_brief(
        team=brief.team,
        user=brief.created_by,
        config=brief.config,
        items=items,
        period_days=brief.period_days,
        status_lines=status_lines,
    )
    created = await database_sync_to_async(persist_brief_output, thread_sensitive=False)(
        brief=brief, out=out, items=items
    )
    await _emit_opportunity_signals(brief, out, created)
    return brief.status


async def _emit_opportunity_signals(brief: ProductBrief, out: BriefOut, created: list[Opportunity]) -> None:
    """Surface newly created opportunities in the signals inbox via the signals facade.

    Deduped fingerprints never re-emit (they were surfaced by an earlier brief), delivery is
    opt-in per team (a `pulse` SignalSourceConfig row, checked inside emit_signal), and each
    emit is best-effort — a failure must never fail the brief.
    """
    confidence_by_fingerprint: dict[str, float] = {}
    for opp in out.opportunities:
        # First-wins to match persist's dedup: the first opportunity with a fingerprint is the
        # one persisted, so its confidence is the weight that gets emitted.
        confidence_by_fingerprint.setdefault(opportunity_fingerprint(opp.kind, opp.fingerprint_hint), opp.confidence)
    # Independent best-effort emits, run concurrently (each still pays its own Temporal connect).
    await asyncio.gather(
        *(_emit_opportunity_signal(brief, opportunity, confidence_by_fingerprint) for opportunity in created)
    )


async def _emit_opportunity_signal(
    brief: ProductBrief, opportunity: Opportunity, confidence_by_fingerprint: dict[str, float]
) -> None:
    try:
        await emit_signal(
            team=brief.team,
            source_product="pulse",
            source_type=f"opportunity_{opportunity.kind}",
            source_id=str(opportunity.id),
            description=f"{opportunity.title}\n\n{opportunity.summary}",
            # The LLM's confidence passes through as the signal weight (weight 1.0 triggers
            # signals' summary path). The map cannot miss — fingerprints are minted from the
            # same output — so a broken invariant surfaces here as a logged emit failure.
            weight=confidence_by_fingerprint[opportunity.fingerprint],
            extra={"brief_id": str(brief.id), "evidence": opportunity.evidence},
        )
    except Exception:
        logger.exception(
            "pulse_opportunity_signal_emit_failed",
            team_id=brief.team_id,
            brief_id=str(brief.id),
            opportunity_id=str(opportunity.id),
        )


@temporalio.activity.defn
async def mark_brief_failed_activity(inputs: MarkBriefFailedInputs) -> None:
    logger.error("pulse_brief_generation_failed", team_id=inputs.team_id, brief_id=inputs.brief_id, error=inputs.error)
    # The workflow sandbox can't reach error tracking, so failure volume is captured here.
    capture_exception(
        BriefGenerationFailed(inputs.error),
        {"team_id": inputs.team_id, "brief_id": inputs.brief_id, "product": "pulse"},
    )
    await database_sync_to_async(_mark_brief_failed, thread_sensitive=False)(
        inputs.team_id, inputs.brief_id, inputs.error
    )
