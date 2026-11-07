"""Does a "why did this chart change?" investigation still end with the chart explanation?

Each case pulls the agent toward a different ending: a pasted chat thread invites a reply
written for that thread, an ask for SQL makes most evidence SQL, and a long checklist puts the
investigate-metric skill's last step far back in context. ``plain_question`` is the control.

    hogli evals eval_explain_chart_distractors --trials 3
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall, RequiredToolCall
from products.posthog_ai.evals.offline_config import offline_suite
from products.posthog_ai.evals.product_analytics.explain_chart_scorers import (
    EXPLAIN_CHART_TOOL,
    NOTEBOOK_CREATE_TOOLS,
    BriefReplyAfterExplanation,
    ExplainChartEndsInvestigation,
    ExplainedSavedInsight,
)

CHAT_THREAD_PROMPT = """Pasting a thread from our #growth channel:

> dana: weekly signups look off to me, does anyone know what happened?
> marco: could be the onboarding test wrapping up, or the pricing page changes
> dana: or tracking broke again
> marco: someone should look before Monday's review

Can you work out what changed in the "Weekly signups" insight? I'll paste your answer back into the thread."""

SQL_PROMPT = (
    'Why did "Daily unique visitors over time" change recently? I trust raw SQL more than the insight builder, '
    "so do the digging in HogQL with execute-sql: break visitors down by referring domain, country, browser and "
    "device type, and compare the last two weeks with the weeks before."
)

LONG_INVESTIGATION_PROMPT = (
    'I need a thorough root-cause analysis of the "Weekly file volume" insight. Check every experiment and '
    "feature flag that was active in the window, look at annotations, break the metric down by file type, plan, "
    "country and browser, look at the people behind any spike or dip, and rule out each hypothesis before you "
    "conclude. Run as many queries as you need."
)


async def eval_explain_chart_distractors(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="plain_question", prompt='Why did our "Weekly signups" insight change over the last few weeks?'
        ),
        SandboxedEvalCase(name="chat_thread", prompt=CHAT_THREAD_PROMPT),
        SandboxedEvalCase(name="sql_evidence", prompt=SQL_PROMPT),
        SandboxedEvalCase(name="long_investigation", prompt=LONG_INVESTIGATION_PROMPT),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-explain-chart-distractors-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_explain_chart_distractors::eval_explain_chart_distractors",
            metrics=[
                "explained_chart",
                "explain_chart_ends_investigation",
                "explained_saved_insight",
                "no_notebook_created",
                "brief_reply_after_explanation",
            ],
        ),
        cases=cases,
        scorers=[
            RequiredToolCall([EXPLAIN_CHART_TOOL], name="explained_chart"),
            ExplainChartEndsInvestigation(),
            ExplainedSavedInsight(),
            NoToolCall(NOTEBOOK_CREATE_TOOLS, name="no_notebook_created"),
            BriefReplyAfterExplanation(),
        ],
        ctx=ctx,
    )
