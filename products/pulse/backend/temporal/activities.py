import dataclasses

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.persist import persist_brief_output
from products.pulse.backend.generation.synthesize import synthesize_brief
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.base import BriefSource, SourceItem
from products.pulse.backend.sources.registry import get_sources

logger = structlog.get_logger(__name__)

MAX_ITEMS = 50


@dataclasses.dataclass
class GenerateBriefWorkflowInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None = None
    period_days: int = 7


@dataclasses.dataclass
class SynthesizeActivityInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None
    period_days: int
    items: list[dict]


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


def _gather_from_source(
    source: BriefSource, team: Team, config: BriefConfig | None, period_days: int
) -> list[SourceItem]:
    return source.gather(team, config, period_days)


def _mark_brief_failed(brief: ProductBrief, error: str) -> None:
    brief.status = ProductBrief.Status.FAILED
    brief.error = error
    brief.save(update_fields=["status", "error", "updated_at"])


@temporalio.activity.defn
async def gather_brief_inputs_activity(inputs: GenerateBriefWorkflowInputs) -> list[dict]:
    team = await database_sync_to_async(_get_team, thread_sensitive=False)(inputs.team_id)
    if not team.organization.is_ai_data_processing_approved:
        raise ApplicationError("AI data processing not approved for this organization", non_retryable=True)
    config = await database_sync_to_async(_get_config, thread_sensitive=False)(team, inputs.brief_config_id)
    items: list[SourceItem] = []
    for source in get_sources():
        gathered = await database_sync_to_async(_gather_from_source, thread_sensitive=False)(
            source, team, config, inputs.period_days
        )
        items.extend(gathered)
    # Keep the activity payload small — well under Temporal's ~2 MiB cap.
    return [dataclasses.asdict(item) for item in items[:MAX_ITEMS]]


@temporalio.activity.defn
async def synthesize_brief_activity(inputs: SynthesizeActivityInputs) -> str:
    brief = await database_sync_to_async(_get_brief, thread_sensitive=False)(inputs.team_id, inputs.brief_id)
    try:
        if brief.created_by is None:
            raise ApplicationError("brief has no creating user for LLM attribution", non_retryable=True)
        items = [SourceItem(**item) for item in inputs.items]
        out = await synthesize_brief(
            team=brief.team,
            user=brief.created_by,
            config=brief.config,
            items=items,
            period_days=inputs.period_days,
        )
        await database_sync_to_async(persist_brief_output, thread_sensitive=False)(brief=brief, out=out)
        return brief.status
    except Exception as exc:
        logger.exception("pulse_synthesize_brief_failed", team_id=inputs.team_id, brief_id=inputs.brief_id)
        await database_sync_to_async(_mark_brief_failed, thread_sensitive=False)(brief, str(exc))
        raise
