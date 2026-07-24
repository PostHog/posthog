from __future__ import annotations

from collections.abc import Callable
from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    ExpectedSkillDiscovered,
    ExpectedSkillLoaded,
    NoBundledSkillBypass,
    NoExecSkillBypass,
    SkillLoadedBeforeTool,
    SkillSearchFirst,
)
from products.posthog_ai.evals.cli_mcp.skill_usage_scorers import (
    ExpectedReferencePulled,
    SearchRecoveryAfterZeroHit,
    SkillAnswerCorrectness,
    skill_usage_expectations,
)
from products.posthog_ai.evals.cli_mcp.skill_usage_seeder import (
    PROJECT_SKILL_EXPECTED_ANSWER,
    PROJECT_SKILL_NAME,
    PROJECT_SKILL_REFERENCE_PATH,
    seed_project_skill,
)


def _case(
    name: str,
    prompt: str,
    skill: str,
    downstream_tools: list[str],
    skill_delivery: SkillDelivery,
    *,
    source: str = "posthog",
    reference_paths: list[str] | None = None,
    expected_answer: str | None = None,
    setup: Callable[[Any], dict[str, Any]] | None = None,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected=skill_usage_expectations(
            skill,
            downstream_tools,
            skill_delivery,
            source=source,
            reference_paths=reference_paths,
            expected_answer=expected_answer,
        ),
        metadata={"expected_skill": skill, "skill_delivery": skill_delivery},
        setup=setup,
    )


async def eval_skill_usage(ctx: EvalContext) -> None:
    cases = [
        _case(
            name="bias_threshold_reference_pull",
            prompt=(
                "The 'bias-warning-demo-uneven-split' experiment is showing a bias warning. "
                "At exactly what multi-variant ($multiple) exposure share does that warning fire, "
                "and at what share does the Exposures tab show a $multiple row? "
                "Compute this experiment's actual $multiple exposure share from its data and state "
                "whether the row is visible for it."
            ),
            skill="diagnosing-experiment-results",
            downstream_tools=["experiment-get", "experiment-stats", "execute-sql"],
            skill_delivery=ctx.skill_delivery,
            reference_paths=["references/bias-and-skew.md"],
            expected_answer=(
                "The bias warning fires when the $multiple exposure share is above 0.1%. "
                "The Exposures tab hides the $multiple row when its share is at or below 0.5%. "
                "This experiment's actual $multiple exposure share is above 0.5%, "
                "so the $multiple row is visible for it."
            ),
        ),
        _case(
            name="error_volume_schema_reference_pull",
            prompt=(
                "Which error tracking issue had the most exceptions over the last 30 days? "
                "Return the issue's exact title and its issue id."
            ),
            skill="querying-posthog-data",
            downstream_tools=["execute-sql"],
            skill_delivery=ctx.skill_delivery,
            reference_paths=["references/models-error-tracking.md", "references/example-error-tracking.md"],
            expected_answer=(
                "The answer names exactly one error tracking issue as the highest-volume one — one of "
                '"Checkout API timeout", "File preview render failure", or "Team invite rejected" — '
                "and includes that issue's UUID issue id."
            ),
        ),
        _case(
            name="automated_visitor_share_paraphrase",
            prompt=(
                "Our pageview numbers for the last 30 days look inflated by non-human visitors. "
                "Work out what share of pageviews came from scrapers and AI agents crawling the site, "
                "and report a cleaned pageview figure that counts people only."
            ),
            skill="filtering-bot-traffic",
            downstream_tools=["query-trends", "execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
    ]

    if ctx.skill_delivery == "exec":
        cases.append(
            _case(
                name="project_enterprise_revenue_policy",
                prompt=(
                    "Finance asked for our qualified enterprise revenue over the last 90 days. "
                    "Compute it, apply the standard definition our team has documented for this, "
                    "and quote the exact rules you applied, including any exclusions."
                ),
                skill=PROJECT_SKILL_NAME,
                downstream_tools=["execute-sql"],
                skill_delivery=ctx.skill_delivery,
                source="project",
                reference_paths=[PROJECT_SKILL_REFERENCE_PATH],
                expected_answer=PROJECT_SKILL_EXPECTED_ANSWER,
                setup=seed_project_skill,
            )
        )

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-skill-usage-cli",
        cases=cases,
        scorers=[
            SkillSearchFirst(),
            ExpectedSkillDiscovered(),
            ExpectedSkillLoaded(),
            SkillLoadedBeforeTool(),
            NoBundledSkillBypass(),
            NoExecSkillBypass(),
            ExpectedReferencePulled(),
            SearchRecoveryAfterZeroHit(),
            SkillAnswerCorrectness(),
        ],
        ctx=ctx,
    )
