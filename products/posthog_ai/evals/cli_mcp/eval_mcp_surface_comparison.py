from __future__ import annotations

from collections.abc import Callable
from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.skill_usage_scorers import SkillAnswerCorrectness
from products.posthog_ai.evals.error_tracking.seeders import seed_error_tracking_issues
from products.posthog_ai.evals.offline_config import offline_suite
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

_EXPERIMENT_NAMING = "Each experiment may be identified by either its name or its flag key."


def _case(
    name: str,
    prompt: str,
    expected_answer: str,
    setup: Callable[[CustomPromptSandboxContext], dict[str, Any]] | None = None,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"skill_answer_correctness": {"expected_answer": expected_answer}},
        setup=setup,
    )


# Scored only on the final answer, so the same cases can compare MCP surfaces that expose different tools.
# Run once per `--mcp-surface`; the runs share this experiment and differ in their `mcp_surface` metadata.
_CASES: list[SandboxedEvalCase] = [
    _case(
        "running_experiments",
        "Which experiments are running right now, and what variants does each one have?",
        "Three experiments are running: File engagement boost (file-engagement-v2) with control, red and blue; "
        "Upgrade prompt experiment (upgrade-prompt-v1) with control, aggressive and subtle; and "
        "Bias warning demo: uneven split with multi-variant (bias-warning-demo-uneven-split) with control and test. "
        + _EXPERIMENT_NAMING,
    ),
    _case(
        "winning_experiment",
        "Which of our finished experiments shipped a winner, and which variant won?",
        "The experiment that won is z. Onboarding flow test (onboarding-test-v1), and the red variant won. "
        + _EXPERIMENT_NAMING,
    ),
    _case(
        "activation_funnel_steps",
        "We have a saved insight called Activation. What steps does it measure, in order?",
        "The steps are signed_up, then the Interacted with file action, then upgraded_plan.",
    ),
    _case(
        "error_issues_by_type",
        "List every error tracking issue in this project, including resolved ones, with the exception type behind each one.",
        "Checkout API timeout is a TimeoutError, File preview render failure is a RenderError, "
        "Team invite rejected is a TypeError, and the resolved Legacy billing alert is a BillingAlertError.",
        setup=seed_error_tracking_issues,
    ),
    _case(
        "top_signup_country",
        "Which country do most of our signups come from over the last 90 days, and what share of signups is that?",
        "The United States is the top country, with a clear majority of signups. "
        "Any share from 60% to 80% matches the expected value.",
    ),
    _case(
        "pinned_dashboards",
        "Which dashboards are pinned in this project?",
        "The pinned dashboards are 🔑 Key metrics and 💸 Revenue.",
    ),
    _case(
        "file_previews_rollout",
        "Is the file-previews feature flag rolled out to all users?",
        "No. file-previews is limited to an internal allowlist of email addresses, not all users.",
    ),
    _case(
        "internet_explorer_signup_conversion",
        "Over the last 90 days, what share of visitors on Internet Explorer go from a homepage pageview "
        "to signed_up, compared with visitors on other browsers?",
        "The answer reports a measured conversion rate for Internet Explorer and one for other browsers, "
        "and the Internet Explorer rate is the lower of the two. Any specific rates count.",
    ),
]


async def eval_mcp_surface_comparison(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-mcp-surface-comparison-cli",
        offline_suite=offline_suite(
            "cli_mcp/eval_mcp_surface_comparison::eval_mcp_surface_comparison",
            metrics=["skill_answer_correctness"],
        ),
        cases=_CASES,
        scorers=[SkillAnswerCorrectness()],
        ctx=ctx,
    )
