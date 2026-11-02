from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.skill_usage_scorers import SkillAnswerCorrectness
from products.posthog_ai.evals.offline_config import offline_suite

# Scored only on the final answer, so the same cases compare MCP setups that expose different tools.
_TASKS: list[tuple[str, str, str]] = [
    (
        "running_experiments",
        "Which experiments are running right now, and what variants does each one have?",
        "Three experiments are running: file-engagement-v2 (control, red, blue), "
        "upgrade-prompt-v1 (control, aggressive, subtle), and "
        "bias-warning-demo-uneven-split (control, test).",
    ),
    (
        "winning_experiment",
        "Which of our finished experiments shipped a winner, and which variant won?",
        "onboarding-test-v1 is the experiment that won, and the red variant won.",
    ),
    (
        "activation_funnel_steps",
        "We have a saved insight called Activation. What steps does it measure, in order?",
        "The steps are signed_up, then the Interacted with file action, then upgraded_plan.",
    ),
    (
        "error_issues_by_type",
        "List the error tracking issues in this project with the exception type behind each one.",
        "Checkout API timeout is a TimeoutError, File preview render failure is a RenderError, "
        "and Team invite rejected is a TypeError.",
    ),
    (
        "top_signup_country",
        "Which country do most of our signups come from over the last 90 days?",
        "The United States is the top country for signups.",
    ),
    (
        "pinned_dashboards",
        "Which dashboards are pinned in this project?",
        "The pinned dashboards are 🔑 Key metrics and 💸 Revenue.",
    ),
    (
        "file_previews_rollout",
        "Is the file-previews feature flag rolled out to all users?",
        "No. file-previews is limited to an internal allowlist of email addresses, not all users.",
    ),
    (
        "internet_explorer_signup_conversion",
        "Over the last 90 days, do visitors on Internet Explorer convert from a homepage pageview "
        "to signed_up better or worse than visitors on other browsers?",
        "Internet Explorer visitors convert to signed_up worse than visitors on other browsers.",
    ),
]


async def eval_mcp_surface_comparison(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-mcp-surface-comparison-cli",
        offline_suite=offline_suite(
            "cli_mcp/eval_mcp_surface_comparison::eval_mcp_surface_comparison",
            metrics=["skill_answer_correctness"],
        ),
        cases=[
            SandboxedEvalCase(
                name=name,
                prompt=prompt,
                expected={"skill_answer_correctness": {"expected_answer": expected_answer}},
            )
            for name, prompt, expected_answer in _TASKS
        ],
        scorers=[SkillAnswerCorrectness()],
        ctx=ctx,
    )
