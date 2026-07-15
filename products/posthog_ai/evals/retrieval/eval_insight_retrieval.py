"""Insight-retrieval eval cases for the sandboxed product-analytics agent.

Each case seeds 1000 noise insights plus a few distinctive lookup insights
into the per-case team via ``setup=seed_insight_noise``, then asks the
agent to find one specific insight and return its ID.

Two metrics:

* ``skill_loaded`` — did the agent load ``querying-posthog-data`` before
  reasoning about how to find the entity? Buying noise without skill
  guidance pushes the agent toward the wrong tool.
* ``lookup_id_in_output`` — does the agent's final message include the
  seeded insight's ID? Proves it actually queried PostHog rather than
  hallucinating a plausible-looking ID.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_insight_retrieval"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.seeders.insight import seed_insight_noise
from products.posthog_ai.evals.retrieval.scorers import LookupIdInOutput, SkillLoaded

SKILL_NAME = "querying-posthog-data"


async def eval_insight_retrieval(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="retrieval_insight_northern_lights",
            prompt=(
                "Find the saved insight named '[lookup] Northern Lights Funnel' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="retrieval_insight_aurora",
            prompt=(
                "Find the saved insight named '[lookup] Aurora Retention Cohort' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="retrieval_insight_solstice",
            prompt=(
                "Find the saved insight named '[lookup] Solstice Pageview Trend' "
                "in this PostHog project and return its numeric ID. Reply with just the ID."
            ),
            setup=seed_insight_noise,
        ),
        # Real-world fuzzy retrieval: user describes the insight in natural
        # language ("MAUs using the app") instead of naming it verbatim. From a
        # team-product-analytics report on a session that took ~50 tool calls
        # and ~15 minutes to return the wrong answer.
        SandboxedEvalCase(
            name="retrieval_insight_fuzzy_mau",
            prompt=(
                "find me a graph of MAUs using the app. "
                "it's probably an existing insight, and created/last used by "
                "me around this time last year."
            ),
            expected={"lookup_id_in_output": {"lookup_name": "Monthly Active Users (Hedgebox)"}},
            setup=seed_insight_noise,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-retrieval-cli",
        cases=cases,
        scorers=[
            SkillLoaded(skill_name=SKILL_NAME),
            LookupIdInOutput(),
        ],
        ctx=ctx,
    )
