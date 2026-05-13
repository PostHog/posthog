"""Single-turn sandbox research that finds PostHog enthusiasts on Twitter/X for referral outreach."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession
from products.twitter_referrals.backend.research.prompts import TwitterReferralCandidates, build_twitter_research_prompt

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)


async def run_twitter_research(
    context: CustomPromptSandboxContext,
    *,
    api_key: str,
    since_unix_ts: int,
    hours: int = 1,
    branch: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> TwitterReferralCandidates:
    """Run a one-turn sandbox session that fetches recent PostHog tweets and filters for referral candidates.

    The agent runs the curl command embedded in the prompt, reads the response, applies the
    enthusiasm criteria, and returns a `TwitterReferralCandidates` payload. The API key is
    inlined into the prompt at call time; the sandbox itself does not need env-var plumbing.
    """
    if output_fn:
        output_fn(f"Starting twitter referral research (since_unix_ts={since_unix_ts}, hours={hours})")

    prompt = build_twitter_research_prompt(
        since_unix_ts=since_unix_ts,
        api_key=api_key,
        hours=hours,
    )

    session, result = await MultiTurnSession.start(
        prompt=prompt,
        context=context,
        model=TwitterReferralCandidates,
        branch=branch,
        step_name="twitter_referral_research",
        verbose=verbose,
        output_fn=output_fn,
        internal=True,
    )

    await session.end()

    if output_fn:
        output_fn(f"Twitter research done: {len(result.candidates)} candidate(s)")

    logger.info("twitter_referral_research: completed with %d candidates", len(result.candidates))
    return result
