import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.prompts import SYNTHESIZE_PROMPT
from products.pulse.backend.generation.schemas import KIND_DESCRIPTIONS, BriefOut
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem, format_evidence_ref

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
        refs = ", ".join(format_evidence_ref(e) for e in item.evidence)
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
    focus_prompt = (config.focus_prompt if config else "") or "the whole product"
    rendered = SYNTHESIZE_PROMPT.format(
        # The focus text is fenced in a <team_focus> block; strip the closing tag so
        # user configuration can't break out of it.
        focus_prompt=focus_prompt.replace("</team_focus>", ""),
        period_days=period_days,
        max_opportunities=MAX_OPPORTUNITIES,
        kind_descriptions=", ".join(f'"{kind}" = {description}' for kind, description in KIND_DESCRIPTIONS.items()),
        items_block=_render_items(items),
    )
    llm = MaxChatOpenAI(
        model=SYNTHESIS_MODEL,
        timeout=_LLM_TIMEOUT_SECONDS,
        # Worst case 2 attempts x 120s stays under the 5-minute synthesize activity timeout.
        max_retries=1,
        user=user,
        team=team,
        billable=True,
        posthog_properties={"ai_product": "pulse", "ai_feature": "brief_synthesis"},
    ).with_structured_output(BriefOut, method="json_schema", include_raw=False)
    # database_sync_to_async (not to_thread): MaxChatOpenAI reads billing/quota from the ORM
    result = await database_sync_to_async(llm.invoke, thread_sensitive=False)([("system", rendered)])
    if not isinstance(result, BriefOut):
        # Raise so the workflow marks the brief FAILED — a malformed output is not a quiet week.
        logger.error("pulse_synthesize_unexpected_output", team_id=team.id, output_type=type(result).__name__)
        raise ValueError(f"LLM returned unexpected structured output type: {type(result).__name__}")
    return apply_say_less_gate(result)
