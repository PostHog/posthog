"""The typed-runner suites for an MCP client without PostHog skills.

Many customers connect the PostHog MCP server but do not install the plugin that ships the
PostHog skills. Their agent sees only the MCP tools, the tool descriptions, the server
instructions and guidance notices. These suites run the cases of ``eval_typed_runner_misses``
in that setup:

- Each case clears the native skill directories in the sandbox.
- Bundled delivery keeps the MCP skill catalog off, so ``learn`` serves no skills.
- The ``eval`` interaction origin makes the MCP server treat the agent as an outside client,
  so guidance rules can reach it. Without an origin, bundled runs identify as PostHog AI,
  which guidance skips.

Run them in bundled delivery, which is the default. Exec delivery serves skills through
``learn``, so the suites refuse to run in it:

    hogli evals eval_typed_runner_no_skills --agent-runtime claude --agent-model claude-opus-5-5 --trials 3
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.offline_config import offline_suite
from products.tasks.backend.facade.agents import EVAL_INTERACTION_ORIGIN

from .eval_typed_runner_misses import (
    JUSTIFIED_SQL_CONTROL_METRICS,
    TYPED_RUNNER_MISS_METRICS,
    justified_sql_control_cases,
    justified_sql_control_scorers,
    typed_runner_miss_cases,
    typed_runner_miss_scorers,
)


def _without_skills(ctx: EvalContext, cases: list[SandboxedEvalCase]) -> list[SandboxedEvalCase]:
    if ctx.skill_delivery == "exec":
        raise ValueError(
            "The no-skills suites measure an agent without PostHog skills, but exec delivery serves "
            "skills through `learn`. Run them with --skill-delivery bundled."
        )
    return [
        case.model_copy(update={"disable_bundled_skills": True, "interaction_origin": EVAL_INTERACTION_ORIGIN})
        for case in cases
    ]


async def eval_typed_runner_misses_no_skills(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-typed-runner-misses-no-skills-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_typed_runner_no_skills::eval_typed_runner_misses_no_skills",
            metrics=TYPED_RUNNER_MISS_METRICS,
        ),
        cases=_without_skills(ctx, typed_runner_miss_cases()),
        scorers=typed_runner_miss_scorers(),
        ctx=ctx,
    )


async def eval_justified_sql_controls_no_skills(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-justified-sql-controls-no-skills-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_typed_runner_no_skills::eval_justified_sql_controls_no_skills",
            metrics=JUSTIFIED_SQL_CONTROL_METRICS,
        ),
        cases=_without_skills(ctx, justified_sql_control_cases()),
        scorers=justified_sql_control_scorers(),
        ctx=ctx,
    )
