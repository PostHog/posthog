"""Single-turn sandbox research that finds PostHog power users worth a referral DM."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from products.referrals.backend.internal.research.prompts import (
    InternalReferralCandidates,
    build_internal_research_prompt,
)
from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)


async def run_internal_research(
    context: CustomPromptSandboxContext,
    *,
    branch: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> InternalReferralCandidates:
    """Run a one-turn sandbox session that queries PostHog behavioural data for referral targets.

    The agent runs the validated HogQL queries (signal aggregation + person/org lookups) via the
    PostHog MCP `execute-sql` tool, applies its own judgement when picking candidates, and returns
    an `InternalReferralCandidates` payload. The caller must ensure `context.posthog_mcp_scopes`
    is set so the sandbox can access the `execute-sql` tool.
    """
    if context.posthog_mcp_scopes is None:
        raise ValueError(
            "context.posthog_mcp_scopes must be set (e.g. 'read_only') so the sandbox can use the execute-sql tool."
        )

    if output_fn:
        output_fn("Starting internal referral research")

    prompt = build_internal_research_prompt()

    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=InternalReferralCandidates,
        branch=branch,
        step_name="internal_referral_research",
        verbose=verbose,
        output_fn=output_fn,
        internal=True,
    )

    await session.end()

    if output_fn:
        output_fn(f"Internal research done: {len(result.candidates)} candidate(s)")

    logger.info("internal_referral_research: completed with %d candidates", len(result.candidates))
    return result
