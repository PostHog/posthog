from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import ExitCodeZero
from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    ExpectedSkillDiscovered,
    ExpectedSkillLoaded,
    NoBundledSkillBypass,
    NoExecSkillBypass,
    SkillLoadedBeforeTool,
    SkillSearchFirst,
    skill_distribution_expectations,
)


def _case(
    name: str,
    prompt: str,
    skill: str,
    downstream_tools: list[str],
    skill_delivery: SkillDelivery,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected=skill_distribution_expectations(skill, downstream_tools, skill_delivery),
        metadata={"expected_skill": skill, "skill_delivery": skill_delivery},
    )


async def eval_skill_distribution(ctx: EvalContext) -> None:
    cases = [
        _case(
            name="paid_bill_revenue_by_account_plan",
            prompt=(
                "Which account plans generated the most paid-bill revenue over the last 90 days? "
                "Return each plan, its total revenue, and the number of unique accounts that paid."
            ),
            skill="querying-posthog-data",
            downstream_tools=["execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="outbound_autocapture_hrefs",
            prompt=(
                "Using our autocapture data from the last 120 days, list the outbound link hrefs people clicked "
                "and the click count for each href."
            ),
            skill="exploring-autocapture-events",
            downstream_tools=["execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="historical_traffic_share_by_type",
            prompt=(
                "For the last 30 days, what share of pageviews came from each human or bot traffic type? "
                "This is a historical analysis, not the Live tab."
            ),
            skill="filtering-bot-traffic",
            downstream_tools=["query-trends", "execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="weekly_file_volume_drop",
            prompt=(
                "Investigate why the existing 'Weekly file volume' metric fell in the most recent full week "
                "compared with the previous full week. Use project data to identify the likely drivers."
            ),
            skill="investigate-metric",
            downstream_tools=["insight-query", "query-trends", "execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="uneven_split_bias_warning",
            prompt=(
                "Diagnose the bias warning on the 'bias-warning-demo-uneven-split' experiment. "
                "Explain what in this experiment is causing the warning and what should be checked next."
            ),
            skill="diagnosing-experiment-results",
            downstream_tools=["experiment-get", "experiment-stats", "execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="seven_day_live_top_pages_equivalent",
            prompt=(
                "The Web analytics Live tab shows top pages for the current window. "
                "Build and run the equivalent top-pages analysis for the last seven days."
            ),
            skill="exploring-live-traffic",
            downstream_tools=["query-trends"],
            skill_delivery=ctx.skill_delivery,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-skill-distribution-cli",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            SkillSearchFirst(),
            ExpectedSkillDiscovered(),
            ExpectedSkillLoaded(),
            SkillLoadedBeforeTool(),
            NoBundledSkillBypass(),
            NoExecSkillBypass(),
        ],
        ctx=ctx,
    )
