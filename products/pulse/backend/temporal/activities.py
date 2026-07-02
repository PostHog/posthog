import dataclasses

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

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

MAX_ITEMS = 50


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
    items: list[SourceItem] = []
    for source in get_sources():
        try:
            gathered = await database_sync_to_async(source.gather, thread_sensitive=False)(
                team, config, inputs.period_days
            )
        except Exception:
            # One broken source must not kill the brief; the other sources still contribute.
            logger.exception("pulse_source_gather_failed", team_id=team.id, source=source.name)
            continue
        items.extend(gathered)
    # Keep the activity payload small — well under Temporal's ~2 MiB cap.
    return [dataclasses.asdict(item) for item in items[:MAX_ITEMS]]


@temporalio.activity.defn
async def synthesize_brief_activity(inputs: SynthesizeActivityInputs) -> str:
    brief = await database_sync_to_async(_get_brief, thread_sensitive=False)(inputs.team_id, inputs.brief_id)
    if brief.created_by is None:
        raise ApplicationError("brief has no creating user for LLM attribution", non_retryable=True)
    items = [SourceItem(**item) for item in inputs.items]
    out = await synthesize_brief(
        team=brief.team,
        user=brief.created_by,
        config=brief.config,
        items=items,
        period_days=brief.period_days,
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
