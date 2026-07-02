import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.prompts import SYNTHESIZE_PROMPT
from products.pulse.backend.generation.schemas import KIND_DESCRIPTIONS, BriefOut
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.6
MAX_OPPORTUNITIES = 3
SYNTHESIS_MODEL = "gpt-4.1"
_LLM_TIMEOUT_SECONDS = 120


def apply_say_less_gate(out: BriefOut) -> BriefOut:
    confident_opportunities = [o for o in out.opportunities if o.confidence >= CONFIDENCE_THRESHOLD]
    return BriefOut(
        sections=[s for s in out.sections if s.confidence >= CONFIDENCE_THRESHOLD],
        # Deterministic cap: the prompt asks for at most MAX_OPPORTUNITIES, but the model may not comply.
        opportunities=sorted(confident_opportunities, key=lambda o: o.confidence, reverse=True)[:MAX_OPPORTUNITIES],
    )


def _render_items(items: list[SourceItem]) -> str:
    blocks = []
    for item in items:
        numbers = ", ".join(f"{k}={v}" for k, v in item.numbers.items())
        refs = ", ".join(f"{e['type']}:{e['ref']}" for e in item.evidence)
        blocks.append(
            f"- [{item.source}/{item.kind}] {item.title}\n"
            f"  numbers: {numbers}\n  evidence_refs: {refs}\n  fingerprint_hint: {item.fingerprint_hint}\n"
            f"  {item.description}"
        )
    return "\n".join(blocks)


async def synthesize_brief(
    *, team: Team, user: User, config: BriefConfig | None, items: list[SourceItem], period_days: int
) -> BriefOut:
    # Quiet periods must cost ~nothing: no items, no LLM call.
    if not items:
        return BriefOut(sections=[], opportunities=[])
    rendered = SYNTHESIZE_PROMPT.format(
        focus_prompt=(config.focus_prompt if config else "") or "the whole product",
        period_days=period_days,
        max_opportunities=MAX_OPPORTUNITIES,
        kind_descriptions=", ".join(f'"{kind}" = {description}' for kind, description in KIND_DESCRIPTIONS.items()),
        items_block=_render_items(items),
    )
    llm = MaxChatOpenAI(
        model=SYNTHESIS_MODEL,
        timeout=_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        billable=True,
        posthog_properties={"ai_product": "pulse", "ai_feature": "brief_synthesis"},
    ).with_structured_output(BriefOut, method="json_schema", include_raw=False)
    # database_sync_to_async (not to_thread): MaxChatOpenAI reads billing/quota from the ORM
    result = await database_sync_to_async(llm.invoke, thread_sensitive=False)([("system", rendered)])
    if not isinstance(result, BriefOut):
        logger.error("pulse_synthesize_unexpected_output", team_id=team.id, output_type=type(result).__name__)
        return BriefOut(sections=[], opportunities=[])
    return apply_say_less_gate(result)
