import asyncio
import datetime as dt
import dataclasses

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async

from products.pulse.backend.agent.mission import build_general_brief_mission
from products.pulse.backend.config import MAX_ITEMS
from products.pulse.backend.generation.accountability import MIN_AGE_DAYS, OpportunityStatusLine, collect_accountability
from products.pulse.backend.generation.goal import GoalStatus, collect_goal_status
from products.pulse.backend.generation.persist import _fingerprint, persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut
from products.pulse.backend.generation.synthesize import synthesize_brief
from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief
from products.pulse.backend.sources.anchored_insights import InsightResultsCache
from products.pulse.backend.sources.base import SourceItem, SourceItemKind
from products.pulse.backend.sources.registry import get_sources
from products.pulse.backend.temporal.inputs import (
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    SynthesizeActivityInputs,
)
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

# Fallback lookback for a since_last_run brief with no prior run, and the default day count.
_DEFAULT_LOOKBACK_DAYS = 7

# Priority-aware truncation before the MAX_ITEMS payload cap: a chatty low-priority source can't
# crowd out actionable items. The assert fails loudly at import if a new SourceItemKind lacks a
# priority (same import-time enum-coverage guard the KIND_DESCRIPTIONS assert uses) — it would
# otherwise silently sort last.
KIND_PRIORITY: dict[str, int] = {
    SourceItemKind.HEALTH: 0,
    SourceItemKind.SIGNAL: 1,
    SourceItemKind.MOVEMENT: 2,
    SourceItemKind.CONTEXT: 3,
}
assert set(KIND_PRIORITY) == set(SourceItemKind)


@dataclasses.dataclass
class ResolvedPeriod:
    start_date: dt.date
    end_date: dt.date
    lookback_days: int


class BriefGenerationFailed(Exception):
    """Carries workflow failures into error tracking; the full stack lives in Temporal."""


def resolve_period(spec: dict, now: dt.datetime, last_run: dt.datetime | None) -> ResolvedPeriod:
    """Resolve a period spec to explicit start/end dates and a lookback window.

    since_last_run measures the window from the last READY brief (min 1 day), else the default.
    """
    end_date = now.date()
    period_type = spec.get("type", "last_n_days")
    if period_type == "since_last_run":
        if last_run is not None:
            lookback_days = max(1, (end_date - last_run.date()).days)
        else:
            lookback_days = _DEFAULT_LOOKBACK_DAYS
    else:
        lookback_days = int(spec.get("days", _DEFAULT_LOOKBACK_DAYS))
    return ResolvedPeriod(
        start_date=end_date - dt.timedelta(days=lookback_days),
        end_date=end_date,
        lookback_days=lookback_days,
    )


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _get_config(team: Team, brief_config_id: str | None) -> BriefConfig | None:
    if not brief_config_id:
        return None
    return BriefConfig.objects.for_team(team.pk).filter(id=brief_config_id).first()


def _last_ready_run(team_id: int, brief_config_id: str | None) -> dt.datetime | None:
    # Most recent READY brief for this config (or the zero-config default when no config).
    return (
        ProductBrief.objects.for_team(team_id)
        .filter(config_id=brief_config_id, status=ProductBrief.Status.READY)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def _get_brief(team_id: int, brief_id: str) -> ProductBrief:
    return (
        ProductBrief.objects.for_team(team_id)
        .select_related("team__organization", "created_by", "config")
        .get(id=brief_id)
    )


def _mark_brief_failed(team_id: int, brief_id: str, error: str) -> None:
    ProductBrief.objects.for_team(team_id).filter(id=brief_id).update(status=ProductBrief.Status.FAILED, error=error)


async def _gather_source_items(team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]:
    """Run every source, isolate per-source failures, priority-sort, and apply the MAX_ITEMS cap.
    Shared by the synthesize-engine gather and the agent-engine mission prep."""
    sources = get_sources()
    items: list[SourceItem] = []
    failed_sources = 0
    for source in sources:
        try:
            gathered = await database_sync_to_async(source.gather, thread_sensitive=False)(team, config, lookback_days)
        except Exception as exc:
            # One broken source must not kill the brief; the other sources still contribute. Capture
            # to error tracking too, matching the per-item isolation in the movement scoring strategy.
            logger.exception("pulse_source_gather_failed", team_id=team.id, source=source.name)
            capture_exception(exc, {"team_id": team.id, "source": source.name, "product": "pulse"})
            failed_sources += 1
            continue
        items.extend(gathered)
    if sources and failed_sources == len(sources):
        # Every source broke: that's a failure to retry. Partial failure in a quiet week is not.
        raise ApplicationError(f"brief gather failed: all {failed_sources} source(s) failed")
    # Stable sort by kind priority so the highest-priority kinds survive the MAX_ITEMS payload cap.
    items.sort(key=lambda item: KIND_PRIORITY.get(item.kind, len(KIND_PRIORITY)))
    if len(items) > MAX_ITEMS:
        # Priority-based dropping is load-bearing — record it so a "missing item" report is diagnosable.
        logger.info(
            "pulse_gather_items_capped",
            team_id=team.id,
            total=len(items),
            kept=MAX_ITEMS,
            dropped=len(items) - MAX_ITEMS,
        )
    return items[:MAX_ITEMS]


@temporalio.activity.defn
async def gather_brief_inputs_activity(inputs: GenerateBriefWorkflowInputs) -> list[dict]:
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(inputs.team_id)
    if not team.organization.is_ai_data_processing_approved:
        raise ApplicationError("AI data processing not approved for this organization", non_retryable=True)
    config = await database_sync_to_async(_get_config, thread_sensitive=False)(team, inputs.brief_config_id)
    last_run = await database_sync_to_async(_last_ready_run, thread_sensitive=False)(
        inputs.team_id, inputs.brief_config_id
    )
    resolved = resolve_period(inputs.period, dt.datetime.now(dt.UTC), last_run)
    items = await _gather_source_items(team, config, resolved.lookback_days)
    return [dataclasses.asdict(item) for item in items]


@temporalio.activity.defn
async def prepare_mission_activity(inputs: GenerateBriefWorkflowInputs) -> dict:
    """Deterministic, secret-free half of the agent engine: scan sources for seeds, pin the frozen
    observation window on the brief row, and return the mission bundle. An empty seed_items list
    signals the quiet-week cheap path (skip the agent)."""
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(inputs.team_id)
    if not team.organization.is_ai_data_processing_approved:
        raise ApplicationError("AI data processing not approved for this organization", non_retryable=True)
    config = await database_sync_to_async(_get_config, thread_sensitive=False)(team, inputs.brief_config_id)
    brief = await database_sync_to_async(_get_brief, thread_sensitive=False)(inputs.team_id, inputs.brief_id)
    last_run = await database_sync_to_async(_last_ready_run, thread_sensitive=False)(
        inputs.team_id, inputs.brief_config_id
    )
    now = dt.datetime.now(dt.UTC)
    resolved = resolve_period(inputs.period, now, last_run)
    window_start = now - dt.timedelta(days=resolved.lookback_days)
    items = await _gather_source_items(team, config, resolved.lookback_days)
    bundle = build_general_brief_mission(
        team=team,
        brief=brief,
        config=config,
        items=items,
        window_start=window_start,
        window_end=now,
        lookback_days=resolved.lookback_days,
    )

    def _pin_window() -> None:
        ProductBrief.objects.for_team(inputs.team_id).filter(id=inputs.brief_id).update(
            window_start=bundle.window_start, window_end=bundle.window_end
        )

    await database_sync_to_async(_pin_window, thread_sensitive=False)()
    # No secrets in the bundle: the OAuth token is minted inside run_agent so it never lands in
    # persisted workflow history.
    return bundle.model_dump(mode="json")


@temporalio.activity.defn
async def synthesize_brief_activity(inputs: SynthesizeActivityInputs) -> str:
    brief = await database_sync_to_async(_get_brief, thread_sensitive=False)(inputs.team_id, inputs.brief_id)
    if brief.created_by is None:
        raise ApplicationError("brief has no creating user for LLM attribution", non_retryable=True)
    last_run = await database_sync_to_async(_last_ready_run, thread_sensitive=False)(
        inputs.team_id, str(brief.config_id) if brief.config_id else None
    )
    resolved = resolve_period(brief.period, dt.datetime.now(dt.UTC), last_run)
    items = [SourceItem(**item) for item in inputs.items]
    status_lines: list[OpportunityStatusLine] = []
    goal_status: GoalStatus | None = None
    # One insight-results cache shared across the goal and accountability reads so an insight
    # referenced by both executes once (and both share the per-insight wall-clock cap).
    results_cache = InsightResultsCache(brief.team)
    # Accountability is not movement-gated — past suggestions matter every period. Only an empty
    # gather skips it, since synthesize short-circuits without items anyway. Best-effort: a broken
    # re-score degrades to no accountability section, never a failed brief.
    if items:
        try:
            min_age_days = brief.config.accountability_min_age_days if brief.config else MIN_AGE_DAYS
            status_lines = await database_sync_to_async(collect_accountability, thread_sensitive=False)(
                brief.team, min_age_days, results_cache=results_cache
            )
        except Exception:
            logger.exception("pulse_accountability_failed", team_id=brief.team_id, brief_id=str(brief.id))
        # Goal status frames the brief around the config's goal. Best-effort like accountability:
        # a broken read degrades to a figure-less goal block, never a failed brief. Config-less
        # briefs carry no goal. The resolved lookback is the goal window, matching the gather.
        if brief.config is not None:
            try:
                goal_status = await database_sync_to_async(collect_goal_status, thread_sensitive=False)(
                    brief.team, brief.config, resolved.lookback_days, results_cache
                )
            except Exception:
                logger.exception("pulse_goal_status_failed", team_id=brief.team_id, brief_id=str(brief.id))
    out = await synthesize_brief(
        team=brief.team,
        user=brief.created_by,
        config=brief.config,
        items=items,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        lookback_days=resolved.lookback_days,
        # Past suggestions the team engaged with — steers relevance, same list we persist for the panel.
        status_lines=status_lines,
        goal_status=goal_status,
    )
    await database_sync_to_async(persist_brief_output, thread_sensitive=False)(
        brief=brief,
        out=out,
        items=items,
        status_lines=status_lines,
        goal_status=goal_status,
        period_days=resolved.lookback_days,
        results_cache=results_cache,
    )
    created = await database_sync_to_async(_created_opportunities, thread_sensitive=False)(brief)
    await _emit_opportunity_signals(brief, out, created)
    try:
        # ph_scoped_capture, not posthoganalytics.capture: events fire outside request context.
        await database_sync_to_async(_report_brief_generated, thread_sensitive=False)(brief, len(created))
    except Exception:
        logger.exception("pulse_brief_generated_capture_failed", team_id=brief.team_id, brief_id=str(brief.id))
    return brief.status


def _created_opportunities(brief: ProductBrief) -> list[Opportunity]:
    # persist skips existing fingerprints, so the opportunities first surfaced by THIS brief are
    # exactly the ones it created this run — the list persist no longer returns directly.
    return list(Opportunity.objects.for_team(brief.team_id).filter(first_seen_brief=brief))


def _report_brief_generated(brief: ProductBrief, new_opportunity_count: int) -> None:
    if brief.created_by is None:
        return
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=brief.created_by.distinct_id,
            event="product_brief_generated",
            properties={
                "brief_id": str(brief.id),
                "status": brief.status,
                "trigger": brief.trigger,
                "period": brief.period,
                "has_config": brief.config_id is not None,
                "new_opportunity_count": new_opportunity_count,
            },
        )


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
        confidence_by_fingerprint.setdefault(_fingerprint(opp.kind, opp.fingerprint_hint), opp.confidence)
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
            extra={"brief_id": str(brief.id)},
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
