import datetime as dt

import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.security.llm_prompt_sanitization import sanitize_user_text
from posthog.sync import database_sync_to_async

from products.pulse.backend.config import LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS, SYNTHESIS_MODEL, BriefSettings
from products.pulse.backend.generation.prompts import PULSE_SYNTHESIS_PROMPT_KEY, SYNTHESIZE_PROMPT, _get_managed_prompt
from products.pulse.backend.generation.schemas import KIND_DESCRIPTIONS, BriefOut
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem, build_evidence_index

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)


def apply_say_less_gate(out: BriefOut, settings: BriefSettings) -> BriefOut:
    confident_opportunities = [o for o in out.opportunities if o.confidence >= settings.confidence_threshold]
    return BriefOut(
        sections=[s for s in out.sections if s.confidence >= settings.confidence_threshold],
        # Deterministic cap: the prompt asks for at most max_opportunities, but the model may not comply.
        opportunities=sorted(confident_opportunities, key=lambda o: o.confidence, reverse=True)[
            : settings.max_opportunities
        ],
    )


def _render_items(items: list[SourceItem]) -> str:
    evidence_index = build_evidence_index(items)
    id_by_key = {(ev["type"], ev["ref"]): cid for cid, ev in evidence_index.items()}
    blocks = []
    for item in items:
        metrics = ", ".join(f"{k}={v}" for k, v in item.metrics.items())
        citation_ids = ", ".join(id_by_key[(e["type"], e["ref"])] for e in item.evidence)
        blocks.append(
            f"- [{item.source}/{item.kind}] {item.title}\n"
            f"  metrics: {metrics}\n  citation_ids: {citation_ids}\n  fingerprint_hint: {item.fingerprint_hint}\n"
            f"  {item.description}"
        )
    return "\n".join(blocks)


async def synthesize_brief(
    *,
    team: Team,
    user: User,
    config: BriefConfig | None,
    items: list[SourceItem],
    start_date: dt.date,
    end_date: dt.date,
    lookback_days: int,
) -> BriefOut:
    # Quiet periods must cost ~nothing: no items, no LLM call.
    if not items:
        return BriefOut(sections=[], opportunities=[])
    settings = BriefSettings.from_config(config)
    # The focus text is fenced in a <team_focus> block. sanitize_user_text strips invisible chars,
    # LLM framing tags (including the fence itself), and collapses newlines, so user configuration
    # can't forge the fence or inject instruction-shaped content; empty falls back to a neutral default.
    focus_prompt = sanitize_user_text(config.focus_prompt if config else "", max_len=2000) or "the whole product"
    template = await database_sync_to_async(_get_managed_prompt, thread_sensitive=False)(
        team, PULSE_SYNTHESIS_PROMPT_KEY, SYNTHESIZE_PROMPT
    )
    rendered = template.format(
        focus_prompt=focus_prompt,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        lookback_days=lookback_days,
        max_opportunities=settings.max_opportunities,
        kind_descriptions=", ".join(f'"{kind}" = {description}' for kind, description in KIND_DESCRIPTIONS.items()),
        items_block=_render_items(items),
    )
    llm = MaxChatOpenAI(
        model=SYNTHESIS_MODEL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
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
    return apply_say_less_gate(result, settings)
