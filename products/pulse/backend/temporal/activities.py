import datetime as dt
import dataclasses

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.config import MAX_ITEMS
from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.synthesize import synthesize_brief
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.registry import get_sources
from products.pulse.backend.temporal.inputs import (
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    SynthesizeActivityInputs,
)

logger = structlog.get_logger(__name__)

# Fallback lookback for a since_last_run brief with no prior run, and the default day count.
_DEFAULT_LOOKBACK_DAYS = 7


@dataclasses.dataclass
class ResolvedPeriod:
    start_date: dt.date
    end_date: dt.date
    lookback_days: int


class BriefGenerationFailed(Exception):
    """Carries workflow failures into error tracking; the full stack lives in Temporal."""


def resolve_period(spec: dict, now: dt.datetime, last_run: dt.datetime | None) -> ResolvedPeriod:
    """Resolve a period spec to explicit dates + a lookback window.

    Wall-clock reads are fine here (activities, not the deterministic workflow). end_date is
    today; start_date is `lookback_days` before. For since_last_run the window is the days since
    the last READY brief (min 1), falling back to the default when there is no prior run.
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
    items: list[SourceItem] = []
    for source in get_sources():
        gathered = await database_sync_to_async(source.gather, thread_sensitive=False)(
            team, config, resolved.lookback_days
        )
        items.extend(gathered)
    # Keep the activity payload small — well under Temporal's ~2 MiB cap.
    return [dataclasses.asdict(item) for item in items[:MAX_ITEMS]]


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
    out = await synthesize_brief(
        team=brief.team,
        user=brief.created_by,
        config=brief.config,
        items=items,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        lookback_days=resolved.lookback_days,
    )
    brief = await database_sync_to_async(persist_brief_output, thread_sensitive=False)(
        brief=brief, out=out, items=items
    )
    return brief.status


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
