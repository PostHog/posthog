"""Do the SQL insights the agent saves behave like insights on a dashboard?

Agents save SQL insights with the window from the request written into the query, for example
``timestamp >= now() - INTERVAL 14 DAY``. The insight then ignores the dashboard and insight
date picker: the user changes the range and nothing changes. Agents also order a SQL time series
newest first, which puts the most recent bucket on the left of the chart.

Each case asks for a SQL insight, so SQL is the right tool and the suite grades only how the
query is written. ``saved_sql_insight`` is the manipulation check: drop a case that saved no
SQL insight before reading the other scores. ``sql_follows_date_filter`` and
``sql_time_axis_ascending`` grade the saved query.

Run on the latest Claude Opus and GPT Sol models, one runtime per run:

    hogli evals eval_sql_insight_hygiene --agent-runtime claude --agent-model claude-opus-5-5 --trials 3
    hogli evals eval_sql_insight_hygiene --agent-runtime codex --agent-model gpt-6.1-sol --trials 3
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.offline_config import offline_suite
from products.posthog_ai.evals.product_analytics.sql_insight_scorers import (
    SavedSqlInsight,
    SqlFollowsDateFilter,
    SqlTimeAxisAscending,
)


def _case(name: str, prompt: str, *, on_dashboard: bool, time_series: bool) -> SandboxedEvalCase:
    expected: dict[str, dict] = {
        "saved_sql_insight": {"on_dashboard": on_dashboard},
        "sql_follows_date_filter": {},
    }
    if time_series:
        expected["sql_time_axis_ascending"] = {}
    return SandboxedEvalCase(name=name, prompt=prompt, expected=expected)


async def eval_sql_insight_hygiene(ctx: EvalContext) -> None:
    cases = [
        _case(
            "daily_uploads_on_dashboard",
            "Write a HogQL query that counts uploaded_file events per day for the last 14 days, and add it as a "
            "line chart to the 🔑 Key metrics dashboard.",
            on_dashboard=True,
            time_series=True,
        ),
        _case(
            "weekly_median_file_size_on_dashboard",
            "Add a SQL insight to the 🔑 Key metrics dashboard that shows the median file_size_b of uploaded_file "
            "events per week over the last 8 weeks.",
            on_dashboard=True,
            time_series=True,
        ),
        _case(
            "weekly_revenue_on_dashboard",
            "Add a SQL insight to the 💸 Revenue dashboard with weekly revenue from paid_bill events, as the sum of "
            "amount_usd, over the last 12 weeks.",
            on_dashboard=True,
            time_series=True,
        ),
        _case(
            "upload_gap_leaderboard_on_dashboard",
            "Add a SQL insight to the 🔑 Key metrics dashboard that lists the 10 users with the longest gap in hours "
            "between their first and second uploaded_file event in the last 30 days.",
            on_dashboard=True,
            time_series=False,
        ),
        _case(
            "daily_downloading_users_insight",
            "Save a HogQL insight that charts daily unique users who downloaded_file over the last 30 days.",
            on_dashboard=False,
            time_series=True,
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-sql-insight-hygiene-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_sql_insight_hygiene::eval_sql_insight_hygiene",
            metrics=["saved_sql_insight", "sql_follows_date_filter", "sql_time_axis_ascending"],
        ),
        cases=cases,
        scorers=[SavedSqlInsight(), SqlFollowsDateFilter(), SqlTimeAxisAscending()],
        ctx=ctx,
    )
