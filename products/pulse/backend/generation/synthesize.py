import structlog

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.accountability import OpportunityStatusLine
from products.pulse.backend.generation.gate import apply_say_less_gate, gate_thresholds
from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.prompts import (
    ACCOUNTABILITY_BLOCK,
    SYNTHESIZE_PROMPT,
    render_goal_block,
    sanitize_for_prompt,
)
from products.pulse.backend.generation.schemas import KIND_DESCRIPTIONS, BriefOut
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem, format_evidence_ref

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)

SYNTHESIS_MODEL = "gpt-4.1"
_LLM_TIMEOUT_SECONDS = 120


def _render_items(items: list[SourceItem]) -> str:
    # Titles and descriptions carry untrusted free text (annotation content, resource names) —
    # sanitize at this boundary, for every source. Evidence labels are not rendered (only
    # type:ref); if they ever are, they must pass through sanitize_for_prompt too. numbers keys
    # and values are rendered raw: every source puts only system-generated data there (timestamps,
    # counts); a source that ever stores user-supplied text must sanitize it before this point.
    blocks = []
    for item in items:
        numbers = ", ".join(f"{k}={v}" for k, v in item.numbers.items())
        refs = ", ".join(sanitize_for_prompt(format_evidence_ref(e)) for e in item.evidence)
        blocks.append(
            f"- [{item.source}/{item.kind}] {sanitize_for_prompt(item.title)}\n"
            f"  numbers: {numbers}\n  evidence_refs: {refs}\n  fingerprint_hint: {item.fingerprint_hint}\n"
            f"  {sanitize_for_prompt(item.description)}"
        )
    return "\n".join(blocks)


def _render_accountability_block(status_lines: list[OpportunityStatusLine]) -> str:
    # Titles carry untrusted free text (LLM-authored on an earlier run) — same render-boundary
    # sanitization as items. Summaries and deltas are code-generated and stated verbatim; the
    # opportunity ref is the citation the frontend links by.
    if not status_lines:
        return ""
    rendered_lines = "\n".join(
        f"- [{line.kind}/{line.status}] {sanitize_for_prompt(line.title)} — suggested {line.age_days} days ago — "
        f"then {line.baseline_summary}, now {line.current_summary}"
        + (f" ({line.delta_pct:+.1f}% vs suggestion time)" if line.delta_pct is not None else "")
        + f" (evidence_ref: opportunity:{line.opportunity_id})"
        for line in status_lines
    )
    return ACCOUNTABILITY_BLOCK.format(status_lines_block=rendered_lines)


async def synthesize_brief(
    *,
    team: Team,
    user: User,
    config: BriefConfig | None,
    items: list[SourceItem],
    period_days: int,
    status_lines: list[OpportunityStatusLine],
    goal_status: GoalStatus | None,
) -> BriefOut:
    # Quiet periods must cost ~nothing: no items, no LLM call. Status lines alone are not a
    # brief — they follow up on movements, so they can't rescue an empty period.
    if not items:
        return BriefOut(sections=[], opportunities=[])
    confidence_threshold, max_opportunities = gate_thresholds(config)
    rendered = SYNTHESIZE_PROMPT.format(
        # The focus prompt is user-authored free text — same render-boundary sanitization as items.
        # Sanitization neutralizes angle brackets, so the <team_focus> fence cannot be broken out of.
        focus_prompt=sanitize_for_prompt((config.focus_prompt if config else "") or "the whole product"),
        period_days=period_days,
        max_opportunities=max_opportunities,
        kind_descriptions=", ".join(f'"{kind}" = {description}' for kind, description in KIND_DESCRIPTIONS.items()),
        goal_block=render_goal_block(goal_status, period_days),
        accountability_block=_render_accountability_block(status_lines),
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
    if goal_status is None and any(o.goal_relevant for o in result.opportunities):
        # No goal was in the prompt, so a set flag is model non-compliance — it must not reorder.
        result = BriefOut(
            sections=result.sections,
            opportunities=[o.model_copy(update={"goal_relevant": False}) for o in result.opportunities],
        )
    return apply_say_less_gate(result, confidence_threshold=confidence_threshold, max_opportunities=max_opportunities)
