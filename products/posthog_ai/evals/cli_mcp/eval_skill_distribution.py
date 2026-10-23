from __future__ import annotations

from collections.abc import Callable
from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    ExcludedSkillNotLoaded,
    ExpectedSkillDiscovered,
    ExpectedSkillLoaded,
    NoBundledSkillBypass,
    NoExecSkillBypass,
    SkillLoadedBeforeTool,
    SkillSearchFirst,
    skill_distribution_expectations,
)
from products.posthog_ai.evals.error_tracking.seeders import seed_error_tracking_issues
from products.posthog_ai.evals.offline_config import offline_suite
from products.tasks.backend.facade.agents import EVAL_INTERACTION_ORIGIN, CustomPromptSandboxContext


def _case(
    name: str,
    prompt: str,
    skill: str,
    downstream_tools: list[str],
    skill_delivery: SkillDelivery,
    *,
    alternate_skills: list[str] | None = None,
    excluded_skill: str | None = None,
    setup: Callable[[CustomPromptSandboxContext], dict[str, Any]] | None = None,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected=skill_distribution_expectations(
            skill,
            downstream_tools,
            skill_delivery,
            alternate_skills=alternate_skills,
            excluded_skill=excluded_skill,
        ),
        metadata={"expected_skill": skill, "skill_delivery": skill_delivery},
        setup=setup,
        # The sandbox identifies as the eval consumer, which the MCP serves `learn` to; the default
        # (Desktop) consumer is excluded from `learn`, so the exec arm would never exercise it.
        interaction_origin=EVAL_INTERACTION_ORIGIN,
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
            skill="diagnosing-experiment-health",
            # The support front door wraps the diagnostic skill and also answers this prompt.
            alternate_skills=["debugging-experiments"],
            downstream_tools=["experiment-get", "experiment-results-get", "execute-sql"],
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
        _case(
            name="session_errors_to_traces_and_logs",
            prompt=(
                "For session 3db8f93b-4c5d-4f1c-aaf1-9c891632eb18, find the traces for its captured errors "
                "and the logs from each trace. Tell me where a link is missing."
            ),
            skill="linking-errors-to-traces",
            downstream_tools=["execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="occurrence_to_trace_and_replay",
            prompt=(
                "Find the OpenTelemetry trace, same-trace logs, and replay for error occurrence "
                "c63f0d39-86ea-4a55-9a5b-c25339875390."
            ),
            skill="linking-errors-to-traces",
            downstream_tools=["execute-sql"],
            skill_delivery=ctx.skill_delivery,
        ),
        _case(
            name="replay_summary_without_trace_request",
            prompt=(
                "Summarize what happened in recording 24d9f620-6d35-4b48-91aa-b634b0f15f64 "
                "and the main actions on screen."
            ),
            skill="investigating-replay",
            downstream_tools=["session-recording-get"],
            skill_delivery=ctx.skill_delivery,
            excluded_skill="linking-errors-to-traces",
        ),
        _case(
            name="error_triage_without_trace_request",
            prompt=(
                "Which active error tracking issues are affecting the most users this week? "
                "Give me a short list of what to investigate first."
            ),
            skill="triaging-error-issues",
            downstream_tools=["query-error-tracking-issues-list"],
            skill_delivery=ctx.skill_delivery,
            excluded_skill="linking-errors-to-traces",
            setup=seed_error_tracking_issues,
        ),
        _case(
            name="single_issue_diagnosis_without_trace_request",
            prompt=(
                "Investigate the checkout TimeoutError issue. Who is affected, when did it start, "
                "and what should we check next?"
            ),
            skill="investigating-error-issue",
            downstream_tools=["query-error-tracking-issues-list", "query-error-tracking-issue"],
            skill_delivery=ctx.skill_delivery,
            excluded_skill="linking-errors-to-traces",
            setup=seed_error_tracking_issues,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-skill-distribution-cli",
        offline_suite=offline_suite(
            "cli_mcp/eval_skill_distribution::eval_skill_distribution",
            metrics=[
                "skill_search_first",
                "expected_skill_discovered",
                "expected_skill_loaded",
                "excluded_skill_not_loaded",
                "skill_loaded_before_tool",
                "no_bundled_skill_bypass",
                "no_exec_skill_bypass",
            ],
        ),
        cases=cases,
        scorers=[
            SkillSearchFirst(),
            ExpectedSkillDiscovered(),
            ExpectedSkillLoaded(),
            ExcludedSkillNotLoaded(),
            SkillLoadedBeforeTool(),
            NoBundledSkillBypass(),
            NoExecSkillBypass(),
        ],
        ctx=ctx,
    )
