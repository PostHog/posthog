"""Eval: the agent reads the project before it configures a new experiment.

Each case seeds one page with a known traffic shape (logged-out share, a server that also reads
the flag, revenue, return visits, low traffic, a shared metric already in use) and asks, in plain
words, for an experiment on that page. The user is not available, so the agent has to choose
bucketing, metrics and running time itself and say which choices are guesses.

Scores come from the created experiment (bucketing, persistence, window units, stored running
time, the reused shared metric, one flag) and from two judges on the final summary.

The `experiment-setup-context` MCP tool is behind a flag. Compare runs with and without it:

    hogli evals eval_setup_inference --trials 3
    hogli evals eval_setup_inference --trials 3 --mcp-flag experiment-setup-context
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.posthog_ai.evals.experiments.setup_scorers import (
    BUCKETING_DEFAULT,
    BUCKETING_PERSIST_OR_DEVICE_ID,
    BucketingFitsSurface,
    MetricWindowsHaveUnits,
    PrimaryMetricShape,
    RunningTimeStored,
    SetupSummaryCallouts,
    SetupSummaryTiers,
    SharedMetricReused,
    SingleFlagCreated,
)
from products.posthog_ai.evals.experiments.setup_seeders import (
    SHARED_SHARES_METRIC_NAME,
    seed_checkout_revenue,
    seed_landing_page_anonymous,
    seed_logged_in_team_page,
    seed_low_traffic_page,
    seed_pricing_crosses_login,
    seed_pricing_server_local_evaluation,
    seed_retention_files_page,
    seed_shared_metric_reuse,
)

_UNATTENDED = (
    " I'm away for the rest of the day and can't answer questions, so set it up as a draft with its "
    "metrics, don't launch it, and tell me what you set up."
)
_PRICING_PROMPT = (
    "We redesigned the /pricing/ page with a simpler plan comparison. Set up an experiment to see "
    "whether it gets more people to upgrade their plan." + _UNATTENDED
)
_CROSSES_LOGIN_CALLOUT = (
    "The pricing page is seen by the same people both logged out and logged in, so default user-id "
    "bucketing can switch their variant at login; persistence or device-id bucketing is needed, "
    "and the user should confirm the choice."
)


async def eval_setup_inference(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="landing_page_anonymous",
            prompt=(
                "Test a new headline on our /lp/secure-sharing/ landing page to see if it gets more "
                "signups." + _UNATTENDED
            ),
            setup=seed_landing_page_anonymous,
            expected={
                "bucketing_fits_surface": BUCKETING_DEFAULT,
                "primary_metric_shape": {"metric_types": ["funnel"], "event": "signed_up", "requires_window": True},
                "running_time_stored": True,
                "setup_summary_callouts": [
                    "Almost all visitors to the landing page are logged out, so default bucketing "
                    "without persistence fits.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="pricing_crosses_login",
            prompt=_PRICING_PROMPT,
            setup=seed_pricing_crosses_login,
            expected={
                "bucketing_fits_surface": BUCKETING_PERSIST_OR_DEVICE_ID,
                "primary_metric_shape": {"metric_types": ["funnel"], "event": "upgraded_plan"},
                "running_time_stored": True,
                "setup_summary_callouts": [_CROSSES_LOGIN_CALLOUT],
            },
        ),
        SandboxedEvalCase(
            name="pricing_server_local_evaluation",
            prompt=_PRICING_PROMPT,
            setup=seed_pricing_server_local_evaluation,
            expected={
                "bucketing_fits_surface": BUCKETING_DEFAULT,
                "primary_metric_shape": {"metric_types": ["funnel"], "event": "upgraded_plan"},
                "running_time_stored": True,
                "setup_summary_callouts": [
                    "Flags on this page are also evaluated on a server, with local evaluation, so "
                    "persistence cannot be used there.",
                    "The server and the browser must use the same user identity and flag value, "
                    "and whether they do is left for the user to decide or check.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="logged_in_team_page",
            prompt=(
                "Test a redesigned team settings page (/account/team/) to see if it gets more people "
                "inviting team members." + _UNATTENDED
            ),
            setup=seed_logged_in_team_page,
            expected={
                "bucketing_fits_surface": BUCKETING_DEFAULT,
                "primary_metric_shape": {"metric_types": ["funnel", "mean"], "event": "invited_team_member"},
                "running_time_stored": True,
                "setup_summary_callouts": [
                    "Everyone who sees the team settings page is logged in, so default bucketing "
                    "without persistence fits.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="checkout_revenue",
            prompt=(
                "Test a new layout for the upgrade checkout page (/account/billing/checkout/) and "
                "measure whether it increases revenue per user." + _UNATTENDED
            ),
            setup=seed_checkout_revenue,
            expected={
                "primary_metric_shape": {
                    "metric_types": ["mean"],
                    "event": "checkout_completed",
                    "math": "sum",
                    "math_property": "revenue",
                },
                "running_time_stored": True,
                "setup_summary_callouts": [
                    "Revenue per order is heavy-tailed (a few very large orders), so outliers should "
                    "be capped (winsorized) or the result will be noisy.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="retention_files_page",
            prompt=(
                "We're changing the layout of the /files/ page. Set up an experiment to see whether "
                "more people come back and upload files again in the weeks after their visit." + _UNATTENDED
            ),
            setup=seed_retention_files_page,
            expected={
                "primary_metric_shape": {"metric_types": ["retention"]},
                "setup_summary_callouts": [
                    "Only users who have had the full return window should be counted (matured "
                    "users), or recent users drag the retention rate down.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="low_traffic_page",
            prompt=(
                "Test a shorter demo request form on the /enterprise/ page to see if we get more demo "
                "requests." + _UNATTENDED
            ),
            setup=seed_low_traffic_page,
            expected={
                "running_time_stored": True,
                "setup_summary_callouts": [
                    "At this page's traffic and demo-request rate, the experiment would need far "
                    "longer than a few weeks to detect a realistic effect.",
                    "A more frequent event earlier in the journey is proposed as the primary "
                    "metric, or another way to make the test feasible.",
                ],
            },
        ),
        SandboxedEvalCase(
            name="shared_metric_reuse",
            prompt=(
                "Test a more visible share button on the /files/ page to get people sharing more files." + _UNATTENDED
            ),
            setup=seed_shared_metric_reuse,
            expected={
                "shared_metric_reused": True,
                "running_time_stored": True,
                "setup_summary_callouts": [
                    f"The existing shared metric '{SHARED_SHARES_METRIC_NAME}' is reused rather "
                    "than a new metric created.",
                ],
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-setup-inference-cli",
        cases=cases,
        scorers=[
            RequiredToolCall(required={"experiment-create"}, name="experiment_created"),
            SingleFlagCreated(),
            BucketingFitsSurface(),
            PrimaryMetricShape(),
            MetricWindowsHaveUnits(),
            RunningTimeStored(),
            SharedMetricReused(),
            SetupSummaryTiers(),
            SetupSummaryCallouts(),
        ],
        ctx=ctx,
    )
